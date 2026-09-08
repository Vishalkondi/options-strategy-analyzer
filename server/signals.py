"""Incremental signal generation for live-watched symbol+strategy pairs.

CRITICAL: entry logic is NOT re-implemented here. evaluate_latest_bar()
in strategy_debit_spread.py is the exact same function the backtest loop
uses (via the shared _signal_for_bar helper) -- this module only supplies
it with the live bar history and turns a fired signal into a paper trade
+ a broadcast event.

Known simplification (documented, not hidden): live paper P&L is tracked
on the UNDERLYING's price move, not on the real debit-spread premium,
because that would require a live options-chain tick stream (a second,
much larger Kite subscription surface) which is out of scope for this
pass. The backtest path (server/engine.py) still prices real option legs
from stored option_bars -- only the live path uses this underlying-price
proxy. paper_trades rows are tagged so this is visible in the data, not
just in a comment.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from server.database import get_database
from server import capture as capture_module
from server import ws_relay
from server.strategy_debit_spread import StrategyParams, evaluate_latest_bar

logger = logging.getLogger("signals")


def adopt_open_trade(watch: dict, conn=None) -> None:
    """Point a freshly-built watch at a position that is already OPEN in the
    database.

    The in-memory watch dict is rebuilt every time a watch is registered or a
    replay starts, with open_trade_id=None. Without this, restarting a replay
    looked like "no position open" and opened a second one on the same bar --
    which is how three identical OPEN rows appeared at entry 1487.49.
    The database is the source of truth for what is open, not process memory.
    """
    conn = conn or get_database()
    row = conn.execute(
        """SELECT paper_trade_id, entry_price, side FROM paper_trades
           WHERE watch_symbol = ? AND strategy_id = ? AND status = 'OPEN'
           ORDER BY entry_ts DESC LIMIT 1""",
        [watch["symbol"], watch["strategy_id"]],
    ).fetchone()
    if row:
        watch["open_trade_id"], watch["entry_price"], watch["open_side"] = row[0], row[1], row[2]
        watch["last_signaled_state"] = row[2]
        logger.info("Adopted existing OPEN position %s for %s", row[0], watch["symbol"])


async def _emit(symbol: str, message: dict) -> None:
    """Send an event to both the per-symbol relay channel and the dashboard
    socket. The Live Monitor connects to /api/live/ws, so broadcasting only to
    ws_relay meant signals never reached the screen the user is looking at."""
    await ws_relay.broadcast(symbol, message)
    try:
        from server.live_service import live_service
        await live_service.broadcast_event(message)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Dashboard broadcast failed: %s", exc)


def load_warm_start_bars(symbol: str, lookback_bars: int = 120) -> list[dict]:
    """Pull the most recent historical daily bars from DuckDB so indicators
    are already past their warm-up window before the first live tick
    arrives. (Live bars are 1-minute; seeding with daily bars is a
    reasonable approximation until real intraday history is imported --
    flagged here rather than silently assumed correct.)"""
    conn = get_database()
    try:
        rows = conn.execute(
            """SELECT timestamp AS ts, open, high, low, close, volume
               FROM equity_bars WHERE symbol = ? ORDER BY trading_date DESC LIMIT ?""",
            [symbol, lookback_bars],
        ).fetchall()
        cols = ["ts", "open", "high", "low", "close", "volume"]
        return [dict(zip(cols, r)) for r in reversed(rows)]
    except Exception as e:
        logger.warning("Could not load warm-start bars for %s: %s", symbol, e)
        return []


def _params_from_dict(params: dict) -> StrategyParams:
    known = {k: v for k, v in params.items() if k in StrategyParams.__dataclass_fields__}
    return StrategyParams(**known)


async def on_new_bar(watch: dict, history: list[dict], conn=None, emit_tick: bool = True) -> None:
    """Called once per finished bar for a watched symbol+strategy, with the
    full bar history (oldest -> newest, this bar last) so indicators can be
    recomputed exactly as the backtest does.

    `watch` carries: symbol, strategy_id, strategy_version, params (dict),
    and mutable state (raw_state, last_signaled_state, open_trade_id,
    entry_price) that this function updates in place.

    `conn` is optional and defaults to the process-wide DuckDB connection
    (get_database()) -- accepting it explicitly, same as engine.run_backtest,
    is what lets tests pass an isolated in-memory connection instead.
    """
    symbol = watch["symbol"]
    strategy_id = watch.get("strategy_id", "unknown")
    params = _params_from_dict(watch.get("params", {}))
    bar = history[-1]

    if conn is None:
        conn = get_database()

    # If a paper trade is already open for this watch, check its exit
    # conditions first -- same target/stop thresholds the backtest engine
    # uses, applied to the underlying price move (see module docstring).
    if watch.get("open_trade_id"):
        entry_price = watch["entry_price"]
        side = watch["open_side"]
        move_pct = (bar["close"] - entry_price) / entry_price if side == "bull" else (entry_price - bar["close"]) / entry_price
        exit_reason = None
        if move_pct >= params.take_profit_pct:
            exit_reason = "target"
        elif move_pct <= -params.stop_loss_pct:
            exit_reason = "stop"

        if exit_reason:
            net_pnl = move_pct * entry_price  # per-unit proxy P&L, see module docstring
            conn.execute(
                """UPDATE paper_trades SET exit_ts=?, exit_price=?, exit_reason=?,
                   net_pnl=?, status='CLOSED' WHERE paper_trade_id=?""",
                [bar["ts"], bar["close"], exit_reason, net_pnl, watch["open_trade_id"]],
            )
            await _emit(symbol, {
                "type": "signal", "action": "EXIT", "symbol": symbol, "strategy": strategy_id,
                "trade_id": watch["open_trade_id"], "price": bar["close"],
                "reason": {"exit_reason": exit_reason, "move_pct": round(move_pct, 4)},
                "timestamp": _iso(bar["ts"]),
            })
            # Signals were previously broadcast and lost. Persisting them means
            # the record of what the strategy decided survives a restart, and
            # exists even when no trade results.
            capture_module.capture_service.record_signal(
                symbol, strategy_id, "EXIT",
                strategy_version=watch.get("strategy_version"),
                paper_trade_id=watch["open_trade_id"], side=watch.get("open_side"),
                price=bar["close"], signal_ts=bar["ts"], reason=exit_reason,
                metadata={"move_pct": round(move_pct, 4),
                          "entry_price": watch.get("entry_price")},
                conn=conn,
            )
            watch["open_trade_id"] = None
            watch["entry_price"] = None
            watch["open_side"] = None

    dates = [_iso(b["ts"]) for b in history]
    closes = [b["close"] for b in history]
    highs = [b["high"] for b in history]
    lows = [b["low"] for b in history]

    raw_state, fired = evaluate_latest_bar(
        dates, closes, highs, lows, params,
        watch.get("raw_state"), watch.get("last_signaled_state"),
    )
    watch["raw_state"] = raw_state

    if emit_tick:
        # Replay sets this False: it already published the bar through
        # live_service.ingest(), and two market_tick events per bar would
        # double every count on the dashboard.
        await _emit(symbol, {
            "type": "market_tick", "symbol": symbol, "price": bar["close"],
            "timestamp": _iso(bar["ts"]),
        })

    # Don't open a second position while one is already open for this watch.
    if fired and not watch.get("open_trade_id"):
        # In-memory state can be stale (a restarted replay, a re-registered
        # watch), so re-check the database before writing. This is the last
        # line of defence against duplicate OPEN rows.
        existing = conn.execute(
            """SELECT paper_trade_id, entry_price, side FROM paper_trades
               WHERE watch_symbol = ? AND strategy_id = ? AND status = 'OPEN'
               ORDER BY entry_ts DESC LIMIT 1""",
            [symbol, strategy_id],
        ).fetchone()
        if existing:
            watch["open_trade_id"], watch["entry_price"], watch["open_side"] = existing
            watch["last_signaled_state"] = existing[2]
            return

        watch["last_signaled_state"] = fired
        trade_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO paper_trades
               (paper_trade_id, watch_symbol, strategy_id, side, entry_ts, entry_price, status)
               VALUES (?, ?, ?, ?, ?, ?, 'OPEN')""",
            [trade_id, symbol, strategy_id, fired, bar["ts"], bar["close"]],
        )
        watch["open_trade_id"] = trade_id
        watch["entry_price"] = bar["close"]
        watch["open_side"] = fired
        logger.info("Live signal: %s %s @ %.2f (%s)", fired, symbol, bar["close"], strategy_id)
        await _emit(symbol, {
            "type": "signal", "action": "ENTRY", "symbol": symbol, "strategy": strategy_id,
            "trade_id": trade_id, "price": bar["close"],
            "reason": {"direction": fired, "adx_threshold": params.adx_threshold,
                       "sma_fast": params.sma_fast, "sma_slow": params.sma_slow},
            "timestamp": _iso(bar["ts"]),
        })

        capture_module.capture_service.record_signal(
            symbol, strategy_id, "ENTRY",
            strategy_version=watch.get("strategy_version"),
            paper_trade_id=trade_id, side=fired, price=bar["close"],
            signal_ts=bar["ts"], reason="crossover",
            metadata={"adx_threshold": params.adx_threshold,
                      "sma_fast": params.sma_fast, "sma_slow": params.sma_slow},
            conn=conn,
        )


def _iso(ts) -> str:
    if isinstance(ts, str):
        return ts
    if isinstance(ts, datetime):
        return ts.isoformat()
    return str(ts)
