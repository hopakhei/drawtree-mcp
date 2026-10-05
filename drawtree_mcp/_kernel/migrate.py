"""Migrate a Draw Tree v0.2 document to protocol v0.3.

Mechanical only — nothing is invented. Fields that v0.3 requires but v0.2 never
held (scenario roles, necessary conditions, frameworks, reading guides, numeric
condition metrics) are listed in the returned `todo` so the author or the AI
client can fill them before `validate_tree` passes.

Mapping:
  branches   weight → impact_grade via the legacy map {8:致命,5:重創,3:明顯受損,2:輕微,1:邊緣}
             (reversed-Fibonacci positions when no explicit weight); weight re-set to the
             grade's log-odds unit; `aggregation: portfolio`.
  leaves     falsification[] → conditions[] (kind falsification, metric null, status open);
             condition_assessments[] seeded `not_met`; recent_evidence[] → evidence_ledger[]
             (tier news, impact neutral, eid E001…); multi-parent leaves keep the first parent;
             leaf_nature text; short_question from title when it already is a ≤22-char question.
"""
from __future__ import annotations

import copy
import re

from . import protocol as P
from .aggregation import fibonacci_weights, hyps_list

_OBS = [re.compile(p) for p in (r"[<>≤≥]\s*-?\d", r"\d+\s*%", r"\$\s*\d", r"\d{4}-\d{2}(-\d{2})?",
                                 r"Q[1-4]\s*FY?\d{2,4}", r"FY\s*\d{2,4}")]


def migrate_v02_to_v03(doc_in: dict) -> tuple[dict, dict]:
    doc = copy.deepcopy(doc_in)
    report = {"changed": [], "todo": [], "from_version": doc.get("drawtree_version")}
    doc["_migrated_from"] = doc.get("drawtree_version", "0.2")
    doc["drawtree_version"] = P.PROTOCOL_VERSION

    branches = [b for b in (doc.get("branches") or []) if isinstance(b, dict)]
    fib = fibonacci_weights(len(branches))
    for i, b in enumerate(branches):
        bid = b.get("id", "?")
        if b.get("impact_grade") in P.IMPACT_GRADES:
            grade = b["impact_grade"]
        else:
            w = b.get("weight", fib[i] if i < len(fib) else 1.0)
            grade = P.grade_for_legacy_weight(w) or ("致命" if i == 0 else "重創" if i == 1 else "明顯受損" if i == 2 else "輕微")
            b["impact_grade"] = grade
            b["weight_rationale"] = (f"{P.WEIGHT_RATIONALE_PREFIX}由 v0.2 權重 {w} 映射為 {grade}（遷移；須以價格後果重定）")
            report["changed"].append(f"branch {bid}: weight {w} → impact_grade {grade}")
            report["todo"].append(f"branch {bid}: derive impact_grade from the falsification consequence's price impact and set falsification_consequence")
        b["weight"] = P.IMPACT_GRADES[grade]
        if str(b.get("aggregation", "portfolio")).lower() != "portfolio":
            report["changed"].append(f"branch {bid}: aggregation {b.get('aggregation')} → portfolio")
        b["aggregation"] = "portfolio"
        for k in ("scenario_role", "necessary_condition", "falsification_rule", "framework"):
            if not b.get(k):
                report["todo"].append(f"branch {bid}: missing {k}")

    leaves = hyps_list(doc)
    for h in leaves:
        hid = h.get("id", "?")
        parents = h.get("parents") or []
        if len(parents) > 1:
            h["parents"] = [parents[0]]
            report["changed"].append(f"leaf {hid}: multi-parent {parents} → {parents[0]} (v0.3 is single-parent)")
        if not isinstance(h.get("conditions"), list) or not h["conditions"]:
            conds = []
            for n, f in enumerate(h.get("falsification") or [], 1):
                text = (f.get("text") if isinstance(f, dict) else str(f)).strip()
                if not text:
                    continue
                conds.append({"cid": f"{hid}-F{n}", "kind": "falsification", "text": text, "metric": None,
                              "operator": None, "threshold": None, "unit": None, "window": None, "status": "open",
                              "observable_hint": any(p.search(text) for p in _OBS)})
            h["conditions"] = conds
            report["changed"].append(f"leaf {hid}: {len(conds)} falsification text(s) → conditions[] (metric null)")
            report["todo"].append(f"leaf {hid}: give each condition a metric / operator / threshold / window where a disclosed number exists")
        if not h.get("condition_assessments"):
            h["condition_assessments"] = [{"cid": c["cid"], "assessment": "not_met",
                                           "reason": "migrated from v0.2: no assessment on record"} for c in h["conditions"]]
        if not h.get("evidence_ledger"):
            rows = []
            for n, e in enumerate(h.get("recent_evidence") or [], 1):
                if not isinstance(e, dict):
                    continue
                text = str(e.get("text") or "")
                rows.append({"eid": f"E{n:03d}", "date": e.get("date"), "text": text, "source_name": e.get("source_name"),
                             "url": e.get("url") or "", "tier": "news", "impact": "neutral", "bears_on": [], "digest": text[:80]})
            h["evidence_ledger"] = rows
            if rows:
                report["changed"].append(f"leaf {hid}: {len(rows)} recent_evidence → evidence_ledger (tier news, impact neutral)")
                report["todo"].append(f"leaf {hid}: set tier and impact on each migrated ledger row")
        h.setdefault("leaf_nature", "text")
        title = str(h.get("title") or "").strip()
        if not h.get("short_question"):
            if title.endswith(("？", "?")) and len(title) <= P.SHORT_QUESTION_MAX:
                h["short_question"] = title
            else:
                report["todo"].append(f"leaf {hid}: write short_question (≤{P.SHORT_QUESTION_MAX} chars, a question)")
        if not h.get("reading_guide"):
            report["todo"].append(f"leaf {hid}: write reading_guide (one sentence per level: {' / '.join(P.SIX_LEVELS)})")
        if not h.get("scenario_role"):
            report["todo"].append(f"leaf {hid}: set scenario_role ({' / '.join(P.LEAF_ROLES)})")
        if h.get("verdict") in P.VERDICT_LEGACY:
            m = {"supported": "Validated", "partially_supported": "Inconclusive", "challenged": "Approaching falsification"}
            report["changed"].append(f"leaf {hid}: verdict {h['verdict']} → {m[h['verdict']]}")
            h["verdict"] = m[h["verdict"]]
    if isinstance(doc.get("hypotheses"), dict):
        doc["hypotheses"] = leaves
    else:
        doc["hypotheses"] = leaves
    return doc, report
