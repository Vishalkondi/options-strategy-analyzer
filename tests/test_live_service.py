import asyncio

import pytest

from server.database import reset_database_for_tests
from server import live_service


RECORD = {
    "timestamp": "2026-09-03T09:15:01",
    "symbol": "reliance",
    "open": 1420,
    "high": 1421,
    "low": 1419,
    "close": 1420.5,
    "volume": 1200,
}


def test_live_record_validation_and_duplicate_prevention(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(live_service, "get_database", lambda: conn)
    service = live_service.LiveIngestionService()

    first = asyncio.run(service.ingest(RECORD))
    duplicate = asyncio.run(service.ingest(RECORD))

    assert first["inserted"] is True
    assert duplicate["inserted"] is False
    assert conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()[0] == 1
    assert first["symbol"] == "RELIANCE"


def test_live_record_rejects_invalid_ohlc(monkeypatch):
    conn = reset_database_for_tests()
    monkeypatch.setattr(live_service, "get_database", lambda: conn)
    service = live_service.LiveIngestionService()

    with pytest.raises(ValueError, match="high/low"):
        asyncio.run(service.ingest({**RECORD, "high": 1400}))
