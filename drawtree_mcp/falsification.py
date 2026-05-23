"""Helpers for `suggest_falsification` — turn a hypothesis into an observable
kill condition.

We do NOT call an LLM. We use:
  1. Heuristic patterns over the hypothesis text
  2. Framework affinity (when the leaf is anchored to a specific framework)
  3. Disclosure-trigger keywords
  4. The protocol's own observability regex from drawtree-protocol-v0.2

The output is a *suggestion*. The user's Claude refines it before commit.
"""
from __future__ import annotations

import re
from typing import Iterable

# The same observability rules drawtree-api enforces server-side.
# Source: stock-trees/protocol/validate_drawtree_v02.py
OBSERVABILITY_PATTERNS = [
    re.compile(r"[<>≤≥]\s*-?\d"),
    re.compile(r"\d+\s*%"),
    re.compile(r"\$\s*\d"),
    re.compile(r"\d{4}-\d{2}(-\d{2})?"),
    re.compile(r"Q[1-4]\s*FY?\d{2,4}"),
    re.compile(r"FY\s*\d{2,4}"),
    re.compile(r"20\d{2}\s*(H[12]|上|下)"),
    re.compile(r"\d{1,2}/\d{1,2}"),
    re.compile(r"(披露|quantif|announce|confirm|disclos|首次|reveal)", re.IGNORECASE),
    re.compile(r"\d+\s*(times|x|×|倍|顆|engines?|個)"),
]


def is_observable(s: str) -> bool:
    return any(p.search(s) for p in OBSERVABILITY_PATTERNS)


# Heuristic mapping: keyword in hypothesis text -> typical observable metric template
KEYWORD_METRICS = [
    # Growth & revenue
    (r"\b(arr|recurring revenue|subscription)\b",
     "FY{year} H1 {ARR|subscription revenue} growth YoY < {threshold}% disclosed"),
    (r"\b(revenue growth|topline growth|sales growth)\b",
     "Two consecutive quarters with revenue YoY < {threshold}%"),
    (r"\b(market share|share gain)\b",
     "{Industry-leader source} share data shows market share down by ≥{threshold}pp YoY"),
    # Margins & unit economics
    (r"\b(gross margin|operating margin|ebitda margin)\b",
     "Two consecutive quarters with {margin} compressing ≥{threshold}pp YoY"),
    (r"\b(ltv|cac|payback)\b",
     "LTV/CAC drops below {threshold}x in disclosed cohort metrics"),
    (r"\b(net revenue retention|nrr)\b",
     "Two consecutive quarters with NRR < {threshold}%"),
    # Customer & demand
    (r"\b(customer|logo|lock.?in|stickiness)\b",
     "Top-{N} customer concentration > {threshold}% disclosed in 10-K"),
    (r"\b(churn|retention)\b",
     "Annualised churn > {threshold}% disclosed in any quarter"),
    # Competition & moat
    (r"\b(moat|defensibility|competitive)\b",
     "Independent third-party benchmark shows performance gap closing to ≤{threshold}%"),
    (r"\b(switching cost)\b",
     "Public migration case study shows switching completed in < {N} months"),
    # Industry & cycle
    (r"\b(capex|capital expenditure|hyperscaler)\b",
     "{Top-3 hyperscaler} capex guidance cut > {threshold}% YoY in any single quarter"),
    (r"\b(inventory|days sales|dsi)\b",
     "Industry-wide DSI > {threshold} days for {N} consecutive quarters"),
    (r"\b(cycle|cyclical|trough|peak)\b",
     "Sector-level lead indicator (PMI/orders) below {threshold} for {N} months"),
    # Regulatory / legal
    (r"\b(regul|antitrust|export control|tariff|FDA|EMA)\b",
     "{Regulator} formal action: enforcement order / consent decree / export ban"),
    (r"\b(litigation|lawsuit|patent)\b",
     "Adverse ruling in {Court} with damages > ${threshold}M"),
    # Disclosures
    (r"\b(disclos|guidance|analyst day|capital markets day)\b",
     "FY{year} {H1|Q1|earnings} call: management does NOT separately quantify {metric}"),
    # Product & adoption
    (r"\b(adoption|penetration|rollout)\b",
     "Adoption rate < {threshold}% disclosed at FY{year} earnings"),
    (r"\b(software|api|developer)\b",
     "Active developer count below {threshold} disclosed at FY{year} dev day"),
    # Valuation transition
    (r"\b(re.?rate|multiple expansion|valuation framework|peer)\b",
     "Sell-side coverage migrates back to {old framework} multiple band"),
]


def suggest(hypothesis_full: str, leaf_id: str = "") -> list[dict]:
    """Return up to 3 candidate falsification suggestions, each as a typed
    Falsification object compatible with the drawtree v0.2 schema.
    """
    text = (hypothesis_full or "").lower()
    suggestions: list[dict] = []

    for pat, template in KEYWORD_METRICS:
        if re.search(pat, text):
            suggestions.append({
                "text": template,
                "type": "observable",
                "match_reason": f"keyword pattern: {pat}",
            })
        if len(suggestions) >= 3:
            break

    # If no keyword match, return a generic disclosure-trigger fallback that the
    # user's Claude will refine.
    if not suggestions:
        suggestions.append({
            "text": "FY{year} {H1|Q1} earnings: management does NOT confirm "
                    "the core mechanism stated in this hypothesis",
            "type": "observable",
            "match_reason": "fallback — no keyword pattern matched",
        })

    return suggestions[:3]


def is_falsification_observable(falsification) -> bool:
    """Accept either a string (legacy) or a Falsification object."""
    if isinstance(falsification, dict):
        return is_observable(falsification.get("text", ""))
    return is_observable(str(falsification))
