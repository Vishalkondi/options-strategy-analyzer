"""
PostgreSQL backend.

Why this exists
---------------
DuckDB is a single embedded file with one writer. That is fine for one backend
process and one user, and it is what makes `check_backend.py` fail while the
server is running. It stops being fine when you want:

  - the backend writing while a BI tool or a second service reads
  - more than one backend process
  - the database on a different machine from the app
  - real concurrent connections instead of a file lock

This module lets the same application run on PostgreSQL by setting two
environment variables. No call site changes.

How it works
------------
Every query in this codebase is raw SQL executed as `conn.execute(sql, params)`
against a connection object. So the swap happens at exactly one seam: provide a
connection object with the same interface, and translate the SQL on the way
through.

`translate_sql()` handles the dialect differences that actually appear in this
project -- nothing speculative:

  ?                   -> %s              (parameter placeholders)
  INSERT OR REPLACE   -> ON CONFLICT DO UPDATE
  INSERT OR IGNORE    -> ON CONFLICT DO NOTHING
  UBIGINT             -> BIGINT
  DOUBLE              -> DOUBLE PRECISION
  current_timestamp   -> CURRENT_TIMESTAMP
  first(x ORDER BY y) -> (array_agg(x ORDER BY y))[1]

`INSERT OR REPLACE` needs the target table's primary key to build the conflict
clause, which is why the schema's keys are declared here rather than inferred.
An unknown table degrades to DO NOTHING, which is safe: a duplicate is skipped
rather than silently overwriting a row with the wrong conflict target.

Honest limits
-------------
- DuckDB stays the default. Postgres is opt-in, because the analytical queries
  the backtester runs are what DuckDB is built for, and Postgres will be slower
  at wide scans over `equity_bars` / `option_bars`.
- `fetchdf()` is implemented via pandas from the cursor, which is fine at the
  row counts the API endpoints return, and is not how you would export millions
  of ticks.
"""
from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger("postgres")

try:
    import psycopg
    from psycopg_pool import ConnectionPool
    PSYCOPG_AVAILABLE = True
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    ConnectionPool = None  # type: ignore[assignment]
    PSYCOPG_AVAILABLE = False


# Primary keys, needed to build ON CONFLICT targets for INSERT OR REPLACE.
# Declared explicitly: guessing a conflict target is how you silently overwrite
# the wrong row.
_PRIMARY_KEYS: dict[str, list[str]] = {
    "equity_bars": ["symbol", "trading_date", "bar_interval"],
    "option_bars": ["underlying", "timestamp", "expiry", "strike", "option_type", "bar_interval"],
    "live_ticks": ["symbol", "ts"],
    "live_market_data": ["id"],
    "captured_bars": ["symbol", "timestamp", "bar_interval"],
    "imports": ["import_id"],
    "strategies": ["strategy_id", "version"],
    "runs": ["run_id"],
    "trades": ["trade_id"],
    "trade_legs": ["leg_id"],
    "watchlist": ["symbol", "strategy_id", "strategy_version"],
    "paper_trades": ["paper_trade_id"],
    "paper_positions": ["position_id"],
    "paper_orders": ["order_id"],
    "kite_sessions": ["id"],
    "capture_sessions": ["session_id"],
    "capture_cycles": ["cycle_id"],
    "strategy_signals": ["signal_id"],
    "pnl_snapshots": ["snapshot_id"],
    "system_events": ["event_id"],
}

_INSERT_TABLE = re.compile(r"INSERT\s+OR\s+(REPLACE|IGNORE)\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_COLUMN_LIST = re.compile(r"\(([^)]*)\)\s*VALUES", re.I | re.S)
_FIRST_LAST = re.compile(r"\b(first|last)\s*\(\s*(.+?)\s+ORDER\s+BY\s+(.+?)\s*\)", re.I | re.S)


def _conflict_clause(action: str, table: str, sql: str) -> str:
    keys = _PRIMARY_KEYS.get(table.lower())
    if action.upper() == "IGNORE" or not keys:
        if action.upper() == "REPLACE" and not keys:
            logger.warning(
                "No primary key registered for %r; INSERT OR REPLACE degraded to "
                "DO NOTHING so an unknown conflict target cannot overwrite the wrong row.",
                table,
            )
        return " ON CONFLICT DO NOTHING"

    match = _COLUMN_LIST.search(sql)
    if not match:
        return " ON CONFLICT DO NOTHING"
    columns = [c.strip() for c in match.group(1).split(",") if c.strip()]
    updates = [c for c in columns if c.lower() not in {k.lower() for k in keys}]
    if not updates:
        return f" ON CONFLICT ({', '.join(keys)}) DO NOTHING"
    setters = ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
    return f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {setters}"


def translate_sql(sql: str) -> str:
    """DuckDB SQL -> PostgreSQL SQL, for the constructs this project uses."""
    match = _INSERT_TABLE.search(sql)
    conflict = ""
    if match:
        action, table = match.group(1), match.group(2)
        conflict = _conflict_clause(action, table, sql)
        sql = _INSERT_TABLE.sub(f"INSERT INTO {table}", sql, count=1)

    sql = _FIRST_LAST.sub(
        lambda m: f"(array_agg({m.group(2)} ORDER BY {m.group(3)}"
                  f"{' DESC' if m.group(1).lower() == 'last' else ''}))[1]",
        sql,
    )

    sql = re.sub(r"\bUBIGINT\b", "BIGINT", sql, flags=re.I)
    sql = re.sub(r"\bDOUBLE\b(?!\s+PRECISION)", "DOUBLE PRECISION", sql, flags=re.I)

    if conflict:
        sql = sql.rstrip().rstrip(";") + conflict

    # Placeholders last, so nothing above can reintroduce a '?'.
    return sql.replace("?", "%s")


class _Result:
    """Materialised result with the DuckDB cursor interface the app expects."""

    def __init__(self, rows: list | None, description=None):
        self._rows = rows or []
        self._description = description

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchdf(self):
        import pandas as pd
        columns = [d[0] for d in self._description] if self._description else None
        return pd.DataFrame(self._rows, columns=columns)


class PostgresConnection:
    """
    Drop-in replacement for the DuckDB connection wrapper.

    Uses a real connection pool, so concurrent requests genuinely run in
    parallel instead of queueing behind one file lock -- which is the whole
    reason for moving off DuckDB.
    """

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10):
        if not PSYCOPG_AVAILABLE:
            raise RuntimeError(
                "PostgreSQL backend requires psycopg. Install it with:\n"
                "    pip install 'psycopg[binary]' psycopg-pool"
            )
        self.dsn = dsn
        self._pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=True)
        self._lock = threading.Lock()
        logger.info("PostgreSQL pool opened (max_size=%d)", max_size)

    def execute(self, query: str, parameters=None):
        sql = translate_sql(query)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(parameters) if parameters else None)
                if cur.description is None:
                    return _Result([], None)
                return _Result(cur.fetchall(), cur.description)

    def executemany(self, query: str, parameters=None):
        sql = translate_sql(query)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, [tuple(p) for p in (parameters or [])])
                return _Result([], None)

    def close(self) -> None:
        self._pool.close()


def apply_schema(conn: PostgresConnection, schema_sql: str, upgrades: tuple[str, ...]) -> None:
    """
    Apply schema.sql to PostgreSQL, statement by statement.

    Split and run individually rather than as one script so a single
    incompatible statement is reported by name instead of aborting everything
    behind it.
    """
    # Strip comments BEFORE splitting. schema.sql contains inline comments that
    # themselves contain semicolons ("-- SHA-256 of file bytes; enforces
    # idempotency"), which would otherwise cut a CREATE TABLE in half.
    stripped = "\n".join(
        line.split("--")[0].rstrip() for line in schema_sql.splitlines()
    )
    statements = [s.strip() for s in stripped.split(";") if s.strip()]
    failures = []
    for statement in statements:
        try:
            conn.execute(statement)
        except Exception as exc:  # noqa: BLE001
            failures.append((statement.split("\n")[0][:70], str(exc).split("\n")[0]))

    for statement in upgrades:
        try:
            conn.execute(statement)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            # "already exists" is the expected outcome of an idempotent upgrade.
            if "already exists" not in msg and "duplicate" not in msg:
                logger.debug("Upgrade skipped: %s (%s)", statement[:60], exc)

    if failures:
        for stmt, err in failures:
            logger.error("Schema statement failed: %s -> %s", stmt, err)
        raise RuntimeError(
            f"{len(failures)} schema statement(s) failed on PostgreSQL. First: "
            f"{failures[0][0]} -> {failures[0][1]}"
        )
