"""
Single DuckDB database handle. Schema application is idempotent.

Thread safety
-------------
DuckDB connections are not safe to use from several threads at once, and this
process has at least three writers: FastAPI's sync endpoints (each runs on an
anyio worker thread), the KiteTicker callback thread, and the CSV watcher task.

main.py previously tried to solve this with an HTTP middleware holding a
threading.RLock. That does nothing: the middleware runs on the event-loop
thread for every request, and RLock is reentrant *per thread*, so the lock was
always free. Worse, it did not cover the ticker thread at all, which is the one
writing paper_trades from outside the request cycle.

The fix is here instead of in the web layer: every `.execute()` takes a real
lock and runs on its own DuckDB cursor. Cursors are DuckDB's supported way to
use one database from multiple threads, and giving each call its own cursor
means a chained `.fetchall()` can never read another thread's result set.
Call sites are unchanged -- they still just do `conn.execute(...).fetchall()`.
"""
from __future__ import annotations

import logging
import threading

import duckdb

logger = logging.getLogger("database")

from server.config import settings

# Applied on every startup, after schema.sql. Additive and idempotent, so an
# existing database on disk upgrades in place -- no migration step to run, and
# no risk of dropping data that is already there.
_SCHEMA_UPGRADES = (
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'api'",
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS unique_key VARCHAR",
    "CREATE UNIQUE INDEX IF NOT EXISTS live_market_data_unique_key ON live_market_data(unique_key)",

    # live_market_data is the normalized-bar table. Reused rather than replaced;
    # these columns are what live option capture needs and it lacked.
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS open_interest BIGINT",
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS instrument_token BIGINT",
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS bar_interval VARCHAR DEFAULT '1m'",
    "ALTER TABLE live_market_data ADD COLUMN IF NOT EXISTS session_id VARCHAR",

    # live_ticks existed in schema.sql but was never written to or read from --
    # 4 columns (symbol, ts, ltp, volume). Extended to hold what a Kite full-mode
    # tick actually carries, instead of creating a second tick table beside it.
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS instrument_token BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS last_quantity BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS volume_traded BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS average_price DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS day_open DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS day_high DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS day_low DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS day_close DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS open_interest BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS oi_day_high BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS oi_day_low BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS buy_quantity BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS sell_quantity BIGINT",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS bid_price DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS ask_price DOUBLE",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS market_depth VARCHAR",  # JSON blob
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'kite'",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS session_id VARCHAR",
    "ALTER TABLE live_ticks ADD COLUMN IF NOT EXISTS received_at TIMESTAMP",

    # runs lacked the capital/return/drawdown fields the analytics layer reports.
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS initial_capital DOUBLE",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS final_capital DOUBLE",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS return_pct DOUBLE",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS max_drawdown DOUBLE",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS cost_profile VARCHAR DEFAULT 'none'",

    # Read paths for the capture endpoints, all of which filter by time.
    "CREATE INDEX IF NOT EXISTS live_ticks_symbol_ts ON live_ticks(symbol, ts)",
    "CREATE INDEX IF NOT EXISTS strategy_signals_ts ON strategy_signals(signal_ts)",
    "CREATE INDEX IF NOT EXISTS pnl_snapshots_ts ON pnl_snapshots(snapshot_ts)",
    "CREATE INDEX IF NOT EXISTS system_events_ts ON system_events(event_ts)",
)


class ThreadSafeConnection:
    """Serialises access to one DuckDB database across threads."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        self._conn = conn
        self._lock = threading.Lock()

    def execute(self, query: str, parameters=None):
        with self._lock:
            cursor = self._conn.cursor()
            return cursor.execute(query, parameters) if parameters is not None else cursor.execute(query)

    def executemany(self, query: str, parameters=None):
        with self._lock:
            cursor = self._conn.cursor()
            return cursor.executemany(query, parameters)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __getattr__(self, name):
        # Anything not explicitly wrapped (e.g. .sql, .table) falls through.
        return getattr(self._conn, name)


def _apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    schema_sql = (settings.REPO_ROOT / "server" / "schema.sql").read_text()
    conn.execute(schema_sql)
    for statement in _SCHEMA_UPGRADES:
        try:
            conn.execute(statement)
        except Exception as exc:  # noqa: BLE001
            # An upgrade that cannot apply must not stop the backend booting.
            # Every statement here is additive, so skipping one degrades a
            # feature rather than corrupting anything.
            logger.warning("Schema upgrade skipped (%s): %s", statement[:60], exc)


_conn = None
_init_lock = threading.Lock()


def _connect_postgres():
    from server.postgres_backend import PostgresConnection, apply_schema
    conn = PostgresConnection(settings.POSTGRES_DSN, max_size=settings.POSTGRES_POOL_MAX)
    schema_sql = (settings.REPO_ROOT / "server" / "schema.sql").read_text()
    apply_schema(conn, schema_sql, _SCHEMA_UPGRADES)
    logger.info("Using PostgreSQL backend")
    return conn


def get_database():
    """
    The single database handle.

    Returns a DuckDB or PostgreSQL connection depending on OA_DB_BACKEND. Both
    expose the same execute()/fetchall()/fetchone()/fetchdf() interface, so no
    call site in the application knows or cares which one it is talking to.
    """
    global _conn
    if _conn is not None:
        return _conn
    with _init_lock:
        if _conn is not None:
            return _conn
        if settings.DB_BACKEND in ("postgres", "postgresql"):
            _conn = _connect_postgres()
            return _conn
        settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = duckdb.connect(str(settings.DB_PATH))
        _apply_schema(raw)
        _conn = ThreadSafeConnection(raw)
        return _conn


def reset_connection_for_tests() -> None:
    global _conn
    with _init_lock:
        _conn = None


def reset_database_for_tests() -> duckdb.DuckDBPyConnection:
    """Only for local/dev testing: in-memory DB, fresh schema every call."""
    conn = duckdb.connect(":memory:")
    _apply_schema(conn)
    return conn
