"""Unified live-market ingestion, persistence, deduplication, and broadcast."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator, model_validator

from server.database import get_database
from server import ws_relay

logger = logging.getLogger("live_service")


class LiveRecord(BaseModel):
    timestamp: str
    symbol: str = Field(min_length=1, max_length=32)
    open: float = Field(ge=0)
    high: float = Field(ge=0)
    low: float = Field(ge=0)
    close: float = Field(ge=0)
    volume: int = Field(ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol is required")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("timestamp is required")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601") from exc
        return value

    @model_validator(mode="after")
    def validate_ohlc(self) -> "LiveRecord":
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("high/low values do not contain open and close")
        return self


class LiveIngestionService:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self.last_received_timestamp: str | None = None
        self.last_symbol: str | None = None
        self.total_received = 0
        self.total_inserted = 0
        self.total_duplicates = 0
        self.total_invalid = 0

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            self._clients.discard(websocket)
        except Exception:
            self._clients.discard(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def ingest(self, payload: LiveRecord | dict[str, Any], source: str = "api") -> dict[str, Any]:
        self.total_received += 1
        try:
            record = payload if isinstance(payload, LiveRecord) else LiveRecord.model_validate(payload)
        except Exception:
            self.total_invalid += 1
            raise

        unique_key = self._unique_key(record, source)
        conn = get_database()
        row_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM live_market_data").fetchone()[0]
        inserted = conn.execute(
            """INSERT INTO live_market_data
               (id, timestamp, symbol, open, high, low, close, volume, source, unique_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (unique_key) DO NOTHING
               RETURNING id""",
            [row_id, record.timestamp, record.symbol, record.open, record.high,
             record.low, record.close, record.volume, source, unique_key],
        ).fetchone()

        response = record.model_dump()
        response["source"] = source
        response["unique_key"] = unique_key
        response["inserted"] = inserted is not None
        if inserted is None:
            self.total_duplicates += 1
            return response

        self.total_inserted += 1
        self.last_received_timestamp = record.timestamp
        self.last_symbol = record.symbol
        await self._broadcast(response)
        return response

    async def broadcast_event(self, message: dict[str, Any]) -> None:
        """Push an arbitrary event to every /api/live/ws client.

        signals.py uses this so ENTRY/EXIT events reach the dashboard socket,
        not just the per-symbol relay channel. Previously a signal fired and
        the Live Monitor showed nothing until the next poll."""
        dead: list[WebSocket] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self._clients.discard(websocket)

    async def _broadcast(self, record: dict[str, Any]) -> None:
        message = {"type": "market_tick", **record, "price": record["close"]}
        await self.broadcast_event(message)
        await ws_relay.broadcast(record["symbol"], message)

    @staticmethod
    def _unique_key(record: LiveRecord, source: str) -> str:
        raw = "|".join([
            source, record.timestamp, record.symbol, str(record.open), str(record.high),
            str(record.low), str(record.close), str(record.volume),
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def status(self) -> dict[str, Any]:
        conn = get_database()
        row = conn.execute("SELECT COUNT(*) FROM live_market_data").fetchone()
        return {
            "connected": bool(self._clients),
            "websocket_clients": len(self._clients),
            "database": "connected",
            "last_received_timestamp": self.last_received_timestamp,
            "last_symbol": self.last_symbol,
            "total_records": row[0] if row else 0,
            "received": self.total_received,
            "inserted": self.total_inserted,
            "duplicates_skipped": self.total_duplicates,
            "invalid": self.total_invalid,
        }


live_service = LiveIngestionService()
