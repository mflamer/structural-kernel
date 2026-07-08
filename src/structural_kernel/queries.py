"""The milestone queries (charter): load-path, explanation, and ranking reads.

Queries are pure reads over derived models and exploration records — the
AI-surface increment wraps these in an API; the semantics live here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from structural_kernel.objects import DecisionTarget, IntentInstance

if TYPE_CHECKING:
    from structural_kernel.derivation import DerivedModel
    from structural_kernel.explorations import Exploration


def what_carries(model: DerivedModel, eid: str) -> list[str]:
    """ "What carries joist J5?" — the elements it bears on, from the load-path
    graph."""
    for element in model.elements:
        if element.eid == eid:
            return list(element.supports)
    raise KeyError(f"no element {eid!r} in the derived model")


def why(model: DerivedModel, eid: str) -> list[IntentInstance]:
    """ "Why does this element exist?" — its structural intent, computed by
    derivation or authored on decisions, never typed into a form."""
    for element in model.elements:
        if element.eid == eid:
            return list(element.intent)
    raise KeyError(f"no element {eid!r} in the derived model")


def header_for_opening(model: DerivedModel, opening_did: str) -> str | None:
    """ "Why does opening D1 have a header?" resolves to the header whose intent
    redirects the gravity load path around that opening."""
    for element in model.elements:
        if element.role != "header":
            continue
        for instance in element.intent:
            for relation in instance.relations:
                if (
                    relation.role == "redirects_load_around"
                    and isinstance(relation.target, DecisionTarget)
                    and relation.target.decision == opening_did
                ):
                    return element.eid
    return None


def best_variant(exploration: Exploration) -> str | None:
    """ "Which variant minimizes the objective while satisfying every hard
    constraint?" — the top of the latest evaluation's ranking, if feasible."""
    if not exploration.evaluations:
        return None
    evaluation = exploration.evaluations[-1]
    for key in evaluation.ranking:
        if evaluation.per_candidate[key].feasible:
            return key
    return None
