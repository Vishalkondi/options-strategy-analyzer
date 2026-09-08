"""
Market replay: drive the real live pipeline from stored historical bars.

Why this exists
---------------
Live Zerodha data needs a paid Kite Connect key and a login that expires every
morning. That is a bad dependency for a demo, and it is a worse dependency for
testing the live code path. Replay streams bars that are already in DuckDB
through the *same* functions the Kite ticker uses:

    stored bar -> live_service.ingest()  -> persisted + broadcast to /api/live/ws
              -> signals.on_new_bar()    -> strategy evaluation -> paper_trades
                                         -> ENTRY/EXIT broadcast

Nothing here re-implements strategy logic or invents prices. It is the real
pipeline with a different clock and a different source of bars.

Honesty rule: every record replay produces is tagged `source: "replay"`, the
status endpoint says it is running, and the dashboard shows a REPLAY badge. It
must never be possible to mistake this for a live market feed.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import yaml

from server import capture as capture_module
from server import signals
from server.config import settings
from server.database import get_database
from server.live_service import LiveRecord, live_service

logger = logging.getLogger("replay")

# Latest replayed price per symbol, read by live_market so the dashboard shows
# replay prices instead of the simulated fallback while a replay is running.
last_prices: dict[str, dict[str, Any]] = {}


class ReplayService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._run_id: str | None = None
        self.symbol: str | None = None
        self.strategy_file: str | None = None
        self.speed: float = 1.0
        self.bars_total = 0
        self.bars_sent = 0
        self.signals_fired = 0
        self.started_at: datetime | None = None
        self.last_error: str | None = None

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "run_id": self._run_id,
            "symbol": self.symbol,
            "strategy_file": self.strategy_file,
            "speed": self.speed,
            "bars_total": self.bars_total,
            "bars_sent": self.bars_sent,
            "signals_fired": self.signals_fired,
            "progress": round(self.bars_sent / self.bars_total, 4) if self.bars_total else 0.0,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_error": self.last_error,
        }

    # -- data --------------------------------------------------------------

    @staticmethod
    def _load_bars(symbol: str, limit: int) -> list[dict]:
        rows = get_database().execute(
            """SELECT timestamp, open, high, low, close, volume
               FROM equity_bars
               WHERE symbol = ? AND close IS NOT NULL
               ORDER BY trading_date
               LIMIT ?""",
            [symbol, limit],
        ).fetchall()
        bars = []
        for ts, open_, high, low, close, volume in rows:
            # An OHLC bar from a CSV can be internally inconsistent; the live
            # record validator rejects those, so clamp rather than crash mid-demo.
            high = max(high, open_, close)
            low = min(low, open_, close)
            bars.append({
                "ts": ts, "open": float(open_), "high": float(high),
                "low": float(low), "close": float(close), "volume": int(volume or 0),
            })
        return bars

    def _resolve_params(self, strategy_file: str) -> tuple[dict, str, int]:
        spec_path = settings.STRATEGY_DIR / strategy_file
        if not spec_path.exists():
            raise ValueError(f"Strategy file not found: {strategy_file}")
        spec = yaml.safe_load(spec_path.read_text())
        defaults = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}
        return defaults, spec_path.stem, int(spec.get("version", 1))

    # -- lifecycle ---------------------------------------------------------

    async def start(self, symbol: str, strategy_file: str, speed: float = 60.0,
                    bar_limit: int = 500) -> dict[str, Any]:
        if self.running:
            raise ValueError(
                f"A replay is already running for {self.symbol}. Stop it first."
            )

        symbol = (symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if speed <= 0:
            raise ValueError("speed must be greater than zero")

        params, strategy_id, strategy_version = self._resolve_params(strategy_file)
        bars = self._load_bars(symbol, bar_limit)
        if not bars:
            raise ValueError(
                f"No stored bars for {symbol}. Import data first "
                "(POST /api/import with {\"path\": \"demo\"})."
            )

        self._run_id = str(uuid.uuid4())
        self.symbol = symbol
        self.strategy_file = strategy_file
        self.speed = speed
        self.bars_total = len(bars)
        self.bars_sent = 0
        self.signals_fired = 0
        self.started_at = datetime.now()
        self.last_error = None

        watch = {
            "symbol": symbol, "strategy_id": strategy_id,
            "strategy_version": strategy_version, "params": params,
            "raw_state": None, "last_signaled_state": None,
            "open_trade_id": None, "entry_price": None, "open_side": None,
        }

        # A previous replay may have left a position open; adopt it instead of
        # opening a duplicate on the same bar.
        signals.adopt_open_trade(watch)

        # Without an open capture session, capture.on_bar() has nowhere to file
        # the bar and drops it. Open one tagged 'replay' so the rows are real
        # but can never be mistaken for a live Kite recording.
        try:
            if capture_module.capture_service.is_capturing(symbol):
                capture_module.capture_service.stop(symbol)
            capture_module.capture_service.start(symbol, source="replay")
        except Exception as exc:  # noqa: BLE001 -- capture must not block a replay
            logger.warning("Could not start capture for replay: %s", exc)

        self._task = asyncio.create_task(self._run(bars, watch))
        logger.info("Replay started for %s (%d bars at %sx)", symbol, len(bars), speed)
        return self.status()

    async def stop(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        if self.symbol:
            try:
                capture_module.capture_service.stop(self.symbol)
            except Exception:  # noqa: BLE001
                pass
        last_prices.pop(self.symbol or "", None)
        logger.info("Replay stopped")
        return self.status()

    async def _run(self, bars: list[dict], watch: dict) -> None:
        # One real second of wall clock per bar, divided by the speed factor.
        interval = 1.0 / self.speed
        source = f"replay-{(self._run_id or '')[:8]}"
        history: list[dict] = []

        try:
            for bar in bars:
                history.append(bar)

                record = LiveRecord(
                    timestamp=bar["ts"].isoformat() if hasattr(bar["ts"], "isoformat") else str(bar["ts"]),
                    symbol=self.symbol or "",
                    open=bar["open"], high=bar["high"], low=bar["low"],
                    close=bar["close"], volume=bar["volume"],
                )
                # Persists the bar and pushes it to every /api/live/ws client.
                await live_service.ingest(record, source=source)

                last_prices[self.symbol or ""] = {
                    "price": bar["close"],
                    "open": bar["open"], "high": bar["high"], "low": bar["low"],
                    "volume": bar["volume"],
                    "timestamp": record.timestamp,
                }

                capture_module.capture_service.on_bar(
                    self.symbol or "", bar, source="replay")

                # A bar is not a tick, so replay synthesises the four prices a
                # bar actually records -- open, high, low, close -- rather than
                # inventing intra-bar movement that never happened. Every row is
                # tagged source='replay'; nothing here claims to be a Kite tick.
                bar_ts = bar["ts"]
                for offset, price in enumerate(
                    (bar["open"], bar["high"], bar["low"], bar["close"])
                ):
                    capture_module.capture_service.on_tick(
                        self.symbol or "",
                        {
                            "last_price": float(price),
                            "volume_traded": int(bar.get("volume") or 0),
                            "exchange_timestamp": bar_ts + timedelta(seconds=offset * 10)
                            if hasattr(bar_ts, "isoformat") else bar_ts,
                            "ohlc": {"open": bar["open"], "high": bar["high"],
                                     "low": bar["low"], "close": bar["close"]},
                        },
                        source="replay",
                    )

                before = watch.get("open_trade_id")
                # The exact function the Kite ticker calls on a finished bar.
                await signals.on_new_bar(watch, list(history), emit_tick=False)
                if watch.get("open_trade_id") and watch["open_trade_id"] != before:
                    self.signals_fired += 1

                self.bars_sent += 1
                await asyncio.sleep(interval)

            logger.info("Replay finished: %d bars, %d entries", self.bars_sent, self.signals_fired)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            logger.exception("Replay failed: %s", exc)
        finally:
            last_prices.pop(self.symbol or "", None)


replay_service = ReplayService()
