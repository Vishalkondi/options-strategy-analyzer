"""
Backtest engine. Pure Python — no FastAPI/HTTP imports. Directly executable
and testable on its own. All financial logic (strategy, indicators) is
called from here but lives in its own modules.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict
from datetime import date

import duckdb

from server.config import settings
from server import costs as cost_model
from server.strategy_debit_spread import StrategyParams, generate_signals, pick_legs


def _params_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]


def _data_snapshot_id(conn: duckdb.DuckDBPyConnection, symbol: str) -> str:
    row = conn.execute(
        """SELECT string_agg(file_hash, ',' ORDER BY file_hash),
                  COUNT(*) FILTER (WHERE kind='equity'),
                  COUNT(*) FILTER (WHERE kind='options')
           FROM imports WHERE symbol = ?""",
        [symbol],
    ).fetchone()
    basis = f"{row[0]}|{row[1]}|{row[2]}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _load_equity(conn: duckdb.DuckDBPyConnection, symbol: str, start: str | None, end: str | None):
    q = "SELECT trading_date, open, high, low, close FROM equity_bars WHERE symbol = ?"
    args = [symbol]
    if start:
        q += " AND trading_date >= ?"
        args.append(start)
    if end:
        q += " AND trading_date <= ?"
        args.append(end)
    q += " ORDER BY trading_date"
    rows = conn.execute(q, args).fetchall()
    dates = [str(r[0]) for r in rows]
    opens = [r[1] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = [r[4] for r in rows]
    return dates, opens, highs, lows, closes


def _option_price(conn: duckdb.DuckDBPyConnection, underlying: str, trading_date: str,
                   expiry: str, strike: float, option_type: str) -> float | None:
    row = conn.execute(
        """SELECT close FROM option_bars
           WHERE underlying=? AND trading_date=? AND expiry=? AND strike=? AND option_type=?""",
        [underlying, trading_date, expiry, strike, option_type],
    ).fetchone()
    return row[0] if row else None


def _strikes_and_expiries(conn: duckdb.DuckDBPyConnection, underlying: str):
    strikes = [r[0] for r in conn.execute(
        "SELECT DISTINCT strike FROM option_bars WHERE underlying=? ORDER BY strike", [underlying]
    ).fetchall()]
    expiries = [str(r[0]) for r in conn.execute(
        "SELECT DISTINCT expiry FROM option_bars WHERE underlying=? ORDER BY expiry", [underlying]
    ).fetchall()]
    return strikes, expiries


def run_backtest(conn: duckdb.DuckDBPyConnection, strategy_id: str, strategy_version: int,
                  symbol: str, params: StrategyParams,
                  date_start: str | None = None, date_end: str | None = None,
                  cost_profile: str | None = None) -> str:
    t0 = time.time()
    run_id = str(uuid.uuid4())
    # "none" by default: adding costs must never silently change what an older
    # run reported. Callers opt in.
    profile = cost_model.get_profile(cost_profile)

    dates, opens, highs, lows, closes = _load_equity(conn, symbol, date_start, date_end)
    strikes, expiries = _strikes_and_expiries(conn, symbol)

    if not dates or not strikes or not expiries:
        _persist_run(conn, run_id, strategy_id, strategy_version, params, [symbol],
                      date_start, date_end, status="blocked",
                      error_message="No equity or option data available for symbol/date range.",
                      duration_ms=int((time.time() - t0) * 1000))
        return run_id

    signals = generate_signals(dates, closes, highs, lows, params)
    trades = []

    for sig in signals:
        entry_date = sig.trading_date
        try:
            spot = closes[dates.index(entry_date)]
        except ValueError:
            continue

        future_expiries = [e for e in expiries if e >= entry_date]
        if not future_expiries:
            continue
        expiry = future_expiries[0]

        buy_strike, sell_strike, opt_type = pick_legs(sig.direction, spot, strikes, params.otm_offset_strikes)

        buy_entry = _option_price(conn, symbol, entry_date, expiry, buy_strike, opt_type)
        sell_entry = _option_price(conn, symbol, entry_date, expiry, sell_strike, opt_type)
        if buy_entry is None or sell_entry is None:
            continue
        entry_spread_value = buy_entry - sell_entry
        if entry_spread_value <= 0:
            continue  # not a valid debit spread on this data; skip rather than fabricate

        future_dates = [d for d in dates if entry_date < d <= expiry]
        exit_date = None
        exit_spread_value = None
        exit_reason = "expiry"

        for d in future_dates:
            bp = _option_price(conn, symbol, d, expiry, buy_strike, opt_type)
            sp = _option_price(conn, symbol, d, expiry, sell_strike, opt_type)
            if bp is None or sp is None:
                continue
            spread_value = bp - sp
            if spread_value >= entry_spread_value * (1 + params.take_profit_pct):
                exit_date, exit_spread_value, exit_reason = d, spread_value, "target"
                break
            if spread_value <= entry_spread_value * (1 - params.stop_loss_pct):
                exit_date, exit_spread_value, exit_reason = d, spread_value, "stop"
                break

        if exit_date is None:
            # fall back to last available bar in range (expiry or end of demo data)
            last_avail = [d for d in future_dates
                          if _option_price(conn, symbol, d, expiry, buy_strike, opt_type) is not None]
            if not last_avail:
                continue
            exit_date = last_avail[-1]
            bp = _option_price(conn, symbol, exit_date, expiry, buy_strike, opt_type)
            sp = _option_price(conn, symbol, exit_date, expiry, sell_strike, opt_type)
            exit_spread_value = bp - sp
            exit_reason = "expiry" if exit_date == expiry else "end_of_data"

        quantity = params.lot_size * params.lots
        gross_pnl = (exit_spread_value - entry_spread_value) * quantity
        # Costs default to the "none" profile, so runs made before the cost
        # model existed reproduce exactly. Pass cost_profile to apply real ones.
        cost_breakdown = cost_model.round_trip_cost(
            profile, long_entry=buy_entry, long_exit=bp,
            short_entry=sell_entry, short_exit=sp, quantity=quantity,
        )
        costs = cost_breakdown["total"]
        net_pnl = gross_pnl - costs

        trades.append(dict(
            trade_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
            strategy_side="bull_call_debit_spread" if sig.direction == "bull" else "bear_put_debit_spread",
            entry_date=entry_date, exit_date=exit_date,
            lot_size=params.lot_size, lots=params.lots,
            gross_pnl=gross_pnl, costs=costs, net_pnl=net_pnl, exit_reason=exit_reason,
            legs=[
                dict(action="buy", option_type=opt_type, strike=buy_strike, expiry=expiry,
                     entry_price=buy_entry, exit_price=bp),
                dict(action="sell", option_type=opt_type, strike=sell_strike, expiry=expiry,
                     entry_price=sell_entry, exit_price=sp),
            ],
        ))

    for t in trades:
        conn.execute(
            """INSERT INTO trades (trade_id, run_id, symbol, strategy_side, entry_date, exit_date,
               lot_size, lots, gross_pnl, costs, net_pnl, exit_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [t["trade_id"], t["run_id"], t["symbol"], t["strategy_side"], t["entry_date"], t["exit_date"],
             t["lot_size"], t["lots"], t["gross_pnl"], t["costs"], t["net_pnl"], t["exit_reason"]],
        )
        for leg in t["legs"]:
            conn.execute(
                """INSERT INTO trade_legs (leg_id, trade_id, action, option_type, strike, expiry,
                   entry_price, exit_price) VALUES (?,?,?,?,?,?,?,?)""",
                [str(uuid.uuid4()), t["trade_id"], leg["action"], leg["option_type"], leg["strike"],
                 leg["expiry"], leg["entry_price"], leg["exit_price"]],
            )

    total_gross = sum(t["gross_pnl"] for t in trades)
    total_costs = sum(t["costs"] for t in trades)
    total_net = sum(t["net_pnl"] for t in trades)
    wins = sum(1 for t in trades if t["net_pnl"] > 0)
    win_rate = (wins / len(trades)) if trades else None

    _persist_run(conn, run_id, strategy_id, strategy_version, params, [symbol],
                 date_start or (dates[0] if dates else None), date_end or (dates[-1] if dates else None),
                 status="success", duration_ms=int((time.time() - t0) * 1000),
                 total_gross_pnl=total_gross, total_costs=total_costs, total_net_pnl=total_net,
                 num_trades=len(trades), win_rate=win_rate,
                 data_snapshot_id=_data_snapshot_id(conn, symbol))
    return run_id


def _persist_run(conn, run_id, strategy_id, strategy_version, params, symbols, date_start, date_end,
                  status, duration_ms, error_message=None, total_gross_pnl=None, total_costs=None,
                  total_net_pnl=None, num_trades=None, win_rate=None, data_snapshot_id=None):
    params_dict = asdict(params) if not isinstance(params, dict) else params
    conn.execute(
        """INSERT INTO runs (run_id, strategy_id, strategy_version, resolved_params, params_hash,
           selected_stocks, date_start, date_end, data_snapshot_id, git_sha, engine_version, app_version,
           status, error_message, duration_ms, total_gross_pnl, total_costs, total_net_pnl, num_trades, win_rate)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [run_id, strategy_id, strategy_version, json.dumps(params_dict), _params_hash(params_dict),
         json.dumps(symbols), date_start, date_end, data_snapshot_id, None,
         settings.ENGINE_VERSION, settings.APP_VERSION, status, error_message, duration_ms,
         total_gross_pnl, total_costs, total_net_pnl, num_trades, win_rate],
    )
