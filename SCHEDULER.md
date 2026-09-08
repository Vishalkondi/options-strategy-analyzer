# 30-minute scheduled capture

The backend runs a capture cycle every 30 minutes for as long as it is running.

```
backend starts -> scheduler starts -> capture -> write records
               -> wait 30 min -> capture -> write records -> repeat
```

The scheduler is an asyncio task owned by the app lifespan. **Closing or
refreshing the browser has no effect on it.** React is a viewer.

## Real data only

A cycle fetches live quotes from Zerodha via the existing `kite_client`. If Kite
is not configured or the token has expired, the cycle is recorded as **FAILED**
with the reason. It never falls back to simulated or demo prices.

That matters more than it might look. A scheduler that quietly wrote fabricated
rows every 30 minutes would fill the database with data indistinguishable from
real captures, and you would not find out until you traded on it.

With placeholder credentials, verified behaviour:

```
cycles=3  succeeded=0  failed=3  records=0
  #1 FAILED  records=0  error=kite_reauth_required: no valid Kite access token...
  #2 FAILED  records=0  error=kite_reauth_required: no valid Kite access token...
  #3 FAILED  records=0  error=kite_reauth_required: no valid Kite access token...

live_ticks: 0    live_market_data: 0    capture_cycles: 3
```

The cycles are recorded. The market tables stay empty. That is correct.

## What each cycle does

1. Assigns a unique `cycle_id` (UUID) and an incrementing `cycle_number`.
2. Writes a `capture_cycles` row with status `RUNNING` **before** doing any
   work, so a cycle that crashes the process still leaves evidence.
3. Resolves symbols: everything in `watchlist`, plus `OA_SCHEDULER_SYMBOLS`.
4. Fetches quotes, retrying transient faults with exponential backoff.
5. Persists each quote as a `live_ticks` row and a `live_market_data` bar.
6. Writes a `pnl_snapshots` row when positions exist.
7. Updates the cycle row with status, duration, attempts and per-table counts.

Config and auth errors are **not** retried — a missing API key will still be
missing in four seconds, and retrying only delays an honest failure.

## Schedule accuracy

The next run is computed from the cycle's *scheduled* time, not from when the
previous one finished, so a slow cycle does not push the whole schedule later.
Verified at a 4-second test interval:

```
 #  started    status   ticks bars total  ms
 1  13:44:46  SUCCESS     2    2     4  101   (startup)
 2  13:44:50  SUCCESS     2    2     4   78
 3  13:44:54  SUCCESS     2    2     4   51
 4  13:44:58  SUCCESS     2    2     4   27
```

Exactly 4 seconds apart.

## No overwriting, no duplicates

Every cycle **appends**. Historical cycles are never modified.

Deduplication is enforced by database keys, not by application logic:
`live_ticks` on `(symbol, ts)`, `live_market_data` on `unique_key`. Capturing
the same minute twice inserts nothing — and the second cycle honestly reports
`total_records = 0` rather than pretending it wrote something.

## Verifying it ran

### From the UI
**Live Monitor → Scheduled capture** shows state, next run countdown, cycle
counts, and a per-cycle table with insert counts. "Run now" triggers one
immediately.

### From the API
```
GET  /api/scheduler/status     — running, next run, success/failure totals
GET  /api/scheduler/cycles     — per-cycle audit, newest first
POST /api/scheduler/run-now    — trigger a cycle immediately
```

### From the database

```sql
-- Did every 30-minute capture run, and what did each write?
SELECT cycle_number, started_at, status, trigger, attempts,
       symbols_captured || '/' || symbols_requested AS symbols,
       ticks_inserted, bars_inserted, pnl_snapshots_inserted,
       total_records, duration_ms, error
FROM capture_cycles
ORDER BY cycle_number DESC
LIMIT 48;
```

```sql
-- Gaps: any interval far from 30 minutes means a cycle was missed.
SELECT cycle_number, started_at,
       ROUND(EXTRACT(EPOCH FROM (started_at -
             LAG(started_at) OVER (ORDER BY started_at))) / 60, 1) AS minutes_since_previous
FROM capture_cycles ORDER BY cycle_number DESC LIMIT 24;
```

```sql
-- Health summary
SELECT status, COUNT(*) cycles, SUM(total_records) records
FROM capture_cycles GROUP BY status;
```

```sql
-- Why did cycles fail?
SELECT cycle_number, started_at, error FROM capture_cycles
WHERE status = 'FAILED' ORDER BY started_at DESC LIMIT 20;
```

### From the logs
Each cycle logs one line:
```
Capture cycle #7 SUCCESS: 12 records (5/5 symbols)
Capture cycle #8 FAILED: 0 records (0/5 symbols) -- kite_reauth_required: ...
```
Also written to `system_events` under category `scheduler`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OA_SCHEDULER_ENABLED` | `true` | Turn the scheduler off entirely |
| `OA_SCHEDULER_INTERVAL_SECONDS` | `1800` | 30 minutes |
| `OA_SCHEDULER_RUN_ON_STARTUP` | `true` | Capture once at boot, so you learn immediately whether it works |
| `OA_SCHEDULER_MAX_RETRIES` | `3` | Attempts per cycle for transient faults |
| `OA_SCHEDULER_RETRY_BACKOFF` | `2.0` | Base seconds, doubling per attempt |
| `OA_SCHEDULER_SYMBOLS` | *(watchlist + dashboard list)* | Explicit symbol list |

## Note on market hours

Cycles run continuously, including outside NSE hours. Each cycle records a
`market_open` flag rather than being skipped: knowing "cycle ran, market closed,
0 new rows" is more useful than silence. NSE holidays are not accounted for.
