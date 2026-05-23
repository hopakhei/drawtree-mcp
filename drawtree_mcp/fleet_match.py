"""Fleet-level pattern matching — the secret sauce of register_narrative.

When a user submits a narrative handoff with a detected error_type, we scan
the existing public fleet for trees whose narrative classification matches
and surface that historical context to the user's Claude.
"""
from __future__ import annotations

from . import api_client


# Mapping from narrative-detection error types to drawtree-api archetypes.
# (The drawtree v0.2 archetype enum is a separate but related taxonomy.)
ERROR_TYPE_TO_ARCHETYPES: dict[str, list[str]] = {
    "Identity Mislabel": ["Disruption fear", "Valuation re-rating", "AI tailwind"],
    "Permanence Assumption Error": ["Cyclical recovery", "Valuation re-rating", "Margin compression"],
    "Life Cycle Mismatch": ["Cyclical recovery", "Disruption fear", "Growth thesis"],
    "Narrative Inertia": ["Valuation re-rating", "Margin compression"],
    "Discrete Event Mispricing": ["Regulatory overhang", "Execution risk"],
    "Macro Narrative Contagion": ["Macro-driven", "Regulatory overhang"],
}


def find_similar_trees(error_type: str, ticker: str, max_results: int = 5) -> list[dict]:
    """Return up to N trees with related archetypes, plus their current
    H-0 verdict and conviction so the user sees how peers played out.

    Excludes the user's own ticker if it's already in the fleet.
    """
    target_archetypes = ERROR_TYPE_TO_ARCHETYPES.get(error_type, [])
    if not target_archetypes:
        return []

    try:
        trees = api_client.list_trees(limit=200)
    except Exception:
        return []

    matches = []
    for t in trees:
        if t.get("ticker", "").upper() == ticker.upper():
            continue
        tree = t.get("tree") or {}
        cls = (tree.get("root") or {}).get("classification") or {}
        archetype = cls.get("archetype")
        if archetype in target_archetypes:
            agg = t.get("aggregation") or {}
            matches.append({
                "ticker": t.get("ticker"),
                "agent_handle": t.get("agent_handle"),
                "archetype": archetype,
                "archetype_rationale": cls.get("archetype_rationale"),
                "h0_verdict": agg.get("h0_verdict"),
                "conviction": agg.get("conviction"),
                "expected_return": agg.get("expected_return"),
            })
    matches.sort(key=lambda m: -(m.get("conviction") or 0))
    return matches[:max_results]
