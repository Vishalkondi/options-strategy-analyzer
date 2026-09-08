"""
Live Data Service: owns the single KiteTicker WebSocket connection to Zerodha,
resamples ticks into 1-minute bars, warm-starts indicators, and hands the full
bar history to signals.py for strategy evaluation on every finished bar.

Fixes over the previous version
-------------------------------
- Bars are stamped with the tick's exchange timestamp, not datetime.now() on
  the server. A slow server or a non-IST clock was silently putting ticks in
  the wrong minute.
- Bar volume is the *delta* of Kite's cumulative day volume. Adding the
  cumulative figure on every tick inflated a bar's volume into the millions.
- Reconnect / error / close callbacks are wired up. Without them a dropped
  socket left `is_running()` reporting True forever.
- start() is idempotent and restores the persisted watchlist, so a restart
  does not silently stop monitoring rows that are still in the watchlist table.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime

try:
    from kiteconnect import KiteTicker
except ImportError:  # pragma: no cover
    KiteTicker = None

from server import capture as capture_module
from server import signals, token_store
from server.config import settings
from server.database import get_database

logger = logging.getLogger("live_data_service")


class BarBuilder:
    """Resamples ticks into 1-minute OHLCV bars, seeded with warm-start
    history so indicators are past their warm-up window immediately."""

    def __init__(self, symbol: str, warm_start_bars: list[dict] | None = None):
        self.symbol = symbol
        self.history: list[dict] = list(warm_start_bars or [])
        self._current: dict | None = None

    def add_tick(self, price: float, volume: int, ts: datetime) -> dict | None:
        """`volume` is the traded quantity *for this tick*, not a running total."""
        minute = ts.replace(second=0, microsecond=0)
        if self._current is None or self._current["ts"] != minute:
            finished = self._current
            self._current = {
                "ts": minute, "open": price, "high": price,
                "low": price, "close": price, "volume": volume,
            }
            if finished is not None:
                self.history.append(finished)
                return finished
            return None
        bar = self._current
        bar["high"] = max(bar["high"], price)
        bar["low"] = min(bar["low"], price)
        bar["close"] = price
        bar["volume"] += volume
        return None


class LiveDataService:
    def __init__(self):
        self._ticker: "KiteTicker | None" = None
        self._watch: dict[int, dict] = {}          # instrument_token -> state (mutated by signals.py)
        self._bar_builders: dict[int, BarBuilder] = {}
        self._cumulative_volume: dict[int, int] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._connected = False
        self.last_error: str | None = None
        self.last_tick_at: datetime | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> bool:
        """
        Start the ticker. Safe to call repeatedly -- the login callback and the
        app startup hook both call it. Returns True if a ticker is live.
        No-ops with a warning when kiteconnect is missing or no token exists.
        """
        self._loop = loop

        if KiteTicker is None:
            self.last_error = "kiteconnect not installed; live ticker disabled"
            logger.warning(self.last_error)
            return False

        if self._ticker is not None and self._connected:
            self._restore_watchlist()
            return True

        token = token_store.get_token(get_database())
        if token is None:
            self.last_error = (
                "No valid Kite token -- live ticker not started. "
                "Complete /api/kite/login-callback first."
            )
            logger.warning(self.last_error)
            return False

        try:
            from server.kite_client import api_key
            self._stop_ticker()
            self._ticker = KiteTicker(api_key(), token)
            self._ticker.on_ticks = self._on_ticks
            self._ticker.on_connect = self._on_connect
            self._ticker.on_close = self._on_close
            self._ticker.on_error = self._on_error
            self._ticker.on_reconnect = self._on_reconnect
            self._ticker.on_noreconnect = self._on_noreconnect
            self._ticker.connect(threaded=True)
            self.last_error = None
            logger.info("Live ticker starting")
            self._restore_watchlist()
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"Failed to start live ticker: {exc}"
            logger.error(self.last_error)
            self._ticker = None
            return False

    def _stop_ticker(self) -> None:
        if self._ticker is not None:
            try:
                self._ticker.close()
            except Exception:  # noqa: BLE001
                pass
        self._ticker = None
        self._connected = False

    def stop(self) -> None:
        self._stop_ticker()

    def is_running(self) -> bool:
        if self._ticker is None:
            return False
        try:
            return bool(self._ticker.is_connected())
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        return {
            "ticker_running": self.is_running(),
            "watched_instruments": len(self._watch),
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_error": self.last_error,
        }

    # -- ticker callbacks --------------------------------------------------

    def _on_connect(self, ws, response):
        self._connected = True
        self.last_error = None
        capture_module.capture_service.log_event("kite", "INFO", "ticker_connected")
        tokens = list(self._watch.keys())
        if tokens:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            logger.info("Subscribed to %d instruments", len(tokens))

    def _on_close(self, ws, code, reason):
        self._connected = False
        logger.warning("Live ticker closed (%s): %s", code, reason)
        capture_module.capture_service.log_event(
            "kite", "WARNING", "ticker_closed", f"code={code} reason={reason}")

    def _on_error(self, ws, code, reason):
        self._connected = False
        self.last_error = f"ticker error {code}: {reason}"
        logger.error(self.last_error)
        capture_module.capture_service.log_event("kite", "ERROR", "ticker_error", self.last_error)

    def _on_reconnect(self, ws, attempts_count):
        logger.warning("Live ticker reconnecting (attempt %s)", attempts_count)
        capture_module.capture_service.log_event(
            "kite", "WARNING", "ticker_reconnecting", f"attempt {attempts_count}")

    def _on_noreconnect(self, ws):
        self._connected = False
        self.last_error = "Live ticker gave up reconnecting -- log in again and restart the watch."
        logger.error(self.last_error)
        capture_module.capture_service.log_event("kite", "ERROR", "ticker_gave_up", self.last_error)

    # -- watches -----------------------------------------------------------

    def watch(self, instrument_token: int, symbol: str, strategy_id: str,
              strategy_version: int, params: dict):
        """Add a symbol+strategy pair and warm-start its indicator state."""
        with self._lock:
            self._watch[instrument_token] = {
                "symbol": symbol, "strategy_id": strategy_id,
                "strategy_version": strategy_version, "params": params,
                "raw_state": None, "last_signaled_state": None,
                "open_trade_id": None, "entry_price": None, "open_side": None,
            }
            signals.adopt_open_trade(self._watch[instrument_token])
            self._bar_builders[instrument_token] = BarBuilder(
                symbol=symbol, warm_start_bars=signals.load_warm_start_bars(symbol),
            )
            self._cumulative_volume.pop(instrument_token, None)

        if settings.CAPTURE_AUTO_START and not capture_module.capture_service.is_capturing(symbol):
            # Watching a symbol without recording it is the gap this closes:
            # the strategy would run and produce nothing durable.
            try:
                capture_module.capture_service.start(symbol, source="kite")
            except ValueError:
                pass

        if self.is_running():
            self._ticker.subscribe([instrument_token])
            self._ticker.set_mode(self._ticker.MODE_FULL, [instrument_token])
            logger.info("Watching %s (%s)", symbol, instrument_token)

    def unwatch(self, instrument_token: int):
        with self._lock:
            watch = self._watch.pop(instrument_token, {})
            self._bar_builders.pop(instrument_token, None)
            self._cumulative_volume.pop(instrument_token, None)
        if self.is_running():
            self._ticker.unsubscribe([instrument_token])
        logger.info("Unwatching %s", watch.get("symbol", "?"))

    def active_watches(self) -> list[dict]:
        with self._lock:
            return [
                {"instrument_token": token, **{k: v for k, v in w.items()
                 if k in ("symbol", "strategy_id", "strategy_version", "open_trade_id")}}
                for token, w in self._watch.items()
            ]

    def _restore_watchlist(self) -> None:
        """Re-subscribe to watchlist rows that survived a restart."""
        try:
            rows = get_database().execute(
                """SELECT instrument_token, symbol, strategy_id, strategy_version, params_json
                   FROM watchlist WHERE instrument_token IS NOT NULL"""
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not restore watchlist: %s", exc)
            return

        for token, symbol, strategy_id, strategy_version, params_json in rows:
            if token in self._watch:
                continue
            try:
                params = json.loads(params_json) if params_json else {}
            except (TypeError, ValueError):
                params = {}
            self.watch(int(token), symbol, strategy_id, int(strategy_version or 1), params)
        if rows:
            logger.info("Restored %d watchlist subscription(s)", len(rows))

    # -- tick handling -----------------------------------------------------

    def _tick_volume(self, token: int, tick: dict) -> int:
        """
        Kite sends `volume_traded` as the cumulative traded quantity for the
        day. A bar wants the increment since the previous tick.
        """
        cumulative = tick.get("volume_traded")
        if cumulative is None:
            return 0
        try:
            cumulative = int(cumulative)
        except (TypeError, ValueError):
            return 0
        previous = self._cumulative_volume.get(token)
        self._cumulative_volume[token] = cumulative
        if previous is None or cumulative < previous:  # first tick, or counter reset
            return 0
        return cumulative - previous

    @staticmethod
    def _tick_timestamp(tick: dict) -> datetime:
        ts = tick.get("exchange_timestamp") or tick.get("last_trade_time")
        if isinstance(ts, datetime):
            return ts.replace(tzinfo=None)
        return datetime.now()

    def _on_ticks(self, ws, ticks):
        # Runs on KiteTicker's own thread, not the asyncio loop --
        # finished bars are handed back to the loop explicitly.
        for tick in ticks:
            token = tick.get("instrument_token")
            builder = self._bar_builders.get(token)
            watch = self._watch.get(token)
            if builder is None or watch is None:
                continue

            price = tick.get("last_price")
            if price is None:
                continue

            self.last_tick_at = datetime.now()

            # Persist the raw tick. Buffered and returns immediately -- the
            # database is never touched on this thread.
            capture_module.capture_service.on_tick(watch["symbol"], tick, source="kite")

            volume = self._tick_volume(token, tick)
            finished_bar = builder.add_tick(float(price), volume, self._tick_timestamp(tick))

            if finished_bar is not None:
                # The normalized bar the strategy is about to see, kept rather
                # than discarded. Same bar, no second bar builder.
                capture_module.capture_service.on_bar(
                    watch["symbol"], finished_bar, source="kite",
                    instrument_token=token, open_interest=tick.get("oi"),
                )

            if finished_bar is not None and self._loop is not None:
                future = asyncio.run_coroutine_threadsafe(
                    signals.on_new_bar(watch, list(builder.history)), self._loop
                )
                future.add_done_callback(self._log_bar_failure)

    @staticmethod
    def _log_bar_failure(future) -> None:
        # Without this, an exception inside on_new_bar vanishes into the
        # Future and the watch just quietly stops producing signals.
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Signal evaluation failed for a finished bar: %s", exc)


live_data_service = LiveDataService()
