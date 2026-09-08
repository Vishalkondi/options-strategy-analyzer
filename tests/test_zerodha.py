"""Unit tests for the Zerodha polling adapter using a fake Kite client."""
from datetime import date, datetime

from server.database import reset_database_for_tests
from server import zerodha


class FakeKite:
    def instruments(self, exchange):
        if exchange == "NSE":
            return [{"tradingsymbol": "TESTCO", "instrument_token": 1}]
        return [
            {"name": "TESTCO", "tradingsymbol": "TESTCO26AUG100CE", "instrument_token": 2,
             "expiry": date(2026, 8, 27), "strike": 100.0, "instrument_type": "CE", "lot_size": 50},
            {"name": "TESTCO", "tradingsymbol": "TESTCO26AUG100PE", "instrument_token": 3,
             "expiry": date(2026, 8, 27), "strike": 100.0, "instrument_type": "PE", "lot_size": 50},
        ]

    def historical_data(self, token, start, end, interval, oi=False):
        if token == 1:
            return [{"date": datetime(2026, 8, 20), "open": 99, "high": 103,
                     "low": 98, "close": 101, "volume": 1000}]
        return [{"date": datetime(2026, 8, 20), "open": 4, "high": 5,
                 "low": 3, "close": 4.5, "volume": 20, "oi": 10}]


def test_sync_writes_equity_and_historical_option_candles(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(zerodha, "_kite_client", lambda: FakeKite())
    result = zerodha.sync_market_data(
        conn, "testco", date_start="2026-08-01", date_end="2026-08-24", expiry="2026-08-27", strikes=[100]
    )

    assert result["equity_rows"] == 1
    assert result["option_rows"] == 2
    assert conn.execute("SELECT COUNT(*) FROM equity_bars WHERE symbol='TESTCO'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM option_bars WHERE underlying='TESTCO'").fetchone()[0] == 2