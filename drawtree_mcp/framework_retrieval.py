"""BM25-lite retrieval over the 164-framework KB index.

Pure keyword scoring (idf-weighted token overlap). No LLM, no embeddings —
fast, deterministic, ships with zero external dependencies.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable

KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "frameworks.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "for", "is", "be",
    "are", "was", "were", "by", "with", "as", "at", "this", "that", "it",
    "from", "into", "on", "but", "if", "than", "such", "their", "they",
    "have", "has", "had", "will", "would", "should", "could", "may",
    "can", "do", "does", "did", "what", "who", "how", "why",
}


def tokenise(s: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(s.lower()) if t not in _STOP and len(t) > 2]


def load_kb() -> dict:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def _build_doc_tokens(framework: dict) -> list[str]:
    """Tokens that represent this framework for retrieval."""
    parts = [
        framework.get("name", ""),
        framework.get("category", ""),
        framework.get("leaf_affinity") or "",
    ]
    parts.extend(framework.get("tags", []))
    text = " ".join(parts)
    return tokenise(text)


def search(query: str, top_k: int = 3) -> list[dict]:
    """Return top-k frameworks most relevant to a free-text query.

    Returns each framework with a `score` field and a `relevance_reason` —
    the latter explains *why* it matched, surfacing the matching tokens so the
    user's Claude can show provenance.
    """
    kb = load_kb()
    frameworks = kb["frameworks"]
    if not query.strip():
        return []

    query_tokens = tokenise(query)
    if not query_tokens:
        return []

    # Build a tiny in-memory index
    docs: list[tuple[str, list[str]]] = [
        (name, _build_doc_tokens(fw)) for name, fw in frameworks.items()
    ]

    # IDF
    n_docs = len(docs)
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n_docs + 1) / (df_val + 0.5) + 1) for t, df_val in df.items()}

    # Score each doc
    scored: list[tuple[float, str, list[str]]] = []
    for name, toks in docs:
        token_set = set(toks)
        matched = [q for q in query_tokens if q in token_set]
        if not matched:
            continue
        # Boost: match against framework name itself counts double
        name_tokens = set(tokenise(name))
        name_matches = [q for q in query_tokens if q in name_tokens]
        s = sum(idf.get(q, 0.5) for q in matched) + 1.5 * sum(
            idf.get(q, 0.5) for q in name_matches
        )
        scored.append((s, name, matched))

    scored.sort(key=lambda x: -x[0])
    out = []
    for s, name, matched in scored[:top_k]:
        fw = dict(frameworks[name])
        fw["score"] = round(s, 3)
        fw["relevance_reason"] = (
            f"matched tokens: {', '.join(matched[:6])}" if matched else "category match"
        )
        out.append(fw)
    return out


def search_for_branch(branch_label: str, branch_question: str, top_k: int = 3) -> list[dict]:
    """Targeted search for a specific branch in a hypothesis tree."""
    return search(f"{branch_label} {branch_question}", top_k=top_k)


def diagnostic_questions(framework_name: str) -> list[str]:
    """Hand-curated diagnostic questions for the most useful frameworks.

    For frameworks not listed, returns a generic structural question.
    """
    return DIAGNOSTIC_QUESTIONS.get(framework_name, [
        f"What does {framework_name} predict about this company?",
        f"Which observation would falsify {framework_name}'s prediction here?",
    ])


# Curated leaf-seed questions for the most-used frameworks.
# These become "candidate sub-hypotheses" when enrich_branches runs.
DIAGNOSTIC_QUESTIONS: dict[str, list[str]] = {
    "Porter's Five Forces": [
        "Is rivalry intensity increasing or decreasing in this industry?",
        "Are switching costs structurally rising or falling?",
        "Is supplier concentration giving suppliers pricing power?",
        "Are buyers consolidating fast enough to compress margin?",
        "Is the threat of substitutes accelerating?",
    ],
    "VRIO / VRIN Analysis": [
        "Is the resource Valuable in the customer's eyes?",
        "Is it Rare among competitors?",
        "Is it Inimitable on a 3-5 year horizon?",
        "Is the Organization able to capture the value?",
    ],
    "Strategic Group Mapping": [
        "What strategic group is the company currently in?",
        "Is the company drifting between groups?",
        "Are barriers between groups rising or falling?",
        "Which group's multiple ceiling is the company being priced at?",
    ],
    "Industry Life Cycle Model": [
        "What stage is the industry in (introduction / growth / maturity / decline)?",
        "How many quarters until the next stage transition?",
        "Are leading indicators of stage change visible yet?",
    ],
    "S-Curve of Industry / Technology Evolution": [
        "Where is the focal technology on its S-curve?",
        "Is the next S-curve visible? When does it inflect?",
        "Is the company on the dominant S-curve or a side branch?",
    ],
    "Strategic Inflection Point Framework": [
        "Has 10x change occurred in any single force?",
        "Is the existing strategic posture still rational post-inflection?",
        "What is the catalyst that turns possibility into actuality?",
    ],
    "Disruptive Innovation Theory": [
        "Is a low-end disruptor entering the market?",
        "Is a new-market disruptor creating new consumption?",
        "Is the company's innovation sustaining or disruptive in this case?",
    ],
    "Network Effects Map": [
        "Is the network exhibiting same-side or cross-side effects?",
        "Is liquidity above the critical mass threshold?",
        "Are diseconomies of scale (congestion, regulation) materialising?",
    ],
    "Customer Lifetime Value Model": [
        "Is LTV/CAC trending above or below 3x?",
        "Are payback periods compressing or extending?",
        "Is gross retention (logo) holding above 90%?",
        "Is net revenue retention above 110%?",
    ],
    "Net Promoter System": [
        "Is NPS rising or falling YoY?",
        "Are detractor reasons concentrated in fixable areas?",
    ],
    "Capital Allocation Framework": [
        "What % of FCF is going to buybacks vs dividends vs M&A vs reinvestment?",
        "Is the marginal ROIC trending above or below WACC?",
        "Are buybacks executed at multiples below intrinsic value?",
    ],
    "McKinsey Three Horizons of Growth": [
        "What % of revenue is from H1 (mature core)?",
        "Is H2 (emerging) revenue compounding above 30% YoY?",
        "Are H3 (incubation) bets resourced and timed coherently?",
    ],
    "Real Options Valuation": [
        "Which option-like investments has the company embedded?",
        "What's the implied volatility on the underlying option?",
        "Is the option being exercised, abandoned, or extended?",
    ],
    "Scenario Planning": [
        "What are the 2-4 plausible scenarios over the planning horizon?",
        "What signposts trigger a transition between scenarios?",
        "Which scenario is the market currently pricing?",
    ],
    "Brand Equity Pyramid": [
        "Is brand salience top-of-mind in the target segment?",
        "Are brand judgments improving on quality / credibility / consideration?",
        "Is brand resonance translating into pricing power?",
    ],
    "Two-sided Platform Business Model": [
        "Which side has the harder activation problem?",
        "Are cross-side network effects strengthening?",
        "Is the take rate sustainable vs disintermediation risk?",
    ],
    "AI Value Creation Framework": [
        "Where in the AI stack does the company sit (infra / model / app)?",
        "Is the company positioned to capture or be commoditised?",
        "Does the AI advantage compound or decay?",
    ],
    "Product-Led Growth Framework": [
        "Is the product self-serve adoptable by an individual user?",
        "Is the activation funnel converting above 25%?",
        "Is the expansion motion (seat / usage) outpacing churn?",
    ],
}
