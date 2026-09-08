"""
Live market snapshot for the dashboard.

The previous implementation returned a sine wave over hard-coded base prices
and shipped it as "live market data" -- the endpoint was up, the numbers were
fabricated, and nothing in the payload said so. That is the worst kind of
"working": a green dashboard that cannot be trusted.

Now: real Kite quotes whenever a valid token exists, and when there isn't one,
the same simulated series but explicitly tagged `source: "simulated"` plus the
reason it fell back, so the UI can show a warning instead of a price.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

from fastapi import WebSocket

from server import kite_client
from server.config import settings

logger = logging.getLogger("live_market")

_SIMULATED_BASE = {
    "RELIANCE": 2838.39, "TCS": 3745.26, "INFY": 1503.58,
    "HDFCBANK": 1748.39, "ICICIBANK": 1384.64,
}


class LiveMarketService:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._task: asyncio.Task[Any] | None = None
        self._symbols = [s.upper() for s in settings.LIVE_MARKET_SYMBOLS] or list(_SIMULATED_BASE)
        self._cache: tuple[float, dict[str, Any]] | None = None

    # -- data sources ------------------------------------------------------

    def _kite_snapshot(self, symbols: list[str]) -> dict[str, Any]:
        keys = [f"NSE:{s}" for s in symbols]
        quotes = kite_client.quote(keys)
        out: dict[str, Any] = {}
        for symbol in symbols:
            payload = quotes.get(f"NSE:{symbol}")
            if not payload:
                continue
            price = float(payload.get("last_price") or 0.0)
            ohlc = payload.get("ohlc") or {}
            previous_close = float(ohlc.get("close") or 0.0)
            change = round(price - previous_close, 2) if previous_close else 0.0
            pct = round((change / previous_close) * 100, 4) if previous_close else 0.0
            out[symbol] = {
                "symbol": symbol,
                "price": round(price, 2),
                "previous_close": round(previous_close, 2),
                "change": change,
                "change_percent": pct,
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "volume": payload.get("volume"),
                "timestamp": str(payload.get("last_trade_time") or payload.get("timestamp") or ""),
                "source": "kite",
            }
        return out

    def _simulated_snapshot(self, symbols: list[str], now: float) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for symbol in symbols:
            base = _SIMULATED_BASE.get(symbol, 100.0)
            wave = math.sin((now + len(symbol) * 13.7) / 8.0)
            price = round(base + (wave * 12.0), 2)
            change = round(price - base, 2)
            out[symbol] = {
                "symbol": symbol,
                "price": price,
                "previous_close": round(base, 2),
                "change": change,
                "change_percent": round((change / base) * 100, 4),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                "source": "simulated",
            }
        return out

    # -- public API --------------------------------------------------------

    def _replay_snapshot(self, symbols: list[str]) -> dict[str, Any]:
        """Prices from an in-progress replay of stored bars. Real recorded
        market data, just not today's -- which is why it is tagged 'replay'
        and never 'kite'."""
        from server.replay import last_prices
        out: dict[str, Any] = {}
        for symbol in symbols:
            entry = last_prices.get(symbol)
            if not entry:
                continue
            price = float(entry["price"])
            previous_close = float(entry.get("open") or price)
            change = round(price - previous_close, 2)
            out[symbol] = {
                "symbol": symbol,
                "price": round(price, 2),
                "previous_close": round(previous_close, 2),
                "change": change,
                "change_percent": round((change / previous_close) * 100, 4) if previous_close else 0.0,
                "open": entry.get("open"), "high": entry.get("high"),
                "low": entry.get("low"), "volume": entry.get("volume"),
                "timestamp": entry.get("timestamp", ""),
                "source": "replay",
            }
        return out

    def snapshot(self, symbol: str | None = None) -> dict[str, Any]:
        now = time.time()
        symbols = [symbol.strip().upper()] if symbol else list(self._symbols)

        if not symbol and self._cache and (now - self._cache[0]) < settings.LIVE_MARKET_CACHE_SECONDS:
            return self._cache[1]

        from server.replay import replay_service
        if replay_service.running:
            replay_symbol = replay_service.symbol
            if replay_symbol and replay_symbol not in symbols:
                symbols = [replay_symbol, *symbols]
            replay_data = self._replay_snapshot(symbols)
            if replay_data:
                payload = {
                    "type": "market_snapshot",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                    "source": "replay",
                    "source_detail": (
                        f"Replaying stored bars for {replay_symbol} "
                        f"({replay_service.bars_sent}/{replay_service.bars_total}). "
                        "Historical data, not a live feed."
                    ),
                    "symbols": replay_data,
                }
                if symbol:
                    return {**replay_data.get(symbols[0], {}), "source": "replay"}
                self._cache = (now, payload)
                return payload

        source = "kite"
        detail: str | None = None
        try:
            data = self._kite_snapshot(symbols)
            if not data:
                raise kite_client.KiteUpstreamError("Zerodha returned no quotes for the watchlist.")
        except (kite_client.KiteConfigError, kite_client.KiteAuthError,
                kite_client.KiteUpstreamError) as exc:
            source = "simulated"
            detail = str(exc)
            logger.debug("Falling back to simulated market data: %s", exc)
            data = self._simulated_snapshot(symbols, now)

        if symbol:
            entry = data.get(symbols[0], {})
            return {**entry, "source": source, "source_detail": detail}

        payload = {
            "type": "market_snapshot",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "source": source,
            "source_detail": detail,
            "symbols": data,
        }
        self._cache = (now, payload)
        return payload

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        await websocket.send_json(await asyncio.to_thread(self.snapshot))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._broadcast_loop())

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _broadcast_loop(self) -> None:
        """Polls only while someone is listening; the old loop ran forever."""
        try:
            while self._clients:
                await asyncio.sleep(settings.LIVE_MARKET_INTERVAL)
                if not self._clients:
                    break
                # snapshot() may do network I/O -- keep it off the event loop.
                payload = await asyncio.to_thread(self.snapshot)
                stale = set()
                for ws in list(self._clients):
                    try:
                        await ws.send_json(payload)
                    except Exception:  # noqa: BLE001
                        stale.add(ws)
                for ws in stale:
                    self._clients.discard(ws)
        except asyncio.CancelledError:
            raise
        finally:
            self._task = None


live_market_service = LiveMarketService()
