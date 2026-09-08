# Running on PostgreSQL

DuckDB remains the default. PostgreSQL is opt-in via two environment variables.

## Why you would switch

| | DuckDB | PostgreSQL |
|---|---|---|
| Setup | none, one file | install a server |
| Concurrent writers | **one process** | many |
| Query while backend runs | no — file is locked | yes |
| Remote / networked | no | yes |
| Backtest scan speed | **faster** (columnar) | slower |
| BI tools, pgAdmin, DBeaver | awkward | native |

The single-writer lock is the real reason to move. It is why `check_backend.py`
fails while uvicorn is running, and why you cannot point a dashboard at the
database during live capture.

Do not switch just because PostgreSQL sounds more serious. If one backend
process and one user is the whole picture, DuckDB is the better fit and is
measurably faster at the analytical queries the backtester runs.

## Setup

1. Install PostgreSQL, then create the database:

```sql
CREATE DATABASE osa;
```

2. Install the driver:

```bash
pip install "psycopg[binary]" psycopg-pool
```

3. Point the app at it (Windows `cmd`):

```
set OA_DB_BACKEND=postgres
set OA_POSTGRES_DSN=postgresql://postgres:yourpassword@localhost:5432/osa
python -m uvicorn server.main:app --reload --host 127.0.0.1 --port 8000
```

The schema is created automatically on first start — all 19 tables.

## Moving your existing data across

```bash
python migrate_to_postgres.py --dsn postgresql://postgres:pw@localhost:5432/osa
```

Copies every table from `data/market_data.duckdb`. Idempotent, so a re-run
after a partial failure is safe. **Nothing is deleted from DuckDB** — unset
`OA_DB_BACKEND` and you are back on the original file, untouched.

## How the switch works

Every query in this project is raw SQL run as `conn.execute(sql, params)`. That
is the only seam, so the swap happens in one place: `server/postgres_backend.py`
provides a connection object with the same interface and translates the SQL on
the way through.

No call site changed. `engine.py`, `capture.py`, `signals.py` and the rest do
not know which database they are talking to.

Translations applied (only what this project actually uses):

| DuckDB | PostgreSQL |
|---|---|
| `?` | `%s` |
| `INSERT OR REPLACE` | `ON CONFLICT (pk) DO UPDATE SET ...` |
| `INSERT OR IGNORE` | `ON CONFLICT DO NOTHING` |
| `UBIGINT` | `BIGINT` |
| `DOUBLE` | `DOUBLE PRECISION` |
| `first(x ORDER BY y)` | `(array_agg(x ORDER BY y))[1]` |

`INSERT OR REPLACE` needs the target table's primary key to build a conflict
target, so the keys are declared explicitly in `_PRIMARY_KEYS`. An unregistered
table degrades to `DO NOTHING` rather than guessing — a wrong conflict target
would silently overwrite the wrong row.

**If you add a new table, add its primary key to `_PRIMARY_KEYS`.**

## Verifying

```bash
psql -d osa -c "
SELECT 'live_ticks' t, COUNT(*) n FROM live_ticks
UNION ALL SELECT 'live_market_data', COUNT(*) FROM live_market_data
UNION ALL SELECT 'runs', COUNT(*) FROM runs
UNION ALL SELECT 'trades', COUNT(*) FROM trades
UNION ALL SELECT 'strategy_signals', COUNT(*) FROM strategy_signals
UNION ALL SELECT 'pnl_snapshots', COUNT(*) FROM pnl_snapshots
ORDER BY 1;"
```

All the queries in `VERIFY_CAPTURE.md` work unchanged on PostgreSQL.

## Tested

Verified against a live PostgreSQL 16 instance running the whole application:
schema creation, demo import, backtest, metrics, equity curve, CSV export,
replay, and live capture. Row counts confirmed through `psql`, in a separate
process from the app:

```
 capture_sessions |    1     live_ticks       |  240
 equity_bars      |   60     option_bars      | 3360
 live_market_data |  120     paper_trades     |    1
 pnl_snapshots    |    1     runs             |    1
 strategy_signals |    1     system_events    |    4
 trade_legs       |    2     trades           |    1
```

Backtest produced identical results on both backends (1 trade, net 9.20).

## Known limits

- `fetchdf()` materialises through pandas — fine for API page sizes, not for
  exporting millions of ticks.
- Backtests will be slower than DuckDB on wide scans of `equity_bars` and
  `option_bars`. That is the trade you are making for concurrency.
- Connection pool defaults to 10 (`OA_POSTGRES_POOL_MAX`).
