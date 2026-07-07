"""Phase 1 milestone acceptance tests (charter: "Phase 1 milestone").

Written early, red until earned. Each is a strict xfail: when an increment
makes one pass, the suite fails until the marker is removed — progress is
recorded deliberately, never by accident. Do not weaken these to match the
implementation; the charter governs.
"""

import pytest


def _increment(name: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        raises=NotImplementedError, strict=True, reason=f"red until increment: {name}"
    )


@_increment("decisions + validation")
def test_one_story_structure_is_defined_only_by_decisions() -> None:
    """Grid + gravity framing strategy + one lateral strategy + one opening,
    all committed through the changeset pipeline."""
    raise NotImplementedError


@_increment("derivation for the milestone structure")
def test_derivation_produces_members_analysis_artifact_and_bill() -> None:
    """Member instances with spans and tributary widths; a self-contained
    analysis model artifact; a bill of elements. The opening induces a header
    carrying gravity-load-path intent — computed, not typed in."""
    raise NotImplementedError


@_increment("xara adapter + verification")
def test_solver_results_verify_against_hand_calcs() -> None:
    """The solver service (local, cloud-shaped interface) solves the artifact;
    results match hand calculations within the stated tolerances."""
    raise NotImplementedError


@_increment("overrides")
def test_surveyed_override_flows_through_with_provenance() -> None:
    """A pinned surveyed member size differing from the derived value flows
    through derivation and analysis with provenance intact."""
    raise NotImplementedError


@_increment("intent checkers + solve-time design checks")
def test_intent_violating_changeset_is_rejected_with_structured_error() -> None:
    """Deleting the header while the opening remains dies in validation with a
    structured error citing the violated intent and the broken load path."""
    raise NotImplementedError


@_increment("exploration loop")
def test_exploration_sweep_is_persisted_replayable_and_pluggable() -> None:
    """Joist spacing 12/16/19.2/24 in crossed with beam layouts; objective min weight;
    hard constraints unity and deflection (L/360 live, L/240 total); concurrent
    dispatch; every generation persisted; replayable; stub LLM proposer slots
    into the same protocol."""
    raise NotImplementedError


@_increment("exploration loop")
def test_milestone_queries_answer() -> None:
    """ "What carries joist J5?", "why does opening D1 have a header?", "which
    variant minimizes weight while keeping all members under unity?"."""
    raise NotImplementedError
