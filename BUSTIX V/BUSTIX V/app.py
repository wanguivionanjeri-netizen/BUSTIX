from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from datetime import datetime, timedelta
from functools import wraps
import hashlib, os, random, string
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bustix-secret-2024-xK9mP')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Render gives DATABASE_URL starting with postgres:// — psycopg2 needs postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# psycopg2 does not support channel_binding — strip it out
DATABASE_URL = DATABASE_URL.replace('&channel_binding=require', '').replace('?channel_binding=require&', '?').replace('?channel_binding=require', '')

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def query(sql, params=(), one=False):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params or None)
    rows = cur.fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    return (result[0] if result else None) if one else result

def execute(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql + " RETURNING id", params)
    last_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return last_id

def execute_no_return(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    conn.close()

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def gen_ticket(): return 'TKT-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
def gen_trip(): return 'TR-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session: return redirect('/login')
        return f(*a, **kw)
    return d

def manager_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session or session.get('role') != 'manager': return redirect('/login')
        return f(*a, **kw)
    return d

def conductor_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session or session.get('role') not in ('conductor', 'manager'): return redirect('/login')
        return f(*a, **kw)
    return d

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/manager' if session['role'] == 'manager' else '/conductor')
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        d = request.get_json() or request.form
        user = query("SELECT * FROM users WHERE username=%s AND active=1", (d.get('username'),), one=True)
        if user and user['password_hash'] == hash_pw(d.get('password', '')):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['name'] = user['full_name']
            return jsonify({'ok': True, 'role': user['role']})
        return jsonify({'ok': False, 'msg': 'Invalid credentials'}), 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/manager')
@manager_required
def manager_dashboard(): return render_template('manager.html', name=session.get('name'))

@app.route('/manager/reports')
@manager_required
def manager_reports(): return render_template('reports.html', name=session.get('name'))

@app.route('/conductor')
@conductor_required
def conductor_dashboard(): return render_template('conductor.html', name=session.get('name'))

@app.route('/api/stats/overview')
@manager_required
def api_stats_overview():
    today = datetime.utcnow().date().isoformat()
    tmrw = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    today_rev = query("SELECT COALESCE(SUM(fare_paid),0) as r FROM tickets WHERE issued_at>=%s AND issued_at<%s", (today, tmrw), one=True)['r']
    today_tix = query("SELECT COUNT(*) as c FROM tickets WHERE issued_at>=%s AND issued_at<%s", (today, tmrw), one=True)['c']
    today_trips = query("SELECT COUNT(*) as c FROM trips WHERE departure_time>=%s AND departure_time<%s", (today, tmrw), one=True)['c']
    active = query("SELECT COUNT(*) as c FROM trips WHERE status='active'", one=True)['c']
    total_pax = query("SELECT COUNT(*) as c FROM tickets", one=True)['c']
    week = []
    for i in range(7):
        d = (datetime.utcnow().date() - timedelta(days=6-i)).isoformat()
        d2 = (datetime.utcnow().date() - timedelta(days=6-i) + timedelta(days=1)).isoformat()
        rev = query("SELECT COALESCE(SUM(fare_paid),0) as r FROM tickets WHERE issued_at>=%s AND issued_at<%s", (d, d2), one=True)['r']
        cnt = query("SELECT COUNT(*) as c FROM tickets WHERE issued_at>=%s AND issued_at<%s", (d, d2), one=True)['c']
        week.append({'date': datetime.fromisoformat(d).strftime('%a'), 'revenue': round(float(rev),2), 'tickets': cnt})
    routes = query("SELECT r.name, COUNT(tk.id) as tickets, COALESCE(SUM(tk.fare_paid),0) as revenue FROM routes r LEFT JOIN trips t ON t.route_id=r.id LEFT JOIN tickets tk ON tk.trip_id=t.id GROUP BY r.id, r.name")
    return jsonify({'today_revenue': round(float(today_rev),2), 'today_tickets': today_tix, 'today_trips': today_trips, 'active_trips': active, 'total_passengers': total_pax, 'week_data': week, 'routes': [{'name': r['name'], 'tickets': r['tickets'], 'revenue': round(float(r['revenue']),2)} for r in routes]})

@app.route('/api/trips/live')
@login_required
def api_trips_live():
    trips = query("SELECT t.*, r.origin, r.destination, r.name as route_name, r.base_fare, b.reg_number, b.capacity, u.full_name as conductor_name FROM trips t JOIN routes r ON t.route_id=r.id JOIN buses b ON t.bus_id=b.id JOIN users u ON t.conductor_id=u.id WHERE t.status IN ('active','scheduled') ORDER BY t.departure_time")
    result = []
    for t in trips:
        s = query("SELECT COUNT(*) as cnt, COALESCE(SUM(fare_paid),0) as rev FROM tickets WHERE trip_id=%s", (t['id'],), one=True)
        dep = str(t['departure_time'])
        dep_short = dep[11:16] if len(dep) > 10 else dep
        result.append({'id': t['id'], 'code': t['trip_code'], 'route': f"{t['origin']} → {t['destination']}", 'route_name': t['route_name'], 'bus': t['reg_number'], 'conductor': t['conductor_name'], 'departure': dep_short, 'status': t['status'], 'passengers': s['cnt'], 'capacity': t['capacity'], 'revenue': round(float(s['rev']),2), 'fare': float(t['base_fare'])})
    return jsonify(result)

@app.route('/api/trips', methods=['POST'])
@manager_required
def api_create_trip():
    d = request.get_json()
    code = gen_trip()
    execute("INSERT INTO trips (trip_code,route_id,bus_id,conductor_id,departure_time,status) VALUES (%s,%s,%s,%s,%s,'scheduled')", (code, d['route_id'], d['bus_id'], d['conductor_id'], d['departure_time']))
    return jsonify({'ok': True, 'trip_code': code})

@app.route('/api/trips/<int:tid>/status', methods=['PUT'])
@login_required
def api_trip_status(tid):
    d = request.get_json()
    execute_no_return("UPDATE trips SET status=%s WHERE id=%s", (d['status'], tid))
    return jsonify({'ok': True})

@app.route('/api/trips/<int:tid>/tickets')
@login_required
def api_trip_tickets(tid):
    trip = query("SELECT t.*, r.origin, r.destination FROM trips t JOIN routes r ON t.route_id=r.id WHERE t.id=%s", (tid,), one=True)
    if not trip: return jsonify({'error': 'Not found'}), 404
    tix = query("SELECT * FROM tickets WHERE trip_id=%s ORDER BY issued_at", (tid,))
    total_rev = sum(float(t['fare_paid']) for t in tix)
    dep = str(trip['departure_time'])
    return jsonify({'trip': {'code': trip['trip_code'], 'route': f"{trip['origin']} → {trip['destination']}", 'status': trip['status'], 'departure': dep[11:16] if len(dep)>10 else dep}, 'tickets': [{'number': t['ticket_number'], 'passenger': t['passenger_name'], 'seat': t['seat_number'], 'fare': float(t['fare_paid']), 'payment': t['payment_method'], 'time': str(t['issued_at'])[11:19]} for t in tix], 'total_passengers': len(tix), 'total_revenue': round(total_rev,2)})

@app.route('/api/tickets', methods=['POST'])
@conductor_required
def api_issue_ticket():
    d = request.get_json()
    trip = query("SELECT status FROM trips WHERE id=%s", (d['trip_id'],), one=True)
    if not trip or trip['status'] not in ('active', 'scheduled'):
        return jsonify({'ok': False, 'msg': 'Trip not active'}), 400
    num = gen_ticket()
    execute("INSERT INTO tickets (ticket_number,trip_id,passenger_name,seat_number,fare_paid,payment_method,issued_by,issued_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (num, d['trip_id'], d.get('passenger_name',''), d.get('seat_number',''), float(d['fare_paid']), d.get('payment_method','cash'), session['user_id'], datetime.utcnow().isoformat()))
    return jsonify({'ok': True, 'ticket_number': num, 'fare': float(d['fare_paid'])})

@app.route('/api/reports/trips')
@manager_required
def api_report_trips():
    from_dt = request.args.get('from', (datetime.utcnow()-timedelta(days=30)).strftime('%Y-%m-%d'))
    to_dt = request.args.get('to', datetime.utcnow().strftime('%Y-%m-%d'))
    route_id = request.args.get('route_id')
    sql = "SELECT t.trip_code, r.origin, r.destination, b.reg_number, u.full_name, t.departure_time, t.status, COUNT(tk.id) as passengers, COALESCE(SUM(tk.fare_paid),0) as revenue FROM trips t JOIN routes r ON t.route_id=r.id JOIN buses b ON t.bus_id=b.id JOIN users u ON t.conductor_id=u.id LEFT JOIN tickets tk ON tk.trip_id=t.id WHERE t.departure_time>=%s AND t.departure_time<=%s"
    params = [from_dt, to_dt + ' 23:59:59']
    if route_id: sql += " AND t.route_id=%s"; params.append(int(route_id))
    sql += " GROUP BY t.id, t.trip_code, r.origin, r.destination, b.reg_number, u.full_name, t.departure_time, t.status ORDER BY t.departure_time DESC"
    rows = [{'code': t['trip_code'], 'route': f"{t['origin']} → {t['destination']}", 'bus': t['reg_number'], 'conductor': t['full_name'], 'departure': str(t['departure_time']), 'status': t['status'], 'passengers': t['passengers'], 'revenue': round(float(t['revenue']),2)} for t in query(sql, params)]
    return jsonify({'trips': rows, 'total_revenue': round(sum(r['revenue'] for r in rows),2), 'total_passengers': sum(r['passengers'] for r in rows)})

@app.route('/api/reports/revenue')
@manager_required
def api_report_revenue():
    days = int(request.args.get('days', 30))
    result = []
    for i in range(days):
        d = (datetime.utcnow().date()-timedelta(days=days-1-i)).isoformat()
        d2 = (datetime.utcnow().date()-timedelta(days=days-1-i)+timedelta(days=1)).isoformat()
        rev = query("SELECT COALESCE(SUM(fare_paid),0) as r FROM tickets WHERE issued_at>=%s AND issued_at<%s", (d, d2), one=True)['r']
        cnt = query("SELECT COUNT(*) as c FROM tickets WHERE issued_at>=%s AND issued_at<%s", (d, d2), one=True)['c']
        trips_cnt = query("SELECT COUNT(*) as c FROM trips WHERE departure_time>=%s AND departure_time<%s", (d, d2), one=True)['c']
        result.append({'date': datetime.fromisoformat(d).strftime('%b %d'), 'revenue': round(float(rev),2), 'tickets': cnt, 'trips': trips_cnt})
    return jsonify(result)

@app.route('/api/routes')
@login_required
def api_routes(): return jsonify(query("SELECT id, name, origin, destination, base_fare as fare FROM routes WHERE active=1"))

@app.route('/api/routes', methods=['POST'])
@manager_required
def api_create_route():
    d = request.get_json()
    execute("INSERT INTO routes (name,origin,destination,base_fare,distance_km,active) VALUES (%s,%s,%s,%s,%s,1)", (d['name'], d['origin'], d['destination'], float(d['fare']), float(d.get('distance',0))))
    return jsonify({'ok': True})

@app.route('/api/buses')
@login_required
def api_buses(): return jsonify([{'id': b['id'], 'reg': b['reg_number'], 'model': b['model'], 'capacity': b['capacity']} for b in query("SELECT * FROM buses WHERE active=1")])

@app.route('/api/buses', methods=['POST'])
@manager_required
def api_create_bus():
    d = request.get_json()
    execute("INSERT INTO buses (reg_number,model,capacity,active) VALUES (%s,%s,%s,1)", (d['reg_number'], d.get('model',''), int(d.get('capacity',50))))
    return jsonify({'ok': True})

@app.route('/api/conductors')
@manager_required
def api_conductors(): return jsonify([{'id': u['id'], 'name': u['full_name'], 'username': u['username']} for u in query("SELECT id,full_name,username FROM users WHERE role='conductor' AND active=1")])

@app.route('/api/users', methods=['POST'])
@manager_required
def api_create_user():
    d = request.get_json()
    if query("SELECT id FROM users WHERE username=%s", (d['username'],), one=True):
        return jsonify({'ok': False, 'msg': 'Username taken'}), 400
    execute("INSERT INTO users (username,password_hash,role,full_name,active) VALUES (%s,%s,%s,%s,1)", (d['username'], hash_pw(d['password']), d['role'], d['full_name']))
    return jsonify({'ok': True})

@app.route('/api/conductor/my_trips')
@conductor_required
def api_conductor_trips():
    trips = query("SELECT t.*, r.origin, r.destination, r.base_fare, b.reg_number, b.capacity FROM trips t JOIN routes r ON t.route_id=r.id JOIN buses b ON t.bus_id=b.id WHERE t.conductor_id=%s AND t.status IN ('active','scheduled') ORDER BY t.departure_time", (session['user_id'],))
    result = []
    for t in trips:
        s = query("SELECT COUNT(*) as cnt, COALESCE(SUM(fare_paid),0) as rev FROM tickets WHERE trip_id=%s", (t['id'],), one=True)
        result.append({'id': t['id'], 'code': t['trip_code'], 'route': f"{t['origin']} → {t['destination']}", 'bus': t['reg_number'], 'departure': str(t['departure_time']), 'status': t['status'], 'passengers': s['cnt'], 'capacity': t['capacity'], 'revenue': round(float(s['rev']),2), 'fare': float(t['base_fare'])})
    return jsonify(result)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            full_name TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS routes (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            base_fare REAL NOT NULL,
            distance_km REAL,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS buses (
            id SERIAL PRIMARY KEY,
            reg_number TEXT UNIQUE NOT NULL,
            model TEXT,
            capacity INTEGER DEFAULT 50,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS trips (
            id SERIAL PRIMARY KEY,
            trip_code TEXT UNIQUE,
            route_id INTEGER,
            bus_id INTEGER,
            conductor_id INTEGER,
            departure_time TEXT,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id SERIAL PRIMARY KEY,
            ticket_number TEXT UNIQUE,
            trip_id INTEGER,
            passenger_name TEXT,
            seat_number TEXT,
            fare_paid REAL,
            payment_method TEXT DEFAULT 'cash',
            issued_at TEXT DEFAULT CURRENT_TIMESTAMP,
            issued_by INTEGER
        );
    """)
    conn.commit()
    conn.close()

def seed_data():
    if query("SELECT COUNT(*) as c FROM users", one=True)['c'] > 0:
        return
    conn = get_db()
    cur = conn.cursor()
    cur.executemany("INSERT INTO users (username,password_hash,role,full_name) VALUES (%s,%s,%s,%s)", [
        ('manager', hash_pw('manager123'), 'manager', 'James Kariuki'),
        ('conductor1', hash_pw('pass123'), 'conductor', 'Peter Mwangi'),
        ('conductor2', hash_pw('pass123'), 'conductor', 'Grace Wanjiku'),
        ('conductor3', hash_pw('pass123'), 'conductor', 'Samuel Odhiambo'),
    ])
    cur.executemany("INSERT INTO routes (name,origin,destination,base_fare,distance_km) VALUES (%s,%s,%s,%s,%s)", [
        ('Nairobi-Mombasa Express','Nairobi','Mombasa',1500,480),
        ('Nairobi-Kisumu','Nairobi','Kisumu',900,340),
        ('Nairobi-Nakuru','Nairobi','Nakuru',400,160),
        ('Nairobi-Eldoret','Nairobi','Eldoret',700,310),
        ('Mombasa-Malindi','Mombasa','Malindi',300,120),
    ])
    cur.executemany("INSERT INTO buses (reg_number,model,capacity) VALUES (%s,%s,%s)", [
        ('KDA 001K','Scania Marcopolo',49),('KDB 215Z','Volvo 9400',55),
        ('KDC 882A','Isuzu NQR',33),('KDD 447M','Mercedes Tourismo',49),
    ])
    conn.commit()
    conn.close()

    conds = [u['id'] for u in query("SELECT id FROM users WHERE role='conductor'")]
    routes = query("SELECT id, base_fare FROM routes")
    buses = query("SELECT id, capacity FROM buses")
    names = ['Alice','Bob','Carol','David','Eve','Frank','Grace','Henry','Iris','Jack']
    conn = get_db()
    cur = conn.cursor()
    for day_off in range(30, 0, -1):
        day = datetime.utcnow() - timedelta(days=day_off)
        for _ in range(random.randint(3,7)):
            r = random.choice(routes); b = random.choice(buses); c = random.choice(conds)
            dep = day.replace(hour=random.randint(5,20), minute=random.choice([0,15,30,45]), second=0, microsecond=0)
            code = gen_trip()
            cur.execute("INSERT INTO trips (trip_code,route_id,bus_id,conductor_id,departure_time,status) VALUES (%s,%s,%s,%s,%s,'completed') RETURNING id", (code, r['id'], b['id'], c, dep.isoformat()))
            tid = cur.fetchone()[0]
            for seat in range(1, random.randint(12, min(b['capacity'],40))+1):
                issued = dep + timedelta(minutes=random.randint(0,20))
                cur.execute("INSERT INTO tickets (ticket_number,trip_id,passenger_name,seat_number,fare_paid,payment_method,issued_by,issued_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (gen_ticket(), tid, random.choice(names), str(seat), r['base_fare'], random.choice(['cash','cash','cash','mpesa']), c, issued.isoformat()))
    today = datetime.utcnow().replace(second=0, microsecond=0)
    for i, r in enumerate(routes[:3]):
        b = buses[i % len(buses)]; c = conds[i % len(conds)]
        dep = today.replace(hour=8+i*2, minute=0)
        status = 'active' if i==0 else 'scheduled'
        code = gen_trip()
        cur.execute("INSERT INTO trips (trip_code,route_id,bus_id,conductor_id,departure_time,status) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (code, r['id'], b['id'], c, dep.isoformat(), status))
        tid = cur.fetchone()[0]
        if status == 'active':
            for seat in range(1,16):
                cur.execute("INSERT INTO tickets (ticket_number,trip_id,passenger_name,seat_number,fare_paid,payment_method,issued_by,issued_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                             (gen_ticket(), tid, random.choice(names), str(seat), r['base_fare'], 'cash', c, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


# Run on startup — works with both gunicorn and direct python
init_db()
seed_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
