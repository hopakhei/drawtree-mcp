"""Scenario-valuation Step 3: implied probability reverse-engineering.

Given a tree's leaf verdicts and a Bull/Base/Bear target-price triple, solve
for the market's implied probability distribution from the current price.

We use the documented method from the scenario-valuation skill:
  Current Price ≈ P(Bull)·V(Bull) + P(Base)·V(Base) + P(Bear)·V(Bear)
  P(Bull) + P(Base) + P(Bear) = 1
  Anchor: P(Base) = 0.5 by default; user can override.

We also identify the **tension point**: the leaf whose verdict change would
move the implied probabilities most. This is the actionable output — what to
watch.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScenarioInputs:
    bull_value: float
    base_value: float
    bear_value: float
    current_price: float
    base_anchor: float = 0.5  # override-able


@dataclass
class ImpliedProbs:
    bull: float
    base: float
    bear: float


def reverse_engineer(inputs: ScenarioInputs) -> ImpliedProbs:
    """Solve for P(Bull) and P(Bear) given P(Base) anchor.

    P(Bull)·V_Bull + P(Base)·V_Base + P(Bear)·V_Bear = Price
    P(Bull) + P(Bear) = 1 - P(Base)
    -> P(Bull) = (Price - P(Base)·V_Base - (1 - P(Base))·V_Bear) / (V_Bull - V_Bear)
    """
    base = max(0.05, min(0.9, inputs.base_anchor))
    if abs(inputs.bull_value - inputs.bear_value) < 1e-6:
        # Degenerate: bull == bear, can't separate. Return uniform.
        rest = (1 - base) / 2
        return ImpliedProbs(rest, base, rest)
    p_bull = (inputs.current_price - base * inputs.base_value -
              (1 - base) * inputs.bear_value) / (inputs.bull_value - inputs.bear_value)
    p_bull = max(0.0, min(1.0, p_bull))
    p_bear = max(0.0, min(1.0, 1 - base - p_bull))
    p_bull = max(0.0, 1 - base - p_bear)
    # Final renormalise in case of clamp-loss
    total = p_bull + base + p_bear
    if abs(total - 1.0) > 0.001:
        scale = 1.0 / max(total, 1e-9)
        p_bull *= scale
        p_bear *= scale
        base *= scale
    return ImpliedProbs(round(p_bull, 4), round(base, 4), round(p_bear, 4))


def what_market_betting(probs: ImpliedProbs, error_type: str | None = None) -> dict:
    """Plain-language description of what each implied probability is betting on."""
    pb = probs.bull
    pb_s = probs.base
    pbr = probs.bear

    bull_desc = f"Bull case at {pb*100:.0f}%: market implicitly thinks the upside fundamentals materialise."
    base_desc = f"Base case at {pb_s*100:.0f}%: market thinks the current narrative simply persists, with no meaningful re-rating."
    bear_desc = f"Bear case at {pbr*100:.0f}%: market thinks downside risk is largely contained — only a small tail of falsification."

    if error_type:
        if "Identity Mislabel" in error_type:
            bear_desc += " Specifically, the market is NOT pricing the chance that this stock is mis-classified."
        elif "Permanence Assumption" in error_type:
            base_desc += " Specifically, the market is treating the current state as permanent rather than transitional."
        elif "Narrative Inertia" in error_type:
            bear_desc += " Specifically, the market is anchored on the old narrative even as fundamentals diverge."
        elif "Discrete Event Mispricing" in error_type:
            bear_desc += " Specifically, the market is under-pricing a binary discrete-event outcome."

    return {
        "bull": bull_desc,
        "base": base_desc,
        "bear": bear_desc,
    }


def identify_tension_point(tree: dict, probs: ImpliedProbs) -> dict | None:
    """Find the leaf whose verdict change would most affect the H-0 score
    and therefore the implied probabilities.

    Heuristic: take the leaf with the largest effective_weight (leaf_weight ×
    branch_weight). If that leaf is currently Inconclusive / Trending pos / Trending neg,
    a binary outcome shifts the picture most.
    """
    branches = {b["id"]: b for b in tree.get("branches", []) if isinstance(b, dict)}
    hypotheses = tree.get("hypotheses") or []

    best = None
    best_weight = 0.0
    for h in hypotheses:
        hid = h.get("id", "")
        parents = h.get("parents") or [hid[:1]] if hid else []
        if not parents:
            continue
        bw = float(branches.get(parents[0], {}).get("weight", 1.0))
        lw = float(h.get("weight", 1.0))
        eff = lw * bw
        verdict = h.get("verdict", "Inconclusive")
        # We care most about leaves that are still in flux
        in_flux = verdict in (
            "Inconclusive", "Trending positive", "Trending negative",
            "Approaching falsification",
        )
        if in_flux and eff > best_weight:
            best_weight = eff
            best = h

    if not best:
        return None

    return {
        "leaf_id": best.get("id"),
        "leaf_title": best.get("title"),
        "current_verdict": best.get("verdict"),
        "effective_weight": round(best_weight, 2),
        "if_validated": (
            f"P(Bull) re-rates upward; P(Base) compresses; P(Bear) collapses toward 0."
        ),
        "if_falsified": (
            f"P(Bear) doubles; P(Bull) collapses toward 0; price re-rates to bear scenario value."
        ),
        "actionable_next_step": (
            f"Watch for evidence that resolves leaf {best.get('id')} — "
            f"its falsification triggers are the highest-leverage observations."
        ),
    }
