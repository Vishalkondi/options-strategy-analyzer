# Development Setup & Troubleshooting

## The Error You're Seeing

```
[vite] http proxy error: /api/stats
Error: connect ECONNREFUSED 127.0.0.1:8000
```

**This means:** Your frontend dev server is running ✅, but the **backend API server is NOT running** ❌

## Quick Fix: Start Both Servers

### Terminal 1: Start the Backend
```bash
cd e:\options-strategy-analyzer\osa
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run the backend
PYTHONPATH=. python -m uvicorn server.main:app --reload
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

### Terminal 2: Start the Frontend (in a new terminal)
```bash
cd frontend
npm install
npm run dev
```

Expected output:
```
➜  Local:   http://localhost:5173/
```

## Then Open
- **UI**: http://localhost:5173 (frontend)
- **API Docs**: http://127.0.0.1:8000/docs (backend)

---

## Full Quickstart Script

**Windows**: Create `start-dev.bat`
```batch
@echo off
echo Starting OSA Development Stack...
echo.

REM Terminal 1: Backend
start "OSA Backend" cmd /k "cd /d %~dp0 && .venv\Scripts\activate && PYTHONPATH=. python -m uvicorn server.main:app --reload"

REM Wait 3 seconds for backend to start
timeout /t 3 /nobreak

REM Terminal 2: Frontend
start "OSA Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo.
echo ✓ Backend running on http://127.0.0.1:8000
echo ✓ Frontend running on http://localhost:5173
echo ✓ API Docs at http://127.0.0.1:8000/docs
```

Run with: `start-dev.bat`

---

## Verify Both Servers

### Check Backend
```bash
curl http://127.0.0.1:8000/docs
# Should return HTML page with Swagger UI
```

### Check Frontend
```bash
# Open browser to http://localhost:5173
# Should show the UI (will see "BLOCKED" states if no data, but no connection errors)
```

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `ECONNREFUSED 127.0.0.1:8000` | Backend not running | Start backend first (see above) |
| `npm ERR! not found: vite` | Dependencies not installed | Run `npm install` in `frontend/` |
| `ModuleNotFoundError: No module named 'server'` | Python env not activated | Run `.venv\Scripts\activate` |
| Port 8000 already in use | Another process using it | `lsof -i :8000` or `netstat -ano \| findstr :8000` |
| Port 5173 already in use | Another process using it | Kill it or run `npm run dev -- --port 5174` |

---

## Architecture Quick Reference

```
┌─────────────────────────────────────────────────────────┐
│  Browser: http://localhost:5173                         │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Frontend React App (Vite dev server)              │ │
│  │  - UI components, state management                 │ │
│  │  - Proxies /api/* requests to backend              │ │
│  └────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP /api/*
                     ↓
┌─────────────────────────────────────────────────────────┐
│  http://127.0.0.1:8000                                  │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Backend FastAPI + Uvicorn                         │ │
│  │  - REST API endpoints (/api/*)                     │ │
│  │  - WebSocket relay (live market data)              │ │
│  │  - DuckDB database engine                          │ │
│  │  - Backtesting logic                               │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## Environment Variables

Copy `.env.example` to `.env` and update with your values:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Key variables:
- `DEBUG=true` — Enable verbose logging
- `KITE_API_KEY`, `KITE_ACCESS_TOKEN` — Zerodha credentials (optional for demo)
- `DATABASE_PATH` — Path to DuckDB file
- `CORS_ORIGINS` — Allowed frontend URLs

---

## Smoke Test (Verify Everything Works)

```bash
# Backend must be running first
PYTHONPATH=. python scripts_smoke_test.py
```

This runs:
1. Data import (demo CSV)
2. Backtest execution
3. Trade persistence
4. Reproducibility check

Success = all endpoints working end-to-end ✓

---

## Next Steps

1. ✅ Start both backend and frontend servers (see above)
2. 📊 Go to **Data Manager**, import `demo` path
3. ⚙️ Go to **Strategy Runner**, pick strategy + symbol
4. ▶️ Run a backtest
5. 📈 Run it again with different params, see **Compare Runs** light up
6. 🔍 Check **Trade Explorer** for full trade table

