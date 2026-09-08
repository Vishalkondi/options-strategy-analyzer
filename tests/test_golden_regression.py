"""
Golden regression tests: real, known-good historical results from
client-validated output or an independently verified implementation.

BLOCKED — no golden fixture exists yet (GAP_ANALYSIS B5). Fixtures must
never be generated from this engine and then used as proof the engine is
correct — that is circular. This test intentionally skips rather than
silently passing.
"""
import pytest


@pytest.mark.skip(reason="BLOCKED: no client-validated golden backtest result supplied yet (GAP_ANALYSIS B5)")
def test_golden_directional_debit_spread_matches_validated_result():
    pass
