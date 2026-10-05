"""Deterministic condition sweep (protocol §8 breach latch) — zero model calls.

Run before any re-judgement. For every leaf with structured `conditions[]`:
  * an open `deadline` (or metric-less) condition whose `due` is past becomes
    `expired_unfulfilled` — the absence of a promised event is evidence;
  * an open scalar `falsification` condition (metric + scalar operator +
    threshold) whose matching `observations[]` entry crosses the threshold
    becomes `breached`, with a permanent `breach{value, date, eid}` latch.
Either transition appends a synthetic ledger row (`tier: synthetic`,
`impact: challenges`, `eid: SYN-<cid>-<date>`) so the next judgement must
weigh it. Idempotent; the latch never ages out.
"""
from __future__ import annotations

from datetime import date
from . import protocol as P
from .aggregation import hyps_list


def _cmp_scalar(value, op: str, threshold) -> bool | None:
    try:
        v, t = float(value), float(threshold)
    except (TypeError, ValueError):
        return None
    return {"<": v < t, "<=": v <= t, ">": v > t, ">=": v >= t, "==": v == t}.get(op)


def _inject(leaf: dict, text: str, cid: str, source: str, today: str) -> str:
    eid = f"SYN-{cid}-{today}"
    ledger = leaf.setdefault("evidence_ledger", [])
    if not any(isinstance(e, dict) and e.get("eid") == eid for e in ledger):
        ledger.append({"eid": eid, "date": today, "text": text, "source_name": source, "url": "",
                       "tier": "synthetic", "impact": "challenges", "bears_on": [cid], "digest": text[:80]})
    return eid


def sweep_conditions(doc: dict, today: str | None = None) -> dict:
    """Mutates `doc` in place. Returns {"breached": [...], "expired": [...], "today": str}."""
    today = today or date.today().isoformat()
    breached: list[dict] = []
    expired: list[dict] = []
    for leaf in hyps_list(doc):
        conds = leaf.get("conditions")
        if not isinstance(conds, list):
            continue
        hid = leaf.get("id", "?")
        obs_by_metric: dict[str, list[dict]] = {}
        for ob in leaf.get("observations") or []:
            if isinstance(ob, dict) and ob.get("metric"):
                obs_by_metric.setdefault(str(ob["metric"]), []).append(ob)
        for c in conds:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("cid", ""))
            st = c.get("status", "open")
            kind = c.get("kind", "falsification")
            due = str(c.get("due") or "")
            if st == "open" and due and due < today and (kind == "deadline" or c.get("metric") is None):
                c["status"] = "expired_unfulfilled"
                c["expired_on"] = today
                basis = c.get("basis")
                if isinstance(basis, dict):
                    prov = f"deadline basis: {str(basis.get('text') or '')[:120]}" + (f" <{basis.get('url')}>" if basis.get("url") else "")
                elif basis:
                    prov = f"deadline basis: {str(basis)[:150]}"
                else:
                    prov = "deadline basis: review window set at tree setup (not a management or regulatory timetable)"
                _inject(leaf, f"Pre-registered deadline passed unfulfilled (absence is evidence): {c.get('text', '')} "
                              f"(due {due}, swept {today}; {prov})", cid, "deadline_clock", today)
                expired.append({"id": hid, "cid": cid, "due": due, "has_basis": bool(basis)})
                continue
            if st != "open" or kind != "falsification":
                continue
            op, thr, metric, win = c.get("operator"), c.get("threshold"), c.get("metric"), c.get("window")
            if not (metric and op in P.SCALAR_OPERATORS and thr is not None):
                continue
            cands = obs_by_metric.get(str(metric), [])
            if win is not None:
                cands = [o for o in cands if str(o.get("window", "")) == str(win)]
            hit = next((o for o in cands if _cmp_scalar(o.get("value"), op, thr)), None)
            if hit is not None:
                eid = hit.get("eid") or _inject(
                    leaf, f"Observed {metric}={hit.get('value')} in {win or hit.get('date')} crossed the falsification "
                          f"threshold {op}{thr} — condition breached", cid, "breach_latch", today)
                c["status"] = "breached"
                c["breach"] = {"value": hit.get("value"), "date": hit.get("date", today), "eid": eid}
                breached.append({"id": hid, "cid": cid, "metric": metric, "value": hit.get("value"), "op": op, "threshold": thr})
    return {"today": today, "breached": breached, "expired": expired}
