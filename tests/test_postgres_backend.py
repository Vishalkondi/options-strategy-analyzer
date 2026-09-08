"""
Tests for the PostgreSQL backend's SQL translation.

These run without a PostgreSQL server: they assert on the SQL that would be
sent. The end-to-end behaviour was verified separately against a real
PostgreSQL 16 instance running the whole application.
"""
from __future__ import annotations

import pytest

from server.postgres_backend import translate_sql


def test_placeholders_are_converted():
    assert translate_sql("SELECT * FROM runs WHERE run_id = ?") == \
        "SELECT * FROM runs WHERE run_id = %s"


def test_insert_or_ignore_becomes_do_nothing():
    sql = translate_sql(
        "INSERT OR IGNORE INTO live_ticks (symbol, ts, ltp) VALUES (?, ?, ?)"
    )
    assert sql.startswith("INSERT INTO live_ticks")
    assert "ON CONFLICT DO NOTHING" in sql
    assert "?" not in sql


def test_insert_or_replace_upserts_on_the_primary_key():
    """The conflict target must be the real PK, or the upsert overwrites wrongly."""
    sql = translate_sql(
        """INSERT OR REPLACE INTO equity_bars
           (symbol, trading_date, bar_interval, open, close)
           VALUES (?, ?, ?, ?, ?)"""
    )
    assert "ON CONFLICT (symbol, trading_date, bar_interval) DO UPDATE SET" in sql
    assert "open = EXCLUDED.open" in sql
    assert "close = EXCLUDED.close" in sql
    # Key columns must not appear in the SET clause.
    set_clause = sql.split("DO UPDATE SET")[1]
    assert "symbol = EXCLUDED.symbol" not in set_clause


def test_unknown_table_degrades_to_do_nothing_rather_than_guessing():
    sql = translate_sql("INSERT OR REPLACE INTO mystery_table (a, b) VALUES (?, ?)")
    assert "ON CONFLICT DO NOTHING" in sql
    assert "DO UPDATE" not in sql


def test_duckdb_types_are_mapped():
    sql = translate_sql("CREATE TABLE t (id UBIGINT PRIMARY KEY, price DOUBLE)")
    assert "BIGINT" in sql and "UBIGINT" not in sql
    assert "DOUBLE PRECISION" in sql


def test_double_precision_is_not_doubled():
    sql = translate_sql("CREATE TABLE t (x DOUBLE PRECISION)")
    assert sql.count("PRECISION") == 1


def test_first_and_last_ordered_aggregates_are_rewritten():
    """DuckDB's first()/last() have no PostgreSQL equivalent."""
    first = translate_sql("SELECT first(open ORDER BY timestamp) FROM captured_bars")
    assert "array_agg(open ORDER BY timestamp)" in first
    assert "[1]" in first

    last = translate_sql("SELECT last(close ORDER BY timestamp) FROM captured_bars")
    assert "DESC" in last, "last() must reverse the ordering, not take the first row"


def test_plain_select_is_untouched_apart_from_placeholders():
    original = "SELECT symbol, COUNT(*) FROM trades GROUP BY symbol ORDER BY 1"
    assert translate_sql(original) == original


def test_question_marks_are_converted_after_other_rewrites():
    """Placeholder conversion runs last so nothing can reintroduce a '?'."""
    sql = translate_sql(
        "INSERT OR REPLACE INTO paper_trades (paper_trade_id, net_pnl) VALUES (?, ?)"
    )
    assert "?" not in sql
    assert sql.count("%s") == 2


@pytest.mark.parametrize("table,keys", [
    ("trades", "trade_id"),
    ("runs", "run_id"),
    ("strategy_signals", "signal_id"),
    ("pnl_snapshots", "snapshot_id"),
])
def test_known_tables_use_their_declared_primary_key(table, keys):
    sql = translate_sql(f"INSERT OR REPLACE INTO {table} ({keys}, x) VALUES (?, ?)")
    assert f"ON CONFLICT ({keys})" in sql
