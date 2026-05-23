"""Framework name + category lookup ONLY.

This is the FREE retrieval surface. It returns just the framework name and
its category — enough for a user's Claude (with its own framework knowledge)
to recognise the framework, but nothing that exposes proprietary leaf-affinity
mapping or curated diagnostic questions.

Deep framework retrieval — including diagnostic question seeds and per-leaf
metric heuristics — happens server-side via the paid `enrich_branches`
endpoint on drawtree-api.
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


def _doc_tokens(framework: dict) -> list[str]:
    """Tokens that represent this framework for retrieval — name + category only.
    Tags are still used for matching but not surfaced.
    """
    parts = [
        framework.get("name", ""),
        framework.get("category", ""),
    ]
    parts.extend(framework.get("tags", []))
    return tokenise(" ".join(parts))


def search(query: str, top_k: int = 3) -> list[dict]:
    """Return top-k framework names + categories for a free-text query.

    No leaf-affinity, no diagnostic questions, no provenance — those live
    behind the paid `enrich_branches` endpoint on drawtree-api.
    """
    kb = load_kb()
    frameworks = kb["frameworks"]
    if not query.strip():
        return []
    query_tokens = tokenise(query)
    if not query_tokens:
        return []

    docs = [(name, _doc_tokens(fw)) for name, fw in frameworks.items()]
    n_docs = len(docs)
    df: dict[str, int] = {}
    for _, toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n_docs + 1) / (df_val + 0.5) + 1) for t, df_val in df.items()}

    scored: list[tuple[float, str]] = []
    for name, toks in docs:
        token_set = set(toks)
        matched = [q for q in query_tokens if q in token_set]
        if not matched:
            continue
        name_tokens = set(tokenise(name))
        name_matches = [q for q in query_tokens if q in name_tokens]
        s = sum(idf.get(q, 0.5) for q in matched) + 1.5 * sum(
            idf.get(q, 0.5) for q in name_matches
        )
        scored.append((s, name))

    scored.sort(key=lambda x: -x[0])
    out = []
    for s, name in scored[:top_k]:
        fw = frameworks[name]
        out.append({
            "name": name,
            "category": fw["category"],
            "score": round(s, 3),
        })
    return out
