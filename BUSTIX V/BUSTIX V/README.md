# BusTix — Digital Bus Ticketing System

## Quick Start

```bash
# 1. Install Flask (only dependency)
pip install flask

# 2. Run the application
python app.py

# 3. Open in browser
http://localhost:5000
```

## Demo Login Credentials

| Role | Username | Password |
|------|----------|----------|
| Manager | `manager` | `manager123` |
| Conductor | `conductor1` | `pass123` |
| Conductor | `conductor2` | `pass123` |

---

## System Features

### Manager Dashboard
- **Live Overview** — Today's revenue, ticket count, active trips, total passengers
- **7-Day Revenue Chart** — Bar chart + ticket volume overlay
- **Route Performance** — Doughnut chart showing revenue distribution across routes
- **Live Trips Table** — Real-time passenger count with capacity progress bar
- **Trip Detail Modal** — View all tickets for any specific trip
- **Fleet Management** — Add/view buses
- **Route Management** — Add/view routes
- **Staff Management** — Add conductors and managers
- **Schedule Trips** — Assign bus, route, conductor, and departure time
- **Reports Page** — Trip reports + revenue trend with CSV export

### Conductor Dashboard
- **My Trips** — See all assigned trips (active/scheduled)
- **Start Trip** — Change status from scheduled → active
- **Issue Ticket** — Record passenger payment in real time
  - Auto-fills fare from route
  - Supports Cash / M-Pesa / Card payment
  - Generates unique ticket number (e.g. TKT-AB3X9Y2Z)
- **Live Ticket Feed** — See last issued ticket + recent tickets
- **My Summary** — Personal revenue and passenger stats

### Reports
- Date range filter + route filter
- Trip-level breakdown table
- Revenue trend chart (30/90 day views)
- CSV export

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3 + Flask |
| Database | SQLite (via sqlite3) |
| Frontend | HTML/CSS/JavaScript |
| Charts | Chart.js 4.4 |
| Fonts | Syne + DM Sans (Google Fonts) |

No external Python packages beyond Flask required.

---

## File Structure

```
bustix/
├── app.py              # Flask application + all routes + DB logic
├── bustix.db           # SQLite database (auto-created)
├── requirements.txt
├── README.md
└── templates/
    ├── base.html       # Shared layout, sidebar, styles
    ├── login.html      # Login page
    ├── manager.html    # Manager dashboard
    ├── conductor.html  # Conductor dashboard
    └── reports.html    # Reports & analytics
```

---

## Seeded Demo Data
- 30 days of historical trip data (~150 trips, ~3800 tickets)
- 5 routes: Nairobi–Mombasa, Nairobi–Kisumu, Nairobi–Nakuru, Nairobi–Eldoret, Mombasa–Malindi
- 4 buses with Kenyan registration plates
- Today: 3 trips (1 active with 15 passengers, 2 scheduled)
