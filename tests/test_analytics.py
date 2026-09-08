"""
Tests for the analytics layer: transaction costs, performance metrics,
equity curve, CSV export and parameter sweep.

The most important test here is the first one: adding a cost model must not
change what any existing backtest reports. Costs are opt-in, so the golden
regression fixture and every historical run stay reproducible.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from server import costs, metrics
from server.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

def test_default_profile_is_free_so_old_runs_reproduce():
    profile = costs.get_profile(None)
    assert profile.name == "none"
    breakdown = costs.round_trip_cost(profile, 20.0, 25.0, 7.0, 3.0, quantity=50)
    assert breakdown["total"] == 0.0


def test_unknown_profile_is_rejected_by_name():
    with pytest.raises(ValueError, match="Unknown cost profile"):
        costs.get_profile("my_broker")


def test_stt_is_charged_on_the_sell_side_only():
    profile = costs.DISCOUNT_BROKER
    sell = costs.leg_cost(profile, premium=100.0, quantity=100, is_sell=True)
    buy = costs.leg_cost(profile, premium=100.0, quantity=100, is_sell=False)
    # 10,000 turnover x 0.15% STT = 15.00, which the sell side pays and the buy side does not.
    assert sell - buy == pytest.approx(15.0 - (10000 * profile.stamp_duty_buy), abs=0.01)
    assert sell > buy


def test_gst_excludes_stt_and_stamp_duty():
    """GST applies to brokerage + exchange + SEBI. Taxing a tax would be wrong."""
    profile = costs.DISCOUNT_BROKER
    turnover = 10000.0
    cost = costs.leg_cost(profile, premium=100.0, quantity=100, is_sell=True)

    brokerage = profile.brokerage_per_order
    exchange = turnover * profile.exchange_txn
    sebi = turnover * profile.sebi_charges
    stt = turnover * profile.stt_sell
    gst = (brokerage + exchange + sebi) * profile.gst
    assert cost == pytest.approx(brokerage + exchange + sebi + stt + gst, abs=0.01)


def test_round_trip_charges_four_executions():
    profile = costs.DISCOUNT_BROKER
    breakdown = costs.round_trip_cost(profile, 20.0, 25.0, 7.0, 3.0, quantity=50)
    # Four orders at flat brokerage, so the floor is 4 x 20 before any percentages.
    assert breakdown["total"] > 4 * profile.brokerage_per_order
    assert breakdown["entry"] > 0 and breakdown["exit"] > 0
    assert breakdown["total"] == pytest.approx(breakdown["entry"] + breakdown["exit"], abs=0.01)


def test_full_service_costs_more_than_discount():
    args = (20.0, 25.0, 7.0, 3.0)
    discount = costs.round_trip_cost(costs.DISCOUNT_BROKER, *args, quantity=50)["total"]
    full = costs.round_trip_cost(costs.FULL_SERVICE, *args, quantity=50)["total"]
    assert full > discount


def test_describe_spells_out_every_rate():
    described = costs.describe(costs.DISCOUNT_BROKER)
    labels = {c["label"] for c in described["components"]}
    assert {"Brokerage", "STT (sell side)", "GST"} <= labels
    assert "verify" in described and described["verify"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _trade(pnl, entry="2026-05-01", exit_="2026-05-05", tid=None):
    return {
        "trade_id": tid or f"t{pnl}{exit_}", "net_pnl": pnl, "gross_pnl": pnl,
        "costs": 0.0, "entry_date": entry, "exit_date": exit_,
    }


def test_metrics_on_no_trades_does_not_crash():
    result = metrics.compute([])
    assert result["num_trades"] == 0
    assert result["reliable"] is False


def test_equity_curve_starts_at_origin_and_accumulates():
    trades = [_trade(100, exit_="2026-05-01"), _trade(-40, exit_="2026-05-02"),
              _trade(60, exit_="2026-05-03")]
    points = metrics.equity_curve(trades)
    assert [p["equity"] for p in points] == [0.0, 100.0, 60.0, 120.0]
    assert points[0]["index"] == 0


def test_max_drawdown_measures_peak_to_trough():
    trades = [_trade(100, exit_="2026-05-01"), _trade(-70, exit_="2026-05-02"),
              _trade(20, exit_="2026-05-03")]
    result = metrics.compute(trades)
    # Peak 100, trough 30 -> drawdown of 70.
    assert result["max_drawdown"] == -70.0
    assert result["max_drawdown_pct"] == -70.0


def test_profit_factor_and_expectancy():
    trades = [_trade(100, exit_="2026-05-01"), _trade(100, exit_="2026-05-02"),
              _trade(-50, exit_="2026-05-03"), _trade(-50, exit_="2026-05-04")]
    result = metrics.compute(trades)
    assert result["profit_factor"] == pytest.approx(2.0)
    assert result["win_rate"] == 0.5
    assert result["avg_win"] == 100.0
    assert result["avg_loss"] == 50.0
    assert result["expectancy"] == pytest.approx(25.0)


def test_profit_factor_is_none_when_there_are_no_losses():
    """Dividing by zero loss would report infinity, which is not informative."""
    result = metrics.compute([_trade(10, exit_="2026-05-01"), _trade(20, exit_="2026-05-02")])
    assert result["profit_factor"] is None


def test_streaks_are_counted():
    trades = [_trade(10, exit_=f"2026-05-0{i}") for i in range(1, 4)]
    trades += [_trade(-5, exit_=f"2026-05-0{i}") for i in range(4, 6)]
    result = metrics.compute(trades)
    assert result["longest_win_streak"] == 3
    assert result["longest_loss_streak"] == 2


def test_small_samples_are_flagged_as_unreliable():
    """A Sharpe ratio computed off two trades is noise, and must say so."""
    result = metrics.compute([_trade(100, exit_="2026-05-01"), _trade(50, exit_="2026-05-02")])
    assert result["reliable"] is False
    assert "not meaningful" in result["note"]

    many = [_trade(10 if i % 2 else -5, exit_=f"2026-05-{i:02d}") for i in range(1, 11)]
    assert metrics.compute(many)["reliable"] is True


def test_ratios_are_none_when_variance_is_zero():
    identical = [_trade(10, exit_=f"2026-05-{i:02d}") for i in range(1, 7)]
    result = metrics.compute(identical)
    assert result["sharpe"] is None      # zero stdev, not a divide-by-zero crash
    assert result["sortino"] is None     # no losing trades


def test_metrics_handles_date_objects_not_just_strings():
    trades = [{
        "trade_id": "a", "net_pnl": 50.0, "gross_pnl": 50.0, "costs": 0.0,
        "entry_date": date(2026, 5, 1), "exit_date": date(2026, 5, 8),
    }]
    result = metrics.compute(trades)
    assert result["avg_holding_days"] == 7.0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _create_run(**extra):
    payload = {"strategy_file": "directional_debit_spread.yaml", "symbol": "DEMOSTK", **extra}
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def test_cost_profiles_endpoint_lists_every_profile():
    body = client.get("/api/cost-profiles").json()
    names = {p["name"] for p in body}
    assert {"none", "discount_broker", "full_service"} <= names


def test_run_accepts_a_cost_profile_and_deducts_costs():
    free_run = _create_run()
    costed_run = _create_run(cost_profile="discount_broker")

    free = client.get(f"/api/runs/{free_run}/metrics").json()
    costed = client.get(f"/api/runs/{costed_run}/metrics").json()

    assert free["total_costs"] == 0.0
    if costed["num_trades"] > 0:
        assert costed["total_costs"] > 0.0
        assert costed["total_net_pnl"] < costed["total_gross_pnl"]


def test_unknown_cost_profile_returns_400():
    response = client.post("/api/runs", json={
        "strategy_file": "directional_debit_spread.yaml",
        "symbol": "DEMOSTK", "cost_profile": "nonsense",
    })
    assert response.status_code == 400


def test_metrics_and_equity_endpoints():
    run_id = _create_run()
    m = client.get(f"/api/runs/{run_id}/metrics")
    assert m.status_code == 200
    assert "max_drawdown" in m.json()

    e = client.get(f"/api/runs/{run_id}/equity")
    assert e.status_code == 200
    assert e.json()["points"][0]["index"] == 0


def test_metrics_for_an_unknown_run_is_404():
    assert client.get("/api/runs/no-such-run/metrics").status_code == 404
    assert client.get("/api/runs/no-such-run/equity").status_code == 404
    assert client.get("/api/runs/no-such-run/export.csv").status_code == 404


def test_csv_export_downloads_with_a_header_row():
    run_id = _create_run()
    response = client.get(f"/api/runs/{run_id}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.splitlines()[0].startswith("trade_id,symbol")


def test_sweep_runs_every_value_and_names_the_best():
    response = client.post("/api/runs/sweep", json={
        "strategy_file": "directional_debit_spread.yaml",
        "symbol": "DEMOSTK", "parameter": "adx_threshold",
        "values": [5, 10, 15, 20],
    })
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 4
    assert body["parameter"] == "adx_threshold"
    assert body["caveat"], "a sweep must warn about curve fitting"


def test_sweep_rejects_an_unknown_parameter():
    response = client.post("/api/runs/sweep", json={
        "strategy_file": "directional_debit_spread.yaml",
        "symbol": "DEMOSTK", "parameter": "not_a_param", "values": [1, 2],
    })
    assert response.status_code == 400
    assert "Unknown parameter" in response.json()["detail"]


def test_sweep_rejects_empty_and_oversized_value_lists():
    base = {"strategy_file": "directional_debit_spread.yaml", "symbol": "DEMOSTK",
            "parameter": "adx_threshold"}
    assert client.post("/api/runs/sweep", json={**base, "values": []}).status_code == 400
    assert client.post("/api/runs/sweep",
                       json={**base, "values": list(range(30))}).status_code == 400
