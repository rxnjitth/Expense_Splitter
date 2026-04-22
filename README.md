# 💸 SplitWise Pro — Smart Expense Splitter

A real-time expense splitting web app. Create groups, add expenses, track balances, and settle up — no login required.

## 🚀 Quick Start (60 seconds)

### 1. Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Run the server
```bash
cd backend
python main.py
```

### 3. Open the app
Visit **http://localhost:8000**

---

## ✨ Features

| Feature | Details |
|---|---|
| 👥 Group Management | Create groups, share via link/ID, add members |
| 💸 Expense Tracking | Equal, custom, or percentage splits |
| ⚖️ Balance Tracking | Real-time net balance per member |
| ✅ Smart Settlement | Greedy algorithm minimizes transactions |
| 🤖 Auto-categorization | Keyword-based: food, travel, accommodation, etc. |
| 📊 Analytics | Spending by category, per-person breakdown |
| 🔴 Real-Time | WebSocket updates across all open tabs |

## 📁 Project Structure

```
Expense_Splitter/
├── backend/
│   ├── main.py          ← FastAPI app + all endpoints
│   ├── database.py      ← SQLAlchemy models + SQLite
│   ├── services.py      ← Balance calc + AI categorization
│   ├── requirements.txt
│   └── .env
└── frontend/
    └── index.html       ← Complete SPA (no build step!)
```

## 🔌 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/users` | Create/get user |
| POST | `/api/groups` | Create group |
| GET | `/api/groups/{id}` | Get group details |
| POST | `/api/groups/{id}/members` | Add member |
| POST | `/api/expenses` | Add expense |
| GET | `/api/groups/{id}/expenses` | List expenses |
| DELETE | `/api/expenses/{id}` | Delete expense |
| GET | `/api/groups/{id}/balances` | Get balances |
| GET | `/api/groups/{id}/settlements` | Settlement plan |
| GET | `/api/analytics/groups/{id}` | Group analytics |
| WS | `/ws/{group_id}` | Real-time updates |

## 🧮 Algorithms

- **Equal split**: amount divided equally among participants
- **Balance**: Each expense credits payer, debits participants by their share
- **Settlement**: Greedy max-matching on debtors/creditors (minimizes transaction count)

## 🌍 Environment Variables

```env
DATABASE_URL=sqlite:///./expense_splitter.db
OPENAI_API_KEY=   # optional, for real AI categorization
```
