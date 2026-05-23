#!/usr/bin/env python3
"""Draw Tree v0.2 aggregation engine.

Computes:
  - leaf score from verdict
  - branch score (weighted average of leaf scores)
  - branch verdict (mapped from branch score with kill switch)
  - H-0 score (weighted average of branch scores)
  - H-0 verdict (mapped from H-0 score with structural guards)
  - conviction (h0_score normalised to [0, 1])
  - per-scenario probability (default-derived from h0_score)
  - expected return (Σ probability × distance)

Pure functions, no I/O. Imported by build_examples_v02.py and validate_drawtree_v02.py.
"""
from __future__ import annotations

from typing import Any


DEFAULT_SCORING = {
    "Validated": 2,
    "Trending positive": 1,
    "Inconclusive": 0,
    "Trending negative": -1,
    "Approaching falsification": -2,
    "Falsified": -3,
    # Legacy 3-value vocab — mapped onto the same numeric scale.
    "supported": 2,
    "partially_supported": 0,
    "challenged": -2,
    "pending": 0,
}

DEFAULT_BRANCH_THRESHOLDS = {
    "Validated": 1.5,
    "Trending positive": 0.5,
    "Trending negative": -0.5,
    "Approaching falsification": -1.5,
    # Falsified handled by kill-switch, not threshold
}

DEFAULT_H0_THRESHOLDS = dict(DEFAULT_BRANCH_THRESHOLDS)

DEFAULT_BRANCH_KILL_THRESHOLD = 1.0
DEFAULT_H0_KILL_THRESHOLD = 1.0


def fibonacci_weights(n: int) -> list[float]:
    """Reversed-Fibonacci weights: position 1 is heaviest, position n is lightest.
    n=4 -> [5, 3, 2, 1]; n=5 -> [8, 5, 3, 2, 1]; n=3 -> [3, 2, 1]; n=2 -> [2, 1]; n=1 -> [1]."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    fib = [1, 2]
    while len(fib) < n:
        fib.append(fib[-1] + fib[-2])
    return [float(x) for x in reversed(fib[:n])]


def linear_weights(n: int) -> list[float]:
    return [float(n - i) for i in range(n)]


def uniform_weights(n: int) -> list[float]:
    return [1.0] * n


def default_branch_weights(n: int, kind: str) -> list[float]:
    if kind == "fibonacci":
        return fibonacci_weights(n)
    if kind == "linear":
        return linear_weights(n)
    return uniform_weights(n)


def get_aggregation_config(doc: dict) -> dict:
    """Resolve aggregation config with defaults."""
    cfg = doc.get("aggregation") or {}
    return {
        "scoring": {**DEFAULT_SCORING, **(cfg.get("scoring") or {})},
        "branch_thresholds": {**DEFAULT_BRANCH_THRESHOLDS, **(cfg.get("branch_thresholds") or {})},
        "h0_thresholds": {**DEFAULT_H0_THRESHOLDS, **(cfg.get("h0_thresholds") or {})},
        "branch_weight_default": cfg.get("branch_weight_default", "fibonacci"),
        "branch_kill_threshold": cfg.get("branch_kill_threshold", DEFAULT_BRANCH_KILL_THRESHOLD),
        "h0_kill_threshold": cfg.get("h0_kill_threshold", DEFAULT_H0_KILL_THRESHOLD),
    }


def parents_of(hyp: dict) -> list[str]:
    """Return list of parent branch IDs. Default: first letter of hypothesis ID."""
    explicit = hyp.get("parents")
    if explicit:
        return list(explicit)
    hid = hyp.get("id", "")
    if hid:
        return [hid[0]]
    return []


def parent_weight(hyp: dict, branch_id: str) -> float:
    """Per-parent weight for a (multi-parent) leaf. Defaults to 1.0."""
    pw = hyp.get("parent_weights") or {}
    return float(pw.get(branch_id, 1.0))


def leaf_weight(hyp: dict) -> float:
    return float(hyp.get("weight", 1.0))


def score_to_branch_verdict(score: float, has_falsified_kill: bool, thresholds: dict) -> str:
    if has_falsified_kill:
        return "Falsified"
    if score >= thresholds["Validated"]:
        return "Validated"
    if score >= thresholds["Trending positive"]:
        return "Trending positive"
    if score > thresholds["Trending negative"]:
        return "Inconclusive"
    if score > thresholds["Approaching falsification"]:
        return "Trending negative"
    return "Approaching falsification"


def score_to_h0_verdict(
    score: float,
    has_falsified_kill: bool,
    branch_verdicts: list[str],
    thresholds: dict,
) -> str:
    if has_falsified_kill:
        return "Falsified"
    # Structural guards
    n_negative = sum(1 for v in branch_verdicts if v in
                     ("Trending negative", "Approaching falsification", "Falsified"))
    any_approaching_or_worse = any(
        v in ("Approaching falsification", "Falsified") for v in branch_verdicts)
    every_branch_inconclusive_or_better = all(
        v in ("Inconclusive", "Trending positive", "Validated") for v in branch_verdicts)

    if score >= thresholds["Validated"] and every_branch_inconclusive_or_better:
        return "Validated"
    if score >= thresholds["Trending positive"] and not any_approaching_or_worse:
        return "Trending positive"
    if score <= thresholds["Approaching falsification"] or n_negative >= 2:
        return "Approaching falsification"
    if score <= thresholds["Trending negative"]:
        return "Trending negative"
    return "Inconclusive"


def aggregate(doc: dict) -> dict:
    """Compute branch + H-0 verdicts and return a result dict.

    Returns:
        {
          "branches": [{id, score, verdict, kill_fired}],
          "h0_score": float,
          "h0_verdict": str,
          "conviction": float in [0, 1],
          "scenario_probabilities": {bull, base, bear},
          "expected_return": float | None,
        }
    """
    cfg = get_aggregation_config(doc)
    scoring = cfg["scoring"]
    branches_in = doc.get("branches") or []
    hypotheses_in = doc.get("hypotheses") or []

    n = len(branches_in)
    default_weights = default_branch_weights(n, cfg["branch_weight_default"])

    # ----- Per-branch aggregation
    branch_results: list[dict] = []
    for i, b in enumerate(branches_in):
        bid = b.get("id", "")
        bw = float(b.get("weight", default_weights[i] if i < len(default_weights) else 1.0))

        numerator = 0.0
        denom = 0.0
        kill_fired = False
        for h in hypotheses_in:
            parents = parents_of(h)
            if bid not in parents:
                continue
            lw = leaf_weight(h)
            pw = parent_weight(h, bid)
            eff = lw * pw
            if eff <= 0:
                continue
            verdict = h.get("verdict", "Inconclusive")
            score = scoring.get(verdict, 0)
            numerator += eff * score
            denom += eff
            if verdict == "Falsified" and eff >= cfg["branch_kill_threshold"]:
                kill_fired = True

        branch_score = (numerator / denom) if denom > 0 else 0.0
        branch_verdict = score_to_branch_verdict(
            branch_score, kill_fired, cfg["branch_thresholds"])

        branch_results.append({
            "id": bid,
            "weight": bw,
            "score": round(branch_score, 4),
            "verdict": branch_verdict,
            "kill_fired": kill_fired,
        })

    # ----- H-0 aggregation
    numerator = 0.0
    denom = 0.0
    h0_kill_fired = False
    for br in branch_results:
        w = br["weight"]
        numerator += w * br["score"]
        denom += w
        if br["verdict"] == "Falsified" and w >= cfg["h0_kill_threshold"]:
            h0_kill_fired = True

    h0_score = (numerator / denom) if denom > 0 else 0.0
    branch_verdicts = [b["verdict"] for b in branch_results]
    h0_verdict = score_to_h0_verdict(
        h0_score, h0_kill_fired, branch_verdicts, cfg["h0_thresholds"])

    # ----- Conviction
    conviction = max(0.0, min(1.0, (h0_score + 3) / 5))

    # ----- Default scenario probabilities
    p_bull = max(0.0, min(1.0, h0_score / 2))
    p_bear = max(0.0, min(1.0, -h0_score / 3))
    # Cap so they don't sum > 1
    if p_bull + p_bear > 1.0:
        scale = 1.0 / (p_bull + p_bear)
        p_bull *= scale
        p_bear *= scale
    p_base = max(0.0, 1.0 - p_bull - p_bear)

    scenario_probs = {
        "bull": round(p_bull, 4),
        "base": round(p_base, 4),
        "bear": round(p_bear, 4),
    }

    # ----- Expected return (if valuation present)
    expected_return: float | None = None
    val = doc.get("valuation") or {}
    sp = val.get("snapshot_price")
    scenarios = val.get("scenarios") or {}
    if sp and scenarios:
        try:
            sp = float(sp)
            er = 0.0
            for scen_key, prob_default in scenario_probs.items():
                scen = scenarios.get(scen_key) or {}
                tp = scen.get("target_price")
                if tp is None:
                    continue
                p = scen.get("probability", prob_default)
                distance = (float(tp) - sp) / sp
                er += float(p) * distance
            expected_return = round(er, 4)
        except (TypeError, ValueError):
            expected_return = None

    return {
        "branches": branch_results,
        "h0_score": round(h0_score, 4),
        "h0_verdict": h0_verdict,
        "h0_kill_fired": h0_kill_fired,
        "conviction": round(conviction, 4),
        "scenario_probabilities": scenario_probs,
        "expected_return": expected_return,
    }


# Convenience: write computed fields back into the doc in-place.
def annotate_doc(doc: dict) -> dict:
    """Mutates doc, adding computed fields. Returns the same doc for chaining."""
    result = aggregate(doc)
    bymap = {b["id"]: b for b in result["branches"]}
    for b in doc.get("branches") or []:
        bid = b.get("id", "")
        r = bymap.get(bid)
        if r:
            b["weight"] = r["weight"]
            b["verdict"] = r["verdict"]
            b["verdict_score"] = r["score"]
    doc.setdefault("root", {})
    doc["root"]["verdict"] = result["h0_verdict"]
    doc["root"]["verdict_score"] = result["h0_score"]
    doc["root"]["conviction"] = result["conviction"]
    val = doc.get("valuation")
    if val and result["expected_return"] is not None:
        val["expected_return"] = result["expected_return"]
        scenarios = val.get("scenarios") or {}
        for k, p in result["scenario_probabilities"].items():
            if k in scenarios and "probability" not in scenarios[k]:
                scenarios[k]["probability"] = p
    return doc


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()
    doc = json.loads(open(args.path).read())
    out = aggregate(doc)
    print(json.dumps(out, indent=2, ensure_ascii=False))
