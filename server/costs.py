"""
Transaction cost model for Indian equity options (NSE F&O).

This closes GAP_ANALYSIS B8, where every backtest reported costs = 0.0 and
net P&L was therefore identical to gross P&L.

Design decisions
----------------
1. Rates are DATA, not code. They are constants you can override per run, not
   values buried in a formula, because they change with every Union Budget and
   broker pricing update. Options STT went from 0.10% to 0.15% on 1 April 2026.
2. Default profile is "none" (zero costs), so every existing backtest and the
   golden regression fixture keep producing identical numbers. Costs are
   opt-in per run. Silently changing historical results would be worse than
   reporting zero.
3. Nothing here is authoritative. Verify the rates against your own broker's
   contract notes before you quote a net return to anyone. The defaults below
   reflect Zerodha's published F&O charges and the post-Budget-2026 statutory
   rates, but a broker's actual billing is the only source of truth.

Cost components on an option leg (per Zerodha's published schedule):
  brokerage      flat per executed order
  STT            sell side only, on premium turnover
  exchange       on premium turnover
  SEBI           on premium turnover
  stamp duty     buy side only, on premium turnover
  GST            on (brokerage + exchange + SEBI); NOT on STT or stamp duty
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class CostProfile:
    """All rates as decimal fractions of premium turnover unless stated."""

    name: str
    brokerage_per_order: float = 0.0      # flat rupees per executed order
    stt_sell: float = 0.0                 # sell side only, on premium
    exchange_txn: float = 0.0             # both sides, on premium
    sebi_charges: float = 0.0             # both sides, on premium
    stamp_duty_buy: float = 0.0           # buy side only, on premium
    gst: float = 0.0                      # on brokerage + exchange + sebi

    def to_dict(self) -> dict:
        return asdict(self)


# No costs. The default, so existing runs are bit-for-bit reproducible.
NONE = CostProfile(name="none")

# Discount-broker profile: Zerodha's published F&O schedule combined with the
# statutory rates in force after Budget 2026 (options STT 0.15% on sell-side
# premium, effective 1 April 2026). VERIFY AGAINST YOUR OWN CONTRACT NOTES.
DISCOUNT_BROKER = CostProfile(
    name="discount_broker",
    brokerage_per_order=20.0,
    stt_sell=0.0015,        # 0.15% of sell premium
    exchange_txn=0.0003503,  # NSE options, on premium
    sebi_charges=0.000001,   # Rs 10 per crore
    stamp_duty_buy=0.00003,  # 0.003% of buy premium
    gst=0.18,
)

# Deliberately pessimistic: a stress case for "does the edge survive costs?"
FULL_SERVICE = CostProfile(
    name="full_service",
    brokerage_per_order=100.0,
    stt_sell=0.0015,
    exchange_txn=0.0003503,
    sebi_charges=0.000001,
    stamp_duty_buy=0.00003,
    gst=0.18,
)

PROFILES: dict[str, CostProfile] = {
    p.name: p for p in (NONE, DISCOUNT_BROKER, FULL_SERVICE)
}


def get_profile(name: str | None) -> CostProfile:
    if not name:
        return NONE
    key = str(name).strip().lower()
    if key not in PROFILES:
        raise ValueError(
            f"Unknown cost profile {name!r}. Available: {', '.join(sorted(PROFILES))}"
        )
    return PROFILES[key]


def leg_cost(profile: CostProfile, premium: float, quantity: int, is_sell: bool) -> float:
    """Cost of one option leg execution (one order)."""
    if profile.name == "none":
        return 0.0
    turnover = abs(float(premium)) * abs(int(quantity))

    brokerage = profile.brokerage_per_order
    exchange = turnover * profile.exchange_txn
    sebi = turnover * profile.sebi_charges
    stt = turnover * profile.stt_sell if is_sell else 0.0
    stamp = 0.0 if is_sell else turnover * profile.stamp_duty_buy
    # GST applies to the broker/exchange/regulator fees, not to STT or stamp duty.
    gst = (brokerage + exchange + sebi) * profile.gst

    return brokerage + exchange + sebi + stt + stamp + gst


def round_trip_cost(
    profile: CostProfile,
    long_entry: float, long_exit: float,
    short_entry: float, short_exit: float,
    quantity: int,
) -> dict[str, float]:
    """
    Total cost of a two-leg vertical spread, opened and closed.

    Four executions: buy the long leg, sell the short leg, then sell the long
    leg and buy back the short leg. The direction of each execution matters
    because STT and stamp duty are one-sided.
    """
    if profile.name == "none":
        return {"entry": 0.0, "exit": 0.0, "total": 0.0, "profile": profile.name}

    entry = (
        leg_cost(profile, long_entry, quantity, is_sell=False)     # buy long leg
        + leg_cost(profile, short_entry, quantity, is_sell=True)   # sell short leg
    )
    exit_ = (
        leg_cost(profile, long_exit, quantity, is_sell=True)       # sell long leg
        + leg_cost(profile, short_exit, quantity, is_sell=False)   # buy back short leg
    )
    return {
        "entry": round(entry, 2),
        "exit": round(exit_, 2),
        "total": round(entry + exit_, 2),
        "profile": profile.name,
    }


def describe(profile: CostProfile) -> dict:
    """Human-readable breakdown for the UI, so the numbers are auditable."""
    if profile.name == "none":
        return {
            "name": "none",
            "summary": "No transaction costs applied. Net P&L equals gross P&L.",
            "components": [],
            "verify": None,
        }
    return {
        "name": profile.name,
        "summary": f"{profile.name.replace('_', ' ').title()} — costs deducted per executed order.",
        "components": [
            {"label": "Brokerage", "value": f"Rs {profile.brokerage_per_order:.0f} per order"},
            {"label": "STT (sell side)", "value": f"{profile.stt_sell * 100:.3f}% of premium"},
            {"label": "Exchange txn", "value": f"{profile.exchange_txn * 100:.4f}% of premium"},
            {"label": "SEBI charges", "value": f"{profile.sebi_charges * 100:.6f}% of premium"},
            {"label": "Stamp duty (buy side)", "value": f"{profile.stamp_duty_buy * 100:.4f}% of premium"},
            {"label": "GST", "value": f"{profile.gst * 100:.0f}% on brokerage + exchange + SEBI"},
        ],
        "verify": (
            "Rates change with every Budget and broker update. Verify against your "
            "own contract notes before quoting a net return."
        ),
    }
