#!/usr/bin/env python3
"""Draw Tree aggregation engine — v0.3 (tree_quant/4 semantics) with a v0.2 fallback.

v0.3 (default for docs with `drawtree_version: "0.3"` or any `impact_grade`):
  - leaf score from verdict (closed 6-value vocabulary; legacy mapped);
  - branch score = leaf-weighted mean (`leaf_weights`, default 1.0);
    kill if a Falsified leaf carries weight ≥ 2.0 or is in `necessity_leaves`;
  - branch verdict from thresholds (Falsified only via kill);
  - branch conviction = σ(logit(0.40) + 1.5 · score);
  - H-0 score = Σ weight·score / Σ weight, weight = IMPACT_GRADES[impact_grade];
    H-0 kill if a Falsified branch has weight ≥ 2.0; five structural guards;
  - H-0 conviction = σ(logit(0.40) + Σ w·(score/3)), positive terms halved,
    clamped to [0.005, 0.95];
  - verdict-based probabilities p_bull = h0/2, p_bear = −h0/3 (renormalised);
  - price-implied probabilities (Max-Base) and expected return for both;
  - a derivation certificate (input sha256 + frozen assumptions).

v0.2 (legacy): reversed-Fibonacci default weights, kill threshold 1.0, linear
conviction (score+3)/5. Kept verbatim so old trees re-aggregate identically.

Pure functions, no I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from . import protocol as P

# ====================================================================== shared

DEFAULT_SCORING = dict(P.VERDICT_SCORES)
DEFAULT_BRANCH_THRESHOLDS = dict(P.BRANCH_THRESHOLDS)
DEFAULT_H0_THRESHOLDS = dict(P.H0_THRESHOLDS)
DEFAULT_BRANCH_KILL_THRESHOLD = 1.0    # v0.2
DEFAULT_H0_KILL_THRESHOLD = 1.0        # v0.2


def hyps_list(doc: dict) -> list[dict]:
    """Accept `hypotheses` as a list (v0.2 docs) or an id-keyed dict (fleet stores)."""
    h = doc.get("hypotheses") or []
    if isinstance(h, dict):
        out = []
        for k, v in h.items():
            if isinstance(v, dict):
                out.append({**v, "id": v.get("id") or k})
        return out
    return [x for x in h if isinstance(x, dict)]


def parents_of(hyp: dict) -> list[str]:
    explicit = hyp.get("parents")
    if explicit:
        return list(explicit)
    hid = hyp.get("id", "")
    return [hid[0]] if hid else []


def is_v03(doc: dict) -> bool:
    if str(doc.get("drawtree_version", "")) == P.PROTOCOL_VERSION:
        return True
    return any(isinstance(b, dict) and b.get("impact_grade") for b in doc.get("branches") or [])


def _logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def score_to_branch_verdict(score: float, has_falsified_kill: bool, thresholds: dict | None = None) -> str:
    t = thresholds or P.BRANCH_THRESHOLDS
    if has_falsified_kill:
        return "Falsified"
    if score >= t["Validated"]:
        return "Validated"
    if score >= t["Trending positive"]:
        return "Trending positive"
    if score > t["Trending negative"]:
        return "Inconclusive"
    if score > t["Approaching falsification"]:
        return "Trending negative"
    return "Approaching falsification"


def score_to_h0_verdict(score: float, has_falsified_kill: bool, branch_verdicts: list[str],
                        thresholds: dict | None = None) -> str:
    t = thresholds or P.H0_THRESHOLDS
    if has_falsified_kill:
        return "Falsified"
    n_negative = sum(1 for v in branch_verdicts if v in
                     ("Trending negative", "Approaching falsification", "Falsified"))
    any_approaching_or_worse = any(v in ("Approaching falsification", "Falsified") for v in branch_verdicts)
    every_ok = all(v in ("Inconclusive", "Trending positive", "Validated") for v in branch_verdicts)
    if score >= t["Validated"] and every_ok:
        return "Validated"
    if score >= t["Trending positive"] and not any_approaching_or_worse:
        return "Trending positive"
    if score <= t["Approaching falsification"] or n_negative >= 2:
        return "Approaching falsification"
    if score <= t["Trending negative"]:
        return "Trending negative"
    return "Inconclusive"


def verdict_based_probabilities(h0_score: float) -> dict:
    p_bull = max(0.0, min(1.0, h0_score / 2))
    p_bear = max(0.0, min(1.0, -h0_score / 3))
    if p_bull + p_bear > 1.0:
        scale = 1.0 / (p_bull + p_bear)
        p_bull *= scale
        p_bear *= scale
    p_base = max(0.0, 1.0 - p_bull - p_bear)
    return {"bull": round(p_bull, 4), "base": round(p_base, 4), "bear": round(p_bear, 4)}


def price_implied_probabilities(price: float, bear: float, base: float, bull: float) -> dict:
    """Max-Base convention: zero weight on the far scenario, split the rest between
    base and the near scenario so Σ p·target = price. Outside [bear, bull] the
    result is a CLAMP, flagged by `infeasible` (above_bull | below_bear), not a
    solution. Never raises (fleet ruling R8, 2026-09-17)."""
    infeasible = None
    if price <= bear:
        p = {"bull": 0.0, "base": 0.0, "bear": 1.0}
        if price < bear:
            infeasible = "below_bear"
    elif price >= bull:
        p = {"bull": 1.0, "base": 0.0, "bear": 0.0}
        if price > bull:
            infeasible = "above_bull"
    elif price <= base:
        pb = (price - bear) / (base - bear) if base != bear else 1.0
        p = {"bull": 0.0, "base": pb, "bear": 1.0 - pb}
    else:
        pb = (bull - price) / (bull - base) if bull != base else 1.0
        p = {"bull": 1.0 - pb, "base": pb, "bear": 0.0}
    out = {k: round(v, 4) for k, v in p.items()}
    out["infeasible"] = infeasible
    return out


def expected_return(probs: dict, targets: dict, price: float) -> float:
    er = 0.0
    for k in P.SCENARIOS:
        er += float(probs[k]) * (float(targets[k]) - price) / price
    return round(er, 4)


def _targets(doc: dict) -> tuple[float | None, dict | None]:
    val = doc.get("valuation") or {}
    sp = val.get("snapshot_price")
    sc = val.get("scenarios") or {}
    try:
        price = float(sp) if sp is not None else None
        tg = {k: float(sc[k]["target_price"]) for k in P.SCENARIOS}
    except (KeyError, TypeError, ValueError):
        return (float(sp) if sp not in (None, "") else None), None
    return price, tg


# ====================================================================== v0.3

def branch_logodds_weight(br: dict) -> float:
    g = br.get("impact_grade")
    if g in P.IMPACT_GRADES:
        return P.IMPACT_GRADES[g]
    mapped = P.grade_for_legacy_weight(br.get("weight", 0))
    if mapped:
        return P.IMPACT_GRADES[mapped]
    return float(br.get("weight", 1.0)) * (2.5 / 8.0)


def score_to_conviction(score: float) -> float:
    return _sigmoid(_logit(P.CONVICTION_PRIOR) + P.CONVICTION_LAMBDA * score)


def aggregate_v03(doc: dict) -> dict:
    branches = [b for b in (doc.get("branches") or []) if isinstance(b, dict)]
    hyps = hyps_list(doc)
    branch_results: list[dict] = []
    for br in branches:
        bid = br.get("id", "")
        bw = float(br.get("weight", branch_logodds_weight(br)))
        agg = str(br.get("aggregation", "portfolio")).lower()
        leaf_weights = br.get("leaf_weights") or {}
        children = sorted((h for h in hyps if bid in parents_of(h)), key=lambda h: h.get("id", ""))
        leaves = []
        for h in children:
            verdict = h.get("verdict", "Inconclusive")
            s = P.VERDICT_SCORES.get(verdict, 0)
            hid = h.get("id", "")
            lw = float(leaf_weights.get(hid, 1.0))
            leaves.append((hid, verdict, s, lw))
        kill = False
        if not leaves:
            score = 0.0
        elif agg == "chain":   # legacy soft-min, retained for old stores only
            ss = sorted(s for _, _, s, _ in leaves)
            w = P.CHAIN_SOFTMIN_WEIGHTS[:len(ss)] + [1] * (len(ss) - len(P.CHAIN_SOFTMIN_WEIGHTS))
            score = sum(x * wi for x, wi in zip(ss, w)) / sum(w[:len(ss)])
            if any(v == "Falsified" for _, v, _, _ in leaves):
                kill = True
        else:
            num = sum(lw * s for _, _, s, lw in leaves)
            den = sum(lw for _, _, _, lw in leaves)
            score = (num / den) if den > 0 else 0.0
            if any(v == "Falsified" and lw >= P.BRANCH_KILL_THRESHOLD for _, v, _, lw in leaves):
                kill = True
            nec = set(br.get("necessity_leaves") or [])
            if nec and any(hid in nec and v == "Falsified" for hid, v, _, _ in leaves):
                kill = True
        branch_results.append({
            "id": bid, "weight": bw, "impact_grade": br.get("impact_grade"), "aggregation": agg,
            "n_leaves": len(children), "score": round(score, 4),
            "conviction": round(score_to_conviction(score), 4),
            "verdict": score_to_branch_verdict(score, kill), "kill_fired": kill,
        })

    num = den = 0.0
    add_logit = _logit(P.CONVICTION_PRIOR)
    h0_kill = False
    for i, br in enumerate(branch_results):
        num += br["weight"] * br["score"]
        den += br["weight"]
        w_lo = branch_logodds_weight(branches[i])
        br["w_logodds"] = round(w_lo, 4)
        contrib = w_lo * (br["score"] / 3.0)
        if contrib > 0:
            contrib *= P.UPWARD_CREDIT_DAMP
        add_logit += contrib
        if br["verdict"] == "Falsified" and br["weight"] >= P.H0_KILL_THRESHOLD:
            h0_kill = True
    h0_score = (num / den) if den > 0 else 0.0
    h0_verdict = score_to_h0_verdict(h0_score, h0_kill, [b["verdict"] for b in branch_results])
    conviction = (min(P.CONVICTION_CAP, max(P.CONVICTION_FLOOR, _sigmoid(add_logit)))
                  if den > 0 else P.CONVICTION_PRIOR)
    vb = verdict_based_probabilities(h0_score)

    price, tg = _targets(doc)
    pi = None; er_v = None; er_p = None
    if price and tg:
        pi = price_implied_probabilities(price, tg["bear"], tg["base"], tg["bull"])
        er_v = expected_return(vb, tg, price)
        er_p = expected_return(pi, tg, price)

    inputs = {"branches": branches, "hypotheses": {h.get("id"): {k: h.get(k) for k in ("id", "verdict", "parents")} for h in hyps}}
    input_hash = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":"), default=str).encode()).hexdigest()
    return {
        "protocol": P.PROTOCOL_VERSION, "engine": P.ENGINE_VERSION, "baseline_semantics": P.BASELINE_SEMANTICS,
        "branches": branch_results,
        "h0_score": round(h0_score, 4), "h0_verdict": h0_verdict, "h0_kill_fired": h0_kill,
        "conviction": round(conviction, 4), "_conv_logit_raw": round(add_logit, 6),
        "verdict_based": vb,
        "price_implied": pi,
        "scenario_probabilities": vb,                 # v0.2-compatible alias
        "expected_return": er_v,                      # v0.2-compatible alias (verdict-based)
        "expected_return_detail": {"verdict_based": er_v, "price_implied": er_p},
        "certificate": {
            "version": P.CERTIFICATE_VERSION, "input_sha256": input_hash,
            "claim": "conditional deterministic derivation; not a factual validation of the verdicts",
            "point_in_time_verified": False,
            "assumptions": {
                "verdict_scores": P.VERDICT_SCORES, "prior": P.CONVICTION_PRIOR, "lambda": P.CONVICTION_LAMBDA,
                "positive_credit": P.UPWARD_CREDIT_DAMP, "conviction_bounds": [P.CONVICTION_FLOOR, P.CONVICTION_CAP],
                "branch_thresholds": P.BRANCH_THRESHOLDS, "h0_thresholds": P.H0_THRESHOLDS,
                "kill_thresholds": [P.BRANCH_KILL_THRESHOLD, P.H0_KILL_THRESHOLD],
                "impact_grades": P.IMPACT_GRADES, "legacy_grade_map": P.LEGACY_GRADE_MAP,
                "rounded_branch_scores_before_h0": 4, "price_implied_convention": "max_base",
                "probabilities_empirically_calibrated": False,
            },
        },
    }


# ====================================================================== v0.2 (legacy, verbatim semantics)

def fibonacci_weights(n: int) -> list[float]:
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
    cfg = doc.get("aggregation") or {}
    return {
        "scoring": {**DEFAULT_SCORING, **(cfg.get("scoring") or {})},
        "branch_thresholds": {**DEFAULT_BRANCH_THRESHOLDS, **(cfg.get("branch_thresholds") or {})},
        "h0_thresholds": {**DEFAULT_H0_THRESHOLDS, **(cfg.get("h0_thresholds") or {})},
        "branch_weight_default": cfg.get("branch_weight_default", "fibonacci"),
        "branch_kill_threshold": cfg.get("branch_kill_threshold", DEFAULT_BRANCH_KILL_THRESHOLD),
        "h0_kill_threshold": cfg.get("h0_kill_threshold", DEFAULT_H0_KILL_THRESHOLD),
    }


def parent_weight(hyp: dict, branch_id: str) -> float:
    pw = hyp.get("parent_weights") or {}
    return float(pw.get(branch_id, 1.0))


def leaf_weight(hyp: dict) -> float:
    return float(hyp.get("weight", 1.0))


def aggregate_v02(doc: dict) -> dict:
    cfg = get_aggregation_config(doc)
    scoring = cfg["scoring"]
    branches_in = doc.get("branches") or []
    hypotheses_in = hyps_list(doc)
    n = len(branches_in)
    default_weights = default_branch_weights(n, cfg["branch_weight_default"])
    branch_results: list[dict] = []
    for i, b in enumerate(branches_in):
        bid = b.get("id", "")
        bw = float(b.get("weight", default_weights[i] if i < len(default_weights) else 1.0))
        numerator = denom = 0.0
        kill_fired = False
        for h in hypotheses_in:
            if bid not in parents_of(h):
                continue
            eff = leaf_weight(h) * parent_weight(h, bid)
            if eff <= 0:
                continue
            verdict = h.get("verdict", "Inconclusive")
            score = scoring.get(verdict, 0)
            numerator += eff * score
            denom += eff
            if verdict == "Falsified" and eff >= cfg["branch_kill_threshold"]:
                kill_fired = True
        branch_score = (numerator / denom) if denom > 0 else 0.0
        branch_results.append({
            "id": bid, "weight": bw, "score": round(branch_score, 4),
            "verdict": score_to_branch_verdict(branch_score, kill_fired, cfg["branch_thresholds"]),
            "kill_fired": kill_fired,
        })
    numerator = denom = 0.0
    h0_kill_fired = False
    for br in branch_results:
        numerator += br["weight"] * br["score"]
        denom += br["weight"]
        if br["verdict"] == "Falsified" and br["weight"] >= cfg["h0_kill_threshold"]:
            h0_kill_fired = True
    h0_score = (numerator / denom) if denom > 0 else 0.0
    h0_verdict = score_to_h0_verdict(h0_score, h0_kill_fired, [b["verdict"] for b in branch_results], cfg["h0_thresholds"])
    conviction = max(0.0, min(1.0, (h0_score + 3) / 5))
    scenario_probs = verdict_based_probabilities(h0_score)
    er: float | None = None
    val = doc.get("valuation") or {}
    sp = val.get("snapshot_price")
    scenarios = val.get("scenarios") or {}
    if sp and scenarios:
        try:
            spf = float(sp)
            acc = 0.0
            for scen_key, prob_default in scenario_probs.items():
                scen = scenarios.get(scen_key) or {}
                tp = scen.get("target_price")
                if tp is None:
                    continue
                p = scen.get("probability", prob_default)
                acc += float(p) * (float(tp) - spf) / spf
            er = round(acc, 4)
        except (TypeError, ValueError):
            er = None
    return {
        "protocol": "0.2",
        "branches": branch_results, "h0_score": round(h0_score, 4), "h0_verdict": h0_verdict,
        "h0_kill_fired": h0_kill_fired, "conviction": round(conviction, 4),
        "scenario_probabilities": scenario_probs, "expected_return": er,
    }


# ====================================================================== dispatch

def aggregate(doc: dict) -> dict:
    """v0.3 engine for v0.3 docs (or any doc carrying impact grades); v0.2 otherwise."""
    return aggregate_v03(doc) if is_v03(doc) else aggregate_v02(doc)


def annotate_doc(doc: dict) -> dict:
    """Write computed fields back into the doc in place (both protocol versions)."""
    result = aggregate(doc)
    bymap = {b["id"]: b for b in result["branches"]}
    for b in doc.get("branches") or []:
        r = bymap.get(b.get("id", ""))
        if r:
            b["weight"] = r["weight"]
            b["verdict"] = r["verdict"]
            b["verdict_score"] = r["score"]
            if "conviction" in r:
                b["conviction"] = r["conviction"]
    doc.setdefault("root", {})
    doc["root"]["verdict"] = result["h0_verdict"]
    doc["root"]["verdict_score"] = result["h0_score"]
    doc["root"]["conviction"] = result["conviction"]
    val = doc.get("valuation")
    if val and result.get("expected_return") is not None:
        val["expected_return"] = result["expected_return"]
        if result.get("price_implied") is not None:
            val["expected_return_price_implied"] = result["expected_return_detail"]["price_implied"]
            val["price_implied_probabilities"] = result["price_implied"]
        scenarios = val.get("scenarios") or {}
        for k, p in result["scenario_probabilities"].items():
            if k in scenarios and "probability" not in scenarios[k]:
                scenarios[k]["probability"] = p
    if is_v03(doc):
        doc.setdefault("computed", {})
        doc["computed"].update({"engine": P.ENGINE_VERSION, "h0_score": result["h0_score"], "h0_verdict": result["h0_verdict"],
                                "conviction": result["conviction"], "verdict_based": result["verdict_based"],
                                "price_implied": result.get("price_implied"), "certificate": result["certificate"]})
    return doc


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()
    print(json.dumps(aggregate(json.loads(open(args.path).read())), indent=2, ensure_ascii=False))
