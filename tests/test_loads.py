"""Load combinations: the ASCE 7 seam (ADR 0007), ASD and LRFD gravity slices
plus the strength/service purpose split the LRFD deflection path relies on."""

import pytest

from structural_kernel.loads import COMBO_SETS, combos_for


def test_asd_gravity_combos_are_service_level() -> None:
    combos = {c.name: c for c in combos_for("ASCE7-22-2.4-ASD", frozenset({"D", "L"}))}
    assert set(combos) == {"D", "D+L"}
    # ASD combinations are unfactored service loads — they size stress and check
    # deflection at once, so every one is tagged service.
    assert all(c.purpose == "service" for c in combos.values())
    assert combos["D+L"].factors == {"D": 1.0, "L": 1.0}


def test_lrfd_gravity_carries_factored_strength_and_unfactored_service_combos() -> None:
    combos = {c.name: c for c in combos_for("ASCE7-22-2.3-LRFD", frozenset({"D", "L"}))}
    # factored strength combos size the steel...
    assert combos["1.4D"].purpose == "strength"
    assert combos["1.2D+1.6L"].purpose == "strength"
    assert combos["1.2D+1.6L"].factors == {"D": 1.2, "L": 1.6}
    # ...and unfactored service combos (named to match the deflection code path)
    # drive the L/360-L/240 limits.
    assert combos["D"].purpose == "service"
    assert combos["D+L"].purpose == "service"
    assert combos["D+L"].factors == {"D": 1.0, "L": 1.0}


def test_combo_sets_are_limited_to_the_cases_present() -> None:
    dead_only = {c.name for c in combos_for("ASCE7-22-2.3-LRFD", frozenset({"D"}))}
    assert dead_only == {"1.4D", "D"}  # no live combos without an L case


def test_registered_sets_and_unknown_rejection() -> None:
    assert set(COMBO_SETS) == {"ASCE7-22-2.4-ASD", "ASCE7-22-2.3-LRFD"}
    with pytest.raises(ValueError, match="no combination engine"):
        combos_for("Eurocode", frozenset({"D"}))
