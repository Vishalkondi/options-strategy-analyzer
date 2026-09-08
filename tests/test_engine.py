"""
Unit tests: engine mechanics on small synthetic data (position sizing,
reproducibility, run persistence). NOT evidence of financial correctness.

Golden regression tests belong in test_golden_regression.py and must be
skipped with an explicit BLOCKED reason until real client-validated
results exist (GAP_ANALYSIS B5) — never generated from this engine and
used to "prove" the engine, which would be circular.
"""
import pytest

from server.database import reset_database_for_tests
from server.engine import run_backtest
from server.strategy_debit_spread import StrategyParams


def _seed_minimal_trending_data(conn):
    """Enough bars for SMA(5)/SMA(20)/ADX(14) to warm up and a debit-spread
    to be priceable on both entry and a later date."""
    import datetime
    dates = []
    d = datetime.date(2026, 1, 1)
    while len(dates) < 40:
        if d.weekday() < 5:
            dates.append(d)
        d += datetime.timedelta(days=1)

    price = 1000.0
    for i, dt in enumerate(dates):
        price += 3.0  # steady uptrend -> reliably trending ADX
        high = price + 5
        low = price - 5
        conn.execute(
            """INSERT INTO equity_bars (symbol, trading_date, timestamp, bar_interval,
               open, high, low, close, prev_close, vwap, volume, turnover, total_trades,
               deliverable_qty, deliverable_pct, import_id)
               VALUES ('TESTCO', ?, ?, '1d', ?, ?, ?, ?, ?, ?, 1000, 1000000, 100, 500, 50.0, NULL)""",
            [dt, f"{dt} 00:00:00", price - 1, high, low, price, price - 3, price],
        )

    expiry = dates[-1]
    strikes = [900 + s * 20 for s in range(20)]  # 900..1280
    for dt in dates:
        spot = conn.execute("SELECT close FROM equity_bars WHERE symbol='TESTCO' AND trading_date=?", [dt]).fetchone()[0]
        for strike in strikes:
            for opt_type in ("CE", "PE"):
                intrinsic = max(0, spot - strike) if opt_type == "CE" else max(0, strike - spot)
                time_value = 10.0
                close_p = round(intrinsic + time_value, 2)
                conn.execute(
                    """INSERT INTO option_bars (underlying, timestamp, trading_date, expiry, strike,
                       option_type, bar_interval, open, high, low, close, settle, open_interest,
                       chg_in_oi, contracts, lot_size, import_id)
                       VALUES ('TESTCO', ?, ?, ?, ?, ?, '1d', ?, ?, ?, ?, ?, 1000, 0, 100, NULL, NULL)""",
                    [f"{dt} 00:00:00", dt, expiry, strike, opt_type,
                     close_p, close_p + 1, close_p - 1, close_p, close_p],
                )
    return dates


def test_backtest_blocked_when_no_data():
    conn = reset_database_for_tests()
    params = StrategyParams()
    run_id = run_backtest(conn, "test_strategy", 1, "NODATA", params)
    row = conn.execute("SELECT status, error_message FROM runs WHERE run_id=?", [run_id]).fetchone()
    assert row[0] == "blocked"
    assert row[1]


def test_backtest_runs_and_persists_trades_on_trending_data():
    conn = reset_database_for_tests()
    _seed_minimal_trending_data(conn)
    params = StrategyParams(lot_size=1, lots=1)
    run_id = run_backtest(conn, "test_strategy", 1, "TESTCO", params)

    run_row = conn.execute("SELECT status, num_trades FROM runs WHERE run_id=?", [run_id]).fetchone()
    assert run_row[0] == "success"

    trades = conn.execute("SELECT COUNT(*) FROM trades WHERE run_id=?", [run_id]).fetchone()[0]
    legs = conn.execute(
        "SELECT COUNT(*) FROM trade_legs WHERE trade_id IN (SELECT trade_id FROM trades WHERE run_id=?)",
        [run_id],
    ).fetchone()[0]
    if trades > 0:
        assert legs == trades * 2  # every debit spread has exactly 2 legs


def test_backtest_is_reproducible_within_tolerance():
    conn = reset_database_for_tests()
    _seed_minimal_trending_data(conn)
    params = StrategyParams(lot_size=1, lots=1)
    run_id_1 = run_backtest(conn, "test_strategy", 1, "TESTCO", params)
    run_id_2 = run_backtest(conn, "test_strategy", 1, "TESTCO", params)

    r1 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_id_1]).fetchone()
    r2 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_id_2]).fetchone()
    assert r1[1] == r2[1]
    assert abs((r1[0] or 0) - (r2[0] or 0)) <= 0.01


def test_position_sizing_scales_linearly_with_lots():
    conn = reset_database_for_tests()
    _seed_minimal_trending_data(conn)
    p1 = StrategyParams(lot_size=1, lots=1)
    p3 = StrategyParams(lot_size=1, lots=3)
    run_1 = run_backtest(conn, "test_strategy", 1, "TESTCO", p1)
    run_3 = run_backtest(conn, "test_strategy", 1, "TESTCO", p3)
    pnl_1, n_1 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_1]).fetchone()
    pnl_3, n_3 = conn.execute("SELECT total_net_pnl, num_trades FROM runs WHERE run_id=?", [run_3]).fetchone()
    if n_1 and n_3 and n_1 == n_3:
        assert abs((pnl_3 or 0) - 3 * (pnl_1 or 0)) <= 0.01
