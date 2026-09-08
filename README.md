# Options Strategy Analyzer — working backend (demo-data build)

This is a real, tested, running implementation of Phases A–G against
**synthetic demo data** (`data/raw/demo/DEMOSTK_*.csv`). It is not a mockup:
every endpoint below actually imports data, runs a backtest, and persists
real trades to DuckDB. What it is NOT is a claim that the strategy logic
or indicator formulas are your validated, correctness-checked source —
see "What's a placeholder" below before trusting any P&L number.

## Quickstart

### Option 1: One-Click Startup (Windows)
```bash
# Just double-click this file from Windows Explorer:
start-dev.bat
```
This automatically starts both backend and frontend servers in separate terminals. Wait 5-10 seconds for initialization, then open http://localhost:5173.

### Option 2: Manual Startup (Any OS)

**Terminal 1 — Backend API:**
```bash
python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=. python -m uvicorn server.main:app --reload
# ✓ Should see: Uvicorn running on http://127.0.0.1:8000
```

**Terminal 2 — Frontend UI:**
```bash
cd frontend
npm install
npm run dev
# ✓ Should see: Local: http://localhost:5173
```

### Verify It Works
- **Frontend**: Open http://localhost:5173 in browser
- **Backend**: Open http://127.0.0.1:8000/docs for API documentation
- **Connection Banner**: Should show "connected" (not "Backend not running")

> ⚠️ **Common Mistake**: If you see `Error: connect ECONNREFUSED 127.0.0.1:8000`, it means the backend isn't running. Make sure both terminals have the servers running before opening the browser.

### Prove Everything Works End-to-End
```bash
# Backend must be running first
PYTHONPATH=. python scripts_smoke_test.py
```

### Run Tests
```bash
PYTHONPATH=. python -m pytest -q
```

### Next Steps
1. Open **Data Manager**, import path `demo`
2. Go to **Strategy Runner**, pick the strategy + `DEMOSTK` symbol
3. Run a backtest
4. Run it again with different params to see **Compare Runs** work
5. Check **Trade Explorer** for the global trade table

## Frontend

Real React 19 + TypeScript + Tailwind v4 app, built (not mocked) against the API above:

- **Data Manager** — live import, per-file quality reports, SHA-256/idempotency display, imports history table
- **Strategy Runner** — strategy + symbol pickers populated from live data, a parameter form generated from each strategy's YAML schema (no hand-coded form per strategy, per the architecture principle), live backtest execution, trade + leg breakdown
- **Compare Runs** — real multi-run comparison (metrics table + cumulative P&L chart via Recharts), shows the "blocked" state honestly when fewer than 2 runs exist yet
- **Trade Explorer** — global, filterable (outcome/exit-reason), paginated trade table across all runs, with expandable per-trade leg detail
- **Strategy Builder** — deferred placeholder, matching the project's stated scope (not built until the core backtesting system is stable)

Design: every card that touches real numbers carries a small provenance tag (`● DEMO DATA` /
`● BLOCKED`) — a deliberate, visible reminder of the project's core rule (never fabricate,
always show data lineage) rather than a generic dashboard skin. Light/dark theme toggle in
the top bar, matching the original screenshots' interaction pattern.

TypeScript strict-mode typecheck and `vite build` both pass clean (verified, not assumed).

## What's real and tested

- **Ingestion** (`server/ingest.py`): SHA-256-based idempotent CSV import,
  OHLC sanity checks, missing-value detection, per-file quality report.
  Tested: clean rows accepted, invalid OHLC rejected, missing CLOSE
  rejected, re-import of identical file is a no-op, unrecognized filenames
  refused rather than guessed.
- **Storage** (`server/schema.sql`, `server/database.py`): single DuckDB
  file, idempotent schema application, the exact table shape described in
  your project README (imports, equity_bars, option_bars, strategies,
  runs, trades, trade_legs).
- **Indicators** (`server/indicators.py`): SMA, Wilder's ADX — standard
  textbook formulas, unit-tested for warm-up behavior and directional
  sensitivity.
- **Engine** (`server/engine.py`, `server/strategy_debit_spread.py`): loads
  bars from DuckDB, generates entry signals, prices real spread legs from
  the option_bars table, exits on target/stop/expiry, persists trades +
  legs, computes run-level P&L/win-rate, records reproducibility metadata
  (params hash, data snapshot hash, engine/app version). Tested: blocked
  status with no data, trade+leg persistence, reproducibility within
  tolerance, linear P&L scaling with lot count.
- **API** (`server/main.py`): FastAPI thin adapter — `/api/import`,
  `/api/data-coverage`, `/api/strategies`, `/api/runs` (POST + GET),
  `/api/runs/{id}/trades`. Manually verified end-to-end against a live
  running server (import -> run -> trades -> list runs).
- **Tests**: 13 passing unit/mechanics tests. 1 golden regression test
  that correctly **skips as BLOCKED** rather than being faked (see below).

## What's a placeholder — do not trust these numbers yet

Directly carried over from your `GAP_ANALYSIS.md` list, still open:

| Ref | What | Current placeholder |
| --- | --- | --- |
| B1 | Strategy source | `directional_debit_spread.yaml` is **my reference build**, not your validated 3 strategies (call/put debit spread, iron condor, vol-arb short premium). Same shape, different formulas until you supply/confirm yours. |
| B2 | Indicator source | SMA/ADX here are standard textbook formulas — not reconciled against your validated indicator code. |
| B3/B4 | Real NSE CSVs | `server/ingest.py` parses the **demo** bhavcopy-style column layout. If real files differ, the parser needs updating — see the CSV format note below. |
| B5 | Golden results | No known-good backtest result exists yet, so `tests/test_golden_regression.py` skips with an explicit reason instead of asserting anything. |
| B6 | Lot size | `lot_size` param defaults to `1` — not a real NSE lot size for any stock. |
| B7 | Position sizing | Fixed `lots` param, no capital-based or risk-based sizing logic. |
| B8 | Transaction costs | `costs` is hardcoded `0`; `net_pnl = gross_pnl - 0`. |
| B9 | NSE holiday calendar | Not wired in; trading-day-count checks don't account for holidays. |

## CSV format currently supported (demo)

Equity: `SYMBOL, SERIES, DATE, PREV_CLOSE, OPEN, HIGH, LOW, LAST, CLOSE,
VWAP, VOLUME, TURNOVER, TOTAL_TRADES, DELIVERABLE_QTY, DELIVERABLE_PCT`

Options: `INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH,
LOW, CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI,
TIMESTAMP`

Filenames must be `<SYMBOL>_equity.csv` or `<SYMBOL>_options.csv` — this
is enforced, not guessed (see `test_bad_filename_is_rejected_not_guessed`).

If your real NSE/broker files use different column names, send me one
real header row (or the file) and I'll update `server/ingest.py` to match
exactly, rather than assuming.

## Fastest path to something you can actually trust

1. Send your 3 validated strategy formulas (or point me at the source) →
   replaces the reference `directional_debit_spread.yaml` logic.
2. Send a real NSE equity + options CSV sample → unblocks B3/B4, parser
   gets updated to the real column layout.
3. Send one known-good backtest result (from your existing validated
   implementation or manual calculation) → unblocks the golden regression
   test, which is the only thing that actually proves correctness.
4. Real lot sizes per stock (B6) and your transaction-cost assumptions
   (B8) → replaces the `1` and `0` placeholders.

Everything else (frontend, Compare Runs, Trade Explorer, Strategy
Builder) builds on top of this backend once the above is confirmed —
happy to keep going on those next.

## Zerodha live-data sync

The backend now has an optional `POST /api/live/sync` endpoint. It fetches
daily NSE equity candles and historical NFO option-contract candles through
Kite and writes them into the existing DuckDB tables. It does not place
orders.

Install the dependency and provide a daily Kite access token through the
environment (never commit these values):

```bash
OA_KITE_API_KEY=your_api_key
OA_KITE_ACCESS_TOKEN=your_daily_access_token
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/live/sync \
  -H "Content-Type: application/json" \
  -d '{"symbol":"RELIANCE","date_start":"2025-08-01","date_end":"2026-08-24","expiry":"2026-08-27","strikes":[1400,1450,1500]}'
```

The access token is generated using Kite Connect's login/request-token flow
and normally expires at the end of the trading day. The endpoint selects the
nearest future expiry when `expiry` is omitted. Restrict `strikes` in real use
because Kite instrument history is fetched once per selected contract.
