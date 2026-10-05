"""Post-judgement gate for a proposed verdict change (fleet rules 1, 1b, 1c, 1d, 2, 3).

A change is a dict:
  {hypothesis_id, new_verdict, reason, cited_evidence_urls[], driver_eids[],
   falsification_basis, judged_offline?: bool}
`week_evidence` is this week's evidence rows for the leaf
  [{url, eid?, tier?, impact?, text?}]
`leaf` is the v0.3 leaf (for `evidence_ledger`, `falsification[]`, `conditions[]`).

Returns {"ok": bool, "dropped_reason": str | None, "provenance": str, "fresh_urls": [...]}.
Rules (dropping):
  1   must cite ≥1 URL present in this week's evidence (exempt: a cited driver eid is a
      synthetic latch row, or judged_offline=True — the exemption is recorded);
  1b  at least one cited row must be verifiable (has a URL or is synthetic);
  1c  every cited eid must exist in the ledger or this week's rows;
  1d  cited rows all `challenges` yet verdict upgraded (or all `supports` yet downgraded) → drop;
  2   a falsification-zone verdict must quote a real falsification condition
      (substring / 6-char overlap with `falsification[]` texts or `conditions[].text`);
  3   the reason may not be price-only (price keywords without an operational keyword).
Provenance (never drops): new_evidence | stale_reread | expiry | none.
"""
from __future__ import annotations

from . import protocol as P

UP = {"Validated", "Trending positive"}
DOWN = {"Falsified", "Approaching falsification", "Trending negative"}

PRICE_ONLY_KEYWORDS = ["股價", "股价", "上漲", "下跌", "52週", "52 週", "52-week", "market cap", "市值",
                       "share price", "stock price", "漲幅", "跌幅"]
OPERATIONAL_KEYWORDS = ["PPA", "合約", "合约", "contract", "agreement", "earnings", "財報", "guidance", "指引",
                        "FERC", "NRC", "PJM", "MW", "GW", "capex", "資本支出", "regulator", "監管", "approval", "批准",
                        "acquisition", "並購", "收購", "merger", "backlog", "order", "訂單", "shipment", "出貨",
                        "plant", "工廠", "capacity", "產能", "裁定", "裁決", "訴訟", "lawsuit", "settlement", "PTC", "IRA",
                        "financial", "revenue", "營收", "margin", "毛利", "EBITDA", "現金", "cash", "debt", "負債",
                        "credit rating", "信用評級"]


def _overlap_ok(citation: str, items: list[str]) -> bool:
    c = (citation or "").strip()
    if len(c) < 6:
        return False
    for f in items:
        f = (f or "").strip()
        if not f:
            continue
        if c in f or f in c:
            return True
        for i in range(0, max(1, len(c) - 5)):
            if c[i:i + 6] in f:
                return True
    return False


def validate_verdict_change(leaf: dict, change: dict, week_evidence: list[dict]) -> dict:
    ledger = [e for e in (leaf.get("evidence_ledger") or []) if isinstance(e, dict)]
    week = [e for e in (week_evidence or []) if isinstance(e, dict)]
    new_verdict = str(change.get("new_verdict") or "")
    reason = str(change.get("reason") or "")
    cited = {str(u) for u in (change.get("cited_evidence_urls") or []) if u}
    eids = [str(x).strip() for x in (change.get("driver_eids") or []) if str(x).strip()]
    week_urls = {str(e.get("url")) for e in week if e.get("url")}
    out = {"ok": True, "dropped_reason": None, "provenance": "none", "fresh_urls": [], "exemptions": []}

    def drop(code: str) -> dict:
        out.update(ok=False, dropped_reason=code)
        return out

    rows_by_eid = {str(e.get("eid")): e for e in ledger if e.get("eid")}
    for e in week:
        if e.get("eid"):
            rows_by_eid.setdefault(str(e["eid"]), e)

    # Rule 1
    if not (cited & week_urls):
        url_in_reason = any(u in reason for u in week_urls)
        drove_synthetic = any(str(rows_by_eid.get(e, {}).get("tier") or "") == "synthetic" for e in eids)
        if not url_in_reason and not drove_synthetic:
            if change.get("judged_offline"):
                out["exemptions"].append("rule_1:judged_offline")
            else:
                return drop("rule_1_no_evidence_url_cited")
    # Rule 1b
    by_url = {str(e.get("url") or "").strip(): e for e in week + ledger}
    cited_rows = [by_url[u] for u in cited if u in by_url]
    if cited_rows and not any(str(r.get("url") or "").strip() or str(r.get("tier") or "") == "synthetic" for r in cited_rows):
        return drop("rule_1b_cited_evidence_unverifiable")
    # Rule 1c
    ghost = [e for e in eids if e not in rows_by_eid]
    if ghost:
        return drop("rule_1c_unknown_eid:" + ",".join(ghost[:3]))
    # Rule 1d
    if eids:
        imp = [P.EVIDENCE_IMPACT_LEGACY.get(str(rows_by_eid[e].get("impact") or ""), str(rows_by_eid[e].get("impact") or ""))
               for e in eids if e in rows_by_eid]
        if imp:
            if new_verdict in UP and all(x == "challenges" for x in imp):
                return drop("rule_1d_cited_evidence_all_challenges_but_upgraded")
            if new_verdict in DOWN and all(x == "supports" for x in imp):
                return drop("rule_1d_cited_evidence_all_supports_but_downgraded")
    # Rule 2
    if new_verdict in P.FALSIFICATION_VERDICTS:
        basis = str(change.get("falsification_basis") or "").strip()
        if not basis:
            return drop("rule_2_falsification_verdict_without_basis")
        items = [str(f.get("text") if isinstance(f, dict) else f) for f in (leaf.get("falsification") or [])]
        items += [str(c.get("text") or "") for c in (leaf.get("conditions") or []) if isinstance(c, dict)
                  and c.get("kind") in ("falsification", "deadline")]
        if not _overlap_ok(basis, items):
            return drop("rule_2_falsification_citation_does_not_match_any_listed_condition")
    # Rule 3
    if any(k in reason for k in PRICE_ONLY_KEYWORDS) and not any(k in reason for k in OPERATIONAL_KEYWORDS):
        return drop("rule_3_price_only_reason")
    # Provenance
    prior_urls = {str(e.get("url")) for e in ledger if e.get("url")}
    matched = [u for u in cited if u in week_urls] or list(cited)
    fresh = [u for u in matched if u not in prior_urls]
    syn = [e for e in week if e.get("tier") == "synthetic" and str(e.get("url", "")) in cited]
    out["provenance"] = "expiry" if (syn and not fresh) else "new_evidence" if fresh else "stale_reread" if matched else "none"
    out["fresh_urls"] = fresh[:6]
    return out
