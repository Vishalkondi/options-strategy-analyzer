"""Paper-trading tests: fills use stored prices and never call a broker."""
from server.database import reset_database_for_tests
from server.paper import close_position, list_positions, open_position


def test_paper_position_opens_and_closes_at_latest_stored_price():
    conn = reset_database_for_tests()
    conn.execute("""INSERT INTO option_bars
        (underlying, timestamp, trading_date, expiry, strike, option_type, bar_interval,
         open, high, low, close, settle, open_interest, chg_in_oi, contracts, lot_size, import_id)
        VALUES ('TESTCO', '2026-08-20 10:00:00', '2026-08-20', '2026-08-27', 100, 'CE',
                '1d', 4, 5, 3, 4, 4, 10, 0, 20, 50, NULL)""")
    position = open_position(conn, "testco", "2026-08-27", 100, "CE", 50)
    assert position["entry_price"] == 4
    assert len(list_positions(conn)) == 1

    conn.execute("UPDATE option_bars SET close=5 WHERE underlying='TESTCO'")
    closed = close_position(conn, position["position_id"])
    assert closed["pnl"] == 50
    assert list_positions(conn) == []