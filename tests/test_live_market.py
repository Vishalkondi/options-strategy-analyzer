from fastapi.testclient import TestClient

from server.main import app


client = TestClient(app)


def test_live_market_snapshot_endpoint_returns_payload():
    response = client.get("/api/live/market")
    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "market_snapshot"
    assert "symbols" in payload
    assert len(payload["symbols"]) >= 1


def test_live_market_websocket_streams_snapshot():
    with client.websocket_connect("/api/ws/market") as websocket:
        payload = websocket.receive_json()
        assert payload["type"] == "market_snapshot"
        assert "symbols" in payload
