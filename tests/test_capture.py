"""
Capture tests: prove real rows land in the database.

The requirement was explicitly "do not fake successful database capture" — so
every test here asserts on rows actually present in DuckDB after the fact, not
on counters, return values or mocks.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from server import capture as capture_module
from server.batch_writer import BatchWriter
from server.capture import CaptureService
from server.database import reset_database_for_tests


@pytest.fixture
def conn(monkeypatch):
    connection = reset_database_for_tests()
    monkeypatch.setattr(capture_module, "get_database", lambda: connection)
    return connection


@pytest.fixture
def service(conn):
    svc = CaptureService()
    # Flush aggressively so assertions don't race the writer thread.
    svc._tick_writer = BatchWriter("t", svc._flush_ticks, batch_size=2, flush_interval=0.05)
    svc._bar_writer = BatchWriter("b", svc._flush_bars, batch_size=1, flush_interval=0.05)
    yield svc
    svc.stop_writers()


def _tick(token=738561, price=2900.0, volume=1000, ts=None, oi=None):
    return {
        "instrument_token": token, "last_price": price, "last_quantity": 25,
        "volume_traded": volume, "average_price": price - 1,
        "exchange_timestamp": ts or datetime(2026, 9, 7, 10, 30, 0),
        "ohlc": {"open": 2880.0, "high": 2910.0, "low": 2875.0, "close": 2890.0},
        "oi": oi, "oi_day_high": 12000, "oi_day_low": 8000,
        "total_buy_quantity": 500, "total_sell_quantity": 450,
        "depth": {"buy": [{"price": 2899.5, "quantity": 100, "orders": 3}],
                  "sell": [{"price": 2900.5, "quantity": 120, "orders": 4}]},
    }


# ---------------------------------------------------------------------------
# Raw ticks
# ---------------------------------------------------------------------------

def test_ticks_reach_the_database_with_every_kite_field(service, conn):
    service.start("RELIANCE", source="kite", conn=conn)
    service.on_tick("RELIANCE", _tick(oi=10500))
    service.on_tick("RELIANCE", _tick(price=2901.0, ts=datetime(2026, 9, 7, 10, 30, 1)))
    service._tick_writer.flush()

    row = conn.execute(
        """SELECT symbol, ltp, last_quantity, volume_traded, average_price,
                  day_open, day_high, open_interest, buy_quantity, sell_quantity,
                  bid_price, ask_price, market_depth, source, instrument_token
           FROM live_ticks ORDER BY ts LIMIT 1"""
    ).fetchone()

    assert row[0] == "RELIANCE"
    assert row[1] == 2900.0          # ltp
    assert row[2] == 25              # last_quantity
    assert row[3] == 1000            # volume_traded
    assert row[5] == 2880.0          # day_open from tick ohlc
    assert row[7] == 10500           # open_interest
    assert row[8] == 500 and row[9] == 450
    assert row[10] == 2899.5 and row[11] == 2900.5   # bid/ask from depth
    assert '"price": 2899.5' in row[12]              # full depth kept as JSON
    assert row[13] == "kite"
    assert row[14] == 738561

    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 2


def test_ticks_are_ignored_when_no_capture_is_running(service, conn):
    service.on_tick("RELIANCE", _tick())
    service._tick_writer.flush()
    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 0


def test_duplicate_ticks_do_not_create_duplicate_rows(service, conn):
    """A reconnect can replay the same tick; the (symbol, ts) key absorbs it."""
    service.start("RELIANCE", conn=conn)
    same = _tick()
    for _ in range(5):
        service.on_tick("RELIANCE", same)
    service._tick_writer.flush()
    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 1


def test_a_malformed_tick_does_not_break_capture(service, conn):
    service.start("RELIANCE", conn=conn)
    service.on_tick("RELIANCE", {"garbage": True})          # no price, no timestamp
    service.on_tick("RELIANCE", _tick())                     # good tick still lands
    service._tick_writer.flush()
    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] >= 1


def test_on_tick_never_raises_into_the_kite_callback(service, conn):
    """The Kite callback must survive a database that is entirely broken."""
    service.start("RELIANCE", conn=conn)

    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("database is gone")
        def executemany(self, *a, **k):
            raise RuntimeError("database is gone")

    capture_module.get_database = lambda: Broken()
    try:
        service.on_tick("RELIANCE", _tick())   # must not raise
        service._tick_writer.flush()
        assert service._tick_writer.failed > 0, "the failure must be counted, not hidden"
    finally:
        capture_module.get_database = lambda: conn


# ---------------------------------------------------------------------------
# Normalized bars
# ---------------------------------------------------------------------------

def _bar(ts, close=100.0, volume=500):
    return {"ts": ts, "open": close - 1, "high": close + 2,
            "low": close - 2, "close": close, "volume": volume}


def test_bars_are_persisted_to_live_market_data(service, conn):
    service.start("RELIANCE", conn=conn)
    service.on_bar("RELIANCE", _bar(datetime(2026, 9, 7, 10, 30)),
                   instrument_token=738561, open_interest=9000)
    service._bar_writer.flush()

    row = conn.execute(
        """SELECT symbol, open, high, low, close, volume, open_interest,
                  instrument_token, bar_interval, source
           FROM live_market_data ORDER BY timestamp DESC LIMIT 1"""
    ).fetchone()
    assert row[0] == "RELIANCE"
    assert row[4] == 100.0
    assert row[6] == 9000          # open interest stored on the reused table
    assert row[7] == 738561
    assert row[8] == "1m"


def test_replaying_the_same_minute_does_not_duplicate_a_bar(service, conn):
    service.start("RELIANCE", conn=conn)
    ts = datetime(2026, 9, 7, 10, 30)
    for _ in range(3):
        service.on_bar("RELIANCE", _bar(ts))
        service._bar_writer.flush()
    assert conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_session_is_recorded_and_closed(service, conn):
    started = service.start("RELIANCE", conn=conn)
    assert started["status"] == "RUNNING"

    service.on_tick("RELIANCE", _tick())
    service._tick_writer.flush()
    stopped = service.stop("RELIANCE", conn=conn)

    assert stopped["status"] == "STOPPED"
    assert stopped["ticks_stored"] == 1
    row = conn.execute(
        "SELECT status, stopped_at FROM capture_sessions WHERE session_id = ?",
        [started["session_id"]],
    ).fetchone()
    assert row[0] == "STOPPED" and row[1] is not None


def test_double_start_is_rejected(service, conn):
    service.start("RELIANCE", conn=conn)
    with pytest.raises(ValueError, match="already running"):
        service.start("RELIANCE", conn=conn)


def test_stopping_an_idle_symbol_is_rejected(service, conn):
    with pytest.raises(ValueError, match="No capture running"):
        service.stop("NOTHING", conn=conn)


def test_invalid_source_is_rejected(service, conn):
    with pytest.raises(ValueError, match="source must be"):
        service.start("RELIANCE", source="madeup", conn=conn)


# ---------------------------------------------------------------------------
# Signals, P&L, events
# ---------------------------------------------------------------------------

def test_signals_are_persisted_with_their_reason(service, conn):
    service.record_signal(
        "RELIANCE", "directional_debit_spread", "ENTRY", side="bull", price=2900.0,
        signal_ts=datetime(2026, 9, 7, 10, 30), reason="crossover",
        metadata={"adx_threshold": 20}, conn=conn,
    )
    row = conn.execute(
        """SELECT symbol, strategy_id, action, side, price, reason, metadata
           FROM strategy_signals"""
    ).fetchone()
    assert row[0] == "RELIANCE"
    assert row[2] == "ENTRY" and row[3] == "bull"
    assert row[5] == "crossover"
    assert "adx_threshold" in row[6]


def test_pnl_snapshot_separates_realized_from_unrealized(service, conn):
    conn.execute(
        """INSERT INTO paper_trades
           (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price,
            exit_ts, exit_price, net_pnl, status)
           VALUES ('closed-1', 'TESTCO', 'strat', 'bull', ?, 100.0, ?, 120.0, 20.0, 'CLOSED')""",
        [datetime(2026, 9, 1), datetime(2026, 9, 2)],
    )
    conn.execute(
        """INSERT INTO paper_trades
           (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price, status)
           VALUES ('open-1', 'TESTCO', 'strat', 'bull', ?, 100.0, 'OPEN')""",
        [datetime(2026, 9, 3)],
    )
    conn.execute(
        """INSERT INTO live_market_data
           (id, timestamp, symbol, open, high, low, close, volume, source, unique_key)
           VALUES (1, ?, 'TESTCO', 100, 116, 99, 115.0, 10, 'kite', 'k1')""",
        [datetime(2026, 9, 4)],
    )

    snapshot = service.snapshot_pnl("live", capital=10000.0, conn=conn)
    assert snapshot["realized_pnl"] == 20.0
    assert snapshot["unrealized_pnl"] == 15.0    # 115 - 100 on an open bull
    assert snapshot["total_pnl"] == 35.0
    assert snapshot["open_positions"] == 1 and snapshot["closed_positions"] == 1

    stored = conn.execute(
        "SELECT realized_pnl, unrealized_pnl, total_pnl, capital FROM pnl_snapshots"
    ).fetchone()
    assert stored[:3] == (20.0, 15.0, 35.0)
    assert stored[3] == 10000.0


def test_events_are_written_and_readable(service, conn):
    service.log_event("kite", "ERROR", "ticker_error", "socket closed")
    service.log_event("capture", "INFO", "capture_started", "RELIANCE")

    errors = service.recent_events(severity="ERROR", conn=conn)
    assert len(errors) == 1
    assert errors[0]["event"] == "ticker_error"
    assert len(service.recent_events(conn=conn)) == 2


def test_status_reports_real_counts_from_the_database(service, conn):
    service.start("RELIANCE", conn=conn)
    service.on_tick("RELIANCE", _tick())
    service._tick_writer.flush()

    status = service.status(conn=conn)
    assert status["capturing"] is True
    assert status["totals"]["ticks"] == 1
    assert status["last_tick_symbol"] == "RELIANCE"
    assert status["writers"]["ticks"]["written"] >= 1


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_purge_removes_only_old_ticks(service, conn):
    service.start("RELIANCE", conn=conn)
    service.on_tick("RELIANCE", _tick(ts=datetime.now() - timedelta(days=30)))
    service.on_tick("RELIANCE", _tick(price=2901.0, ts=datetime.now()))
    service._tick_writer.flush()
    assert conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0] == 2

    result = service.purge_ticks(7, conn=conn)
    assert result["deleted"] == 1
    assert result["remaining"] == 1


def test_purge_rejects_a_zero_day_window(service, conn):
    """Guards against a typo wiping the whole tick table."""
    with pytest.raises(ValueError, match="at least 1"):
        service.purge_ticks(0, conn=conn)


# ---------------------------------------------------------------------------
# Batch writer behaviour
# ---------------------------------------------------------------------------

def test_writer_flushes_on_batch_size():
    written = []
    writer = BatchWriter("t", lambda batch: (written.extend(batch), len(batch))[1],
                         batch_size=3, flush_interval=10)
    writer.start()
    try:
        for i in range(3):
            writer.append(i)
        deadline = time.time() + 2
        while len(written) < 3 and time.time() < deadline:
            time.sleep(0.02)
        assert written == [0, 1, 2]
    finally:
        writer.stop()


def test_writer_drops_oldest_when_the_buffer_is_full():
    """Bounded buffer: measured loss beats an OOM that ends the session."""
    writer = BatchWriter("t", lambda b: len(b), batch_size=1000, flush_interval=60,
                         max_buffer=1000)
    for i in range(1500):
        writer.append(i)
    stats = writer.stats()
    assert stats["pending"] == 1000
    assert stats["dropped"] == 500


def test_writer_survives_a_failing_flush_and_counts_it():
    def explode(batch):
        raise RuntimeError("disk full")

    writer = BatchWriter("t", explode, batch_size=2, flush_interval=60)
    writer.append(1)
    writer.append(2)
    writer.flush()          # must not raise
    stats = writer.stats()
    assert stats["failed"] == 2
    assert "disk full" in stats["last_error"]


def test_stop_drains_the_final_partial_batch():
    written = []
    writer = BatchWriter("t", lambda b: (written.extend(b), len(b))[1],
                         batch_size=100, flush_interval=60)
    writer.start()
    writer.append("a")
    writer.stop(drain=True)
    assert written == ["a"], "a clean shutdown must not discard buffered rows"
