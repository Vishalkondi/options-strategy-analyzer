# Backend + Live API — what was broken, what changed, how to run it

## TL;DR

The backend code had real bugs, but the reason **nothing live worked** was simpler:
your `.env` contained the placeholder text, not your keys.

```
OA_KITE_API_KEY=your_kite_api_key
OA_KITE_API_SECRET=your_kite_api_secret
OA_KITE_ACCESS_TOKEN=your_kite_access_token
```

The old code checked credentials with `bool(value)`. A placeholder string is
truthy, so every check passed, the startup log printed `[KITE] API key loaded: True`,
and the app built a login URL like:

```
https://kite.zerodha.com/connect/login?api_key=your_kite_api_key&v=3
```

Zerodha then returned errors that looked like backend failures. That's the 502 you saw.

**Fix your `.env` first.** Everything below is the code that was fixed so the
same class of failure reports itself clearly next time.

---

## Step 1 — Real credentials

1. Go to https://developers.kite.trade/apps and open your app.
2. Set the **Redirect URL** to exactly:
   ```
   http://127.0.0.1:8000/api/kite/login-callback
   ```
3. Copy the API key and API secret into `.env`:
   ```
   OA_KITE_API_KEY=<your real key>
   OA_KITE_API_SECRET=<your real secret>
   ```
4. Leave `OA_KITE_ACCESS_TOKEN` blank. The login flow now stores the token for you.

## Step 2 — Verify before starting the UI

```bash
python check_backend.py          # dependencies, database, offline endpoints, credentials
python check_backend.py --live   # adds one real authenticated call to Zerodha
```

This is the fastest way to answer "is it the backend or my keys?".

## Step 3 — Run

```bash
pip install -r requirements.txt
python -m uvicorn server.main:app --reload      # http://127.0.0.1:8000
cd frontend && npm install && npm run dev       # http://localhost:5173
```

Or `start-dev.bat` (Windows) / `./start-dev.sh` (macOS, Linux, WSL).

## Step 4 — Daily Zerodha login

Kite access tokens expire every morning. This is normal, not a bug.

1. `GET /api/kite/login-url` → open the returned URL in a browser.
2. Log in to Zerodha. It redirects to `/api/kite/login-callback?request_token=...`.
3. The backend exchanges the token, stores it, and starts the ticker.
4. Confirm with `GET /api/kite/diagnostics` → `"ready": true`.

---

## New diagnostic endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/kite/diagnostics` | Why live data isn't working, in plain words. Never returns a secret. |
| `GET /api/kite/profile` | One authenticated round-trip. Proves the token really works. |
| `POST /api/kite/logout` | Clears the stored token and stops the ticker. |
| `GET /api/health` | Now actually queries the database instead of always returning `ok`. |

Error codes are now distinct, so the frontend can tell the three cases apart:

| Status | `error` | Meaning |
|---|---|---|
| 400 | `kite_not_configured` | Your `.env` is wrong. Fix the key or secret. |
| 401 | `kite_reauth_required` | Log in again — token missing or expired. |
| 429 | `kite_rate_limited` | Too many Zerodha calls. Back off. |
| 502 | `kite_upstream_error` | Zerodha failed or was unreachable. Not your code. |

Previously all four returned 400, or a 500 with a stack trace.

---

## Bugs fixed in the backend

### 1. The login flow and the data sync used different tokens
`/api/kite/login-callback` stored the access token in the `kite_sessions`
table. `sync_market_data()` read `OA_KITE_ACCESS_TOKEN` straight from `.env`.
So you could log in successfully and the very next sync would still say
"set OA_KITE_ACCESS_TOKEN".

All Kite authentication now goes through `server/kite_client.py`, which prefers
the stored login token and falls back to the env token.

### 2. The database lock did nothing
`main.py` wrapped every request in a `threading.RLock` middleware to protect the
shared DuckDB connection. That lock never engaged: the middleware runs on the
event-loop thread for every request, and `RLock` is reentrant *per thread*. It
also didn't cover the KiteTicker callback thread — the one writing `paper_trades`
from outside the request cycle, which is exactly where corruption would happen.

Thread safety now lives in `server/database.py`, where every `.execute()` takes
a real lock and runs on its own DuckDB cursor. Call sites are unchanged.
Verified with 240 concurrent reads and 120 concurrent writes.

### 3. "Live market data" was a sine wave
`/api/live/market` and `/api/ws/market` returned `sin()` over hard-coded base
prices, with nothing in the payload saying so. A green dashboard showing
fabricated prices is worse than a broken one.

Now: real Kite quotes when authenticated. When not, the same fallback series but
tagged `"source": "simulated"` with `source_detail` explaining why, so the UI can
show a warning instead of a price.

### 4. Bar volume was inflated ~100x
`volume_traded` in a Kite tick is the *cumulative* day total. The old code added
that whole figure to the bar on every tick, so a bar built from 50 ticks reported
roughly 50× the day's volume. Now it uses the delta between ticks.

### 5. Bars were stamped with the server clock
`datetime.now()` instead of the tick's `exchange_timestamp`. A slow server or a
non-IST machine silently filed ticks into the wrong minute — which quietly
corrupts every indicator downstream.

### 6. The ticker never recovered from a dropped socket
No `on_error`, `on_close`, `on_reconnect` or `on_noreconnect` handlers, so
`is_running()` reported `True` forever after a disconnect. All four are wired up
now, `start()` is idempotent (both the startup hook and the login callback call
it), and exceptions inside `on_new_bar` are logged instead of vanishing into an
un-awaited Future.

### 7. Watchlist rows died on restart
Rows persisted in the `watchlist` table but were never re-subscribed after a
restart, so the UI showed active watches that weren't ticking. The ticker now
restores them on connect.

### 8. The historical sync would rate-limit itself
With no `strikes` argument, `sync_market_data` pulled *every strike* of the
nearest expiry — hundreds of `historical_data` calls fired back to back. Kite
allows about 3 per second. Now: strikes are windowed ±5 around ATM (configurable),
contract count is capped at 20 (configurable), calls are throttled to stay under
the limit, the instrument dump is cached for 6 hours instead of downloaded twice
per sync, and one failing contract no longer aborts the whole run.

### 9. Token expiry was computed in the wrong timezone
Tokens were marked valid until 23:59 *server local time*. Kite invalidates them
around 06:00 IST. Expiry is now computed against the IST boundary and stored in
UTC.

### 10. Smaller things
- `kite_client.py` had its imports at the bottom of the file and printed
  credential diagnostics to stdout on import. Now normal imports and logging.
- The NSE equity lookup matched on trading symbol alone, so an index or a
  BSE-segment row with the same symbol could win. Now filters on segment and
  instrument type.
- Deprecated `@app.on_event` replaced with a `lifespan` handler.
- The dashboard websocket loop polled forever even with zero clients connected.
- CORS now covers `127.0.0.1` as well as `localhost`, and the preview port.

---

## Tests

```bash
python -m pytest -q
```

**77 passing, 1 skipped** (up from 31). New coverage:

- `tests/test_kite_client.py` — placeholder detection, error translation,
  instrument caching, token precedence, IST expiry boundary.
- `tests/test_live_pipeline.py` — the full live chain driven by a fake Kite
  ticker: tick → 1-minute bar → strategy evaluation → paper trade row →
  websocket broadcast. This is the important one: it proves everything after
  the socket works, so the only thing between you and live data is a valid key.
- `tests/test_live_api_contract.py` — strike windowing, contract caps, failure
  isolation, and the 400/401/429/502 mapping.

The skipped test is `test_golden_regression.py`, which is still correctly
blocked: there's no client-validated result to compare against yet.

---

## Still open (unchanged by this pass)

These were flagged in the earlier gap analysis and are **not** code bugs — they
need inputs from you before any number the tool produces should be trusted:

- **Strategy logic is a reference implementation**, not your validated code.
- **Indicators (ADX/SMA) are textbook variants**, not reconciled against yours.
- **Lot sizes default to 1.** Real NSE lot sizes are still unresolved.
- **Transaction costs are 0.** Net P&L currently equals gross P&L.
- **Live paper P&L tracks the underlying's move**, not the real spread premium
  (that needs an options-chain tick subscription). The backtest path prices real
  legs from stored `option_bars`; only the live path uses the proxy.
- **No golden backtest fixture**, so nothing verifies the engine against a
  known-good result.

Until those are closed, treat every number as "the pipeline runs", not "the
number is right".

---

## Security note

Your `.env` is correctly listed in `.gitignore`, so it isn't going into git.
It *is* inside the zip you sent, though — currently harmless because it only
holds placeholders. Once you put real keys in it, don't share the zip. If a
real key ever does get shared, regenerate it at developers.kite.trade.

---

# Demo mode: replay (added for client presentations)

You do not need a Kite subscription to demonstrate the live features.

`POST /api/live/replay/start` streams bars already in DuckDB through the **same
functions the Kite ticker uses** — `live_service.ingest()` for persistence and
broadcast, `signals.on_new_bar()` for strategy evaluation. Ticks appear on the
websocket, signals fire, paper trades open and close, the dashboard updates.

Nothing is faked. These are real recorded bars moving through the real pipeline
on a different clock.

## Using it

In the UI: **Live Monitor → Replay → pick symbol/strategy/speed → Start replay.**

Or by API:

```bash
curl -X POST http://127.0.0.1:8000/api/live/replay/start \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"DEMOSTK","strategy_file":"directional_debit_spread.yaml","speed":15}'

curl http://127.0.0.1:8000/api/live/replay/status
curl -X POST http://127.0.0.1:8000/api/live/replay/stop
```

| Endpoint | Purpose |
|---|---|
| `POST /api/live/replay/start` | `{symbol, strategy_file, speed, bar_limit}` |
| `POST /api/live/replay/stop` | Stop the current replay |
| `GET /api/live/replay/status` | Progress, bars sent, signals fired |

Replay state is also included in `GET /api/live/status` under `replay`.

## The honesty guarantee

Replayed rows are stored with `source: "replay-<run id>"`, `/api/live/market`
returns `"source": "replay"` with `"Historical data, not a live feed."`, and the
Live Monitor shows an amber **REPLAY — historical bars** banner.

The banner has three states and is always on screen:

| State | Meaning |
|---|---|
| Green — **LIVE — Zerodha** | Real Kite quotes. Requires a valid key and token. |
| Amber — **REPLAY — historical bars** | Stored bars through the real pipeline. |
| Red — **SIMULATED — not real prices** | Fallback series. Not market data. |

If you present this to a client, the banner will say exactly what they are
looking at. Do not describe a replay as live data — the screen will contradict
you, and the source tag is in the database rows too.

## What replay does *not* prove

It exercises the plumbing, not the correctness of the strategy. All the open
items listed above still apply: reference strategy logic, unreconciled
indicators, lot size 1, zero transaction costs, no golden fixture. Replay
showing a profitable trade is not evidence the strategy is profitable.

---

# Analytics features (added)

## Transaction costs — closes GAP_ANALYSIS B8

Every backtest previously reported `costs = 0.0`, so net P&L was just gross
P&L renamed. `server/costs.py` adds a real NSE F&O cost model.

Three profiles, selectable per run via `cost_profile`:

| Profile | Use |
|---|---|
| `none` (default) | No costs. Keeps every existing run bit-for-bit reproducible. |
| `discount_broker` | Rs 20/order + statutory charges (Zerodha-style schedule). |
| `full_service` | Rs 100/order. A stress test: does the edge survive? |

Components: brokerage per order, STT 0.15% on sell-side premium (the
post-Budget-2026 rate, effective 1 April 2026), NSE exchange transaction
charges, SEBI charges, stamp duty on the buy side, and GST at 18% on
brokerage + exchange + SEBI only — GST is not charged on STT or stamp duty.

`GET /api/cost-profiles` returns every rate spelled out, so the numbers are
auditable rather than buried in a formula.

**These rates are defaults, not gospel.** They change with every Budget and
broker update. Verify against your own contract notes before quoting a net
return to anyone.

Costs are **opt-in** deliberately. Making them default would have silently
changed the results of every run made before the model existed.

## Performance metrics

`GET /api/runs/{run_id}/metrics` — computed from stored trades, so any
historical run can be re-analysed without re-running it.

Profit factor, expectancy, average win/loss, largest win/loss, max drawdown
(absolute and percent), longest win and loss streaks, average holding days,
P&L standard deviation, Sharpe and Sortino.

Two honesty guards are built in:
- Runs with fewer than 5 trades are flagged `reliable: false` with a note
  saying the ratios are noise. A Sharpe computed off two trades is meaningless
  and the API says so rather than printing a confident number.
- Ratios return `null` instead of infinity when the denominator is zero (no
  losing trades, or zero variance).

Sharpe and Sortino are per-trade, annualised from observed trade frequency,
not from a daily equity series. Drawdown is measured on closed trades, so
intra-trade drawdown is not captured.

## Equity curve

`GET /api/runs/{run_id}/equity` — cumulative net P&L after each closed trade,
with running peak and drawdown at every point. Starts at an origin point so it
plots cleanly.

## CSV export

`GET /api/runs/{run_id}/export.csv` — trades as a download, opens straight in
Excel.

## Parameter sweep

`POST /api/runs/sweep` — run the same backtest across a range of one
parameter.

```json
{
  "strategy_file": "directional_debit_spread.yaml",
  "symbol": "DEMOSTK",
  "parameter": "adx_threshold",
  "values": [5, 10, 15, 20, 25]
}
```

Returns net P&L, trade count, win rate, profit factor, drawdown and Sharpe for
each value, plus the best by net P&L — and a caveat, because the best value on
one sample is not the best value. A strategy that works at threshold 20 and
collapses at 19 and 21 is curve-fitted, and a sweep is how you see that.

Capped at 25 values per request.
