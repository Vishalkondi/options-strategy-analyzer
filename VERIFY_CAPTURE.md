# Verifying live capture

Every query below reads DuckDB directly. Stop uvicorn first — DuckDB allows one
writer process at a time.

```bash
python -c "import duckdb; duckdb.connect('data/market_data.duckdb')"   # should not error
```

## Row counts across every capture table

```sql
SELECT 'live_ticks' t, COUNT(*) n FROM live_ticks
UNION ALL SELECT 'live_market_data', COUNT(*) FROM live_market_data
UNION ALL SELECT 'strategy_signals', COUNT(*) FROM strategy_signals
UNION ALL SELECT 'pnl_snapshots',    COUNT(*) FROM pnl_snapshots
UNION ALL SELECT 'system_events',    COUNT(*) FROM system_events
UNION ALL SELECT 'capture_sessions', COUNT(*) FROM capture_sessions
UNION ALL SELECT 'runs',             COUNT(*) FROM runs
UNION ALL SELECT 'trades',           COUNT(*) FROM trades
UNION ALL SELECT 'trade_legs',       COUNT(*) FROM trade_legs
UNION ALL SELECT 'paper_trades',     COUNT(*) FROM paper_trades
ORDER BY 1;
```

## Raw ticks

```sql
SELECT symbol, ts, ltp, volume_traded, open_interest,
       buy_quantity, sell_quantity, bid_price, ask_price, source
FROM live_ticks
ORDER BY ts DESC
LIMIT 20;
```

## Normalized 1-minute bars (with open interest)

```sql
SELECT timestamp, symbol, open, high, low, close, volume,
       open_interest, bar_interval, source
FROM live_market_data
ORDER BY timestamp DESC
LIMIT 20;
```

## Strategy signals — the audit trail of what fired and why

```sql
SELECT signal_ts, symbol, strategy_id, action, side, price, reason, metadata
FROM strategy_signals
ORDER BY signal_ts DESC
LIMIT 20;
```

## Backtest runs

```sql
SELECT run_id, strategy_id, status, num_trades, total_gross_pnl,
       total_costs, total_net_pnl, win_rate, cost_profile, created_at
FROM runs
ORDER BY created_at DESC
LIMIT 20;
```

## Trades and legs

```sql
SELECT trade_id, symbol, strategy_side, entry_date, exit_date,
       gross_pnl, costs, net_pnl, exit_reason
FROM trades ORDER BY entry_date DESC LIMIT 20;

SELECT * FROM trade_legs LIMIT 20;
```

## Live positions (paper)

```sql
SELECT paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price,
       exit_ts, exit_price, exit_reason, net_pnl, status
FROM paper_trades
ORDER BY entry_ts DESC;
```

## P&L history

```sql
SELECT snapshot_ts, scope, strategy_id, realized_pnl, unrealized_pnl,
       total_pnl, open_positions, closed_positions, return_pct
FROM pnl_snapshots
ORDER BY snapshot_ts DESC
LIMIT 50;
```

## System events — errors and connection transitions

```sql
SELECT event_ts, category, severity, event, detail
FROM system_events
WHERE severity IN ('WARNING','ERROR')
ORDER BY event_ts DESC
LIMIT 50;
```

## Capture sessions

```sql
SELECT session_id, symbol, source, status, started_at, stopped_at, bars_captured
FROM capture_sessions
ORDER BY started_at DESC;
```

## Is capture actually advancing right now?

Run twice, thirty seconds apart. If the count does not move while the ticker is
connected, capture is not working.

```sql
SELECT COUNT(*) AS ticks, MAX(ts) AS newest FROM live_ticks;
```

## Proving capture survives the frontend closing

1. Start backend and frontend, connect Kite, confirm ticks are arriving.
2. Note `SELECT COUNT(*) FROM live_ticks;`
3. Close the browser tab entirely.
4. Wait two minutes.
5. Run the count again — it must be higher.

Capture runs on the backend. The frontend is a viewer, not a participant.

## Retention

Only `live_ticks` grows fast enough to need pruning, and nothing is deleted on a
timer. Purge is an explicit call:

```bash
curl -X POST http://127.0.0.1:8000/api/live/ticks/purge \
  -H 'Content-Type: application/json' -d '{"older_than_days": 30}'
```

Bars, signals, trades, positions and P&L snapshots are never purged by this —
they are small and they are the record you actually need later.
