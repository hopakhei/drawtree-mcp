#!/usr/bin/env python3
"""Draw Tree v0.2 reference validator.

Adds to v0.1:
  - Branch regex relaxed to ^[A-Z]$
  - Hypothesis regex relaxed to ^[A-Z][1-9][0-9]*$
  - Falsification typed objects {observable, directional, mechanism}
  - Multi-parent leaves via explicit parents[]
  - Weight bounds [0.1, 10.0]
  - ISO 8601 tracking_events.time
  - narrative_versions mandatory (current + next_candidate)
  - Aggregation block validation (numeric scoring, valid thresholds)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from .aggregation import aggregate  # noqa: E402


HYP_ID_RE = re.compile(r"^[A-Z][1-9][0-9]*$")
BRANCH_ID_RE = re.compile(r"^[A-Z]$")
ROOT_ID = "H0"
ISO8601_TIME_RE = re.compile(r"^\d{4}(-(\d{2}|Q[1-4])(-\d{2})?)?$")

VERDICT_NEW = {
    "Validated", "Trending positive", "Inconclusive",
    "Trending negative", "Approaching falsification", "Falsified",
}
VERDICT_LEGACY = {"supported", "partially_supported", "challenged"}
VERDICT_STRUCTURAL = {"pending"}
VERDICT_ALL = VERDICT_NEW | VERDICT_LEGACY | VERDICT_STRUCTURAL

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
    re.compile(r"[A-Z][a-z]+\s+[A-Z][a-z]+"),
]


@dataclass
class Issue:
    severity: str
    code: str
    path: str
    message: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, code: str, path: str, message: str):
        self.issues.append(Issue(severity, code, path, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]


def is_observable(s: str) -> bool:
    return any(pat.search(s) for pat in OBSERVABILITY_PATTERNS)


def has_source_refs(ev: dict) -> tuple[bool, str]:
    date = (ev.get("date") or "").strip()
    if not date:
        return False, "date is empty"
    src = (ev.get("source_name") or "").strip()
    url = (ev.get("url") or "").strip()
    if not src and not url:
        return False, "neither source_name nor url provided"
    return True, ""


def normalise_falsification(f) -> dict:
    """Accept string or object form. Return canonical {text, type}."""
    if isinstance(f, str):
        text = f.strip()
        return {"text": text, "type": "observable" if is_observable(text) else "directional"}
    if isinstance(f, dict):
        text = (f.get("text") or "").strip()
        ftype = f.get("type")
        if not ftype:
            ftype = "observable" if is_observable(text) else "directional"
        return {"text": text, "type": ftype, **{k: v for k, v in f.items() if k not in {"text", "type"}}}
    return {"text": "", "type": "directional"}


def check_weight(value, path: str, rep: Report):
    if value is None:
        return
    try:
        w = float(value)
    except (TypeError, ValueError):
        rep.add("error", "WEIGHT_TYPE", path, f"weight must be numeric, got {value!r}")
        return
    if w < 0.1 or w > 10.0:
        rep.add("error", "WEIGHT_RANGE", path, f"weight {w} outside [0.1, 10.0]")


def check_root(root: dict, consensus: dict, rep: Report):
    if not (root.get("question") or "").strip():
        rep.add("error", "ROOT_QUESTION_EMPTY", "root.question", "root.question is empty")
    if not (root.get("core_thesis") or "").strip():
        rep.add("error", "ROOT_THESIS_EMPTY", "root.core_thesis", "root.core_thesis is empty")
    if root.get("verdict") not in VERDICT_ALL:
        rep.add("error", "ROOT_VERDICT_VOCAB", "root.verdict",
                f"root.verdict {root.get('verdict')!r} not in closed vocabulary")
    if not (consensus.get("narrative") or "").strip():
        rep.add("error", "CONSENSUS_NARRATIVE_EMPTY", "consensus.narrative",
                "consensus.narrative is empty (frozen baseline missing)")
    if not (consensus.get("implicit_assumptions") or []):
        rep.add("error", "CONSENSUS_ASSUMPTIONS_EMPTY", "consensus.implicit_assumptions",
                "consensus.implicit_assumptions is empty")
    if not (consensus.get("pricing_logic") or "").strip():
        rep.add("error", "CONSENSUS_PRICING_EMPTY", "consensus.pricing_logic",
                "consensus.pricing_logic is empty")

    nv = (root.get("narrative_versions") or {})
    if not nv:
        rep.add("error", "NARRATIVE_VERSIONS_MISSING", "root.narrative_versions",
                "v0.2 requires narrative_versions on every tree (decision 5)")
    else:
        versions = nv.get("versions") or []
        statuses = {v.get("status") for v in versions if isinstance(v, dict)}
        if "current" not in statuses:
            rep.add("error", "NARRATIVE_NO_CURRENT", "root.narrative_versions.versions",
                    "no version with status: current")
        if "next_candidate" not in statuses:
            rep.add("error", "NARRATIVE_NO_NEXT", "root.narrative_versions.versions",
                    "no version with status: next_candidate")
        cur = nv.get("current_version_id")
        nc = nv.get("next_candidate_id")
        ids = {v.get("id") for v in versions if isinstance(v, dict)}
        if cur and cur not in ids:
            rep.add("error", "NARRATIVE_CUR_REF", "root.narrative_versions.current_version_id",
                    f"current_version_id {cur!r} not in versions[]")
        if nc and nc not in ids:
            rep.add("error", "NARRATIVE_NC_REF", "root.narrative_versions.next_candidate_id",
                    f"next_candidate_id {nc!r} not in versions[]")


def check_decomposition(root: dict, branches: list[dict], hypotheses: list[dict], rep: Report):
    if (root or {}).get("id") != ROOT_ID:
        rep.add("error", "ROOT_ID", "root.id",
                f"root id must be {ROOT_ID!r}, got {root.get('id')!r}")
    branch_ids: set[str] = set()
    for i, b in enumerate(branches):
        bid = b.get("id", "")
        if not BRANCH_ID_RE.match(bid):
            rep.add("error", "BRANCH_ID", f"branches[{i}].id",
                    f"branch id {bid!r} does not match ^[A-Z]$")
        else:
            if bid in branch_ids:
                rep.add("error", "BRANCH_DUP", f"branches[{i}].id",
                        f"duplicate branch id {bid!r}")
            branch_ids.add(bid)
        if not (b.get("label") or "").strip():
            rep.add("error", "BRANCH_LABEL", f"branches[{i}]", "branch.label is empty")
        if not (b.get("core_question") or "").strip():
            rep.add("error", "BRANCH_QUESTION", f"branches[{i}]", "branch.core_question is empty")
        check_weight(b.get("weight"), f"branches[{i}].weight", rep)

    if len(branch_ids) < 3:
        rep.add("warning", "BRANCH_COUNT", "branches",
                f"only {len(branch_ids)} branch(es); MECE rule recommends ≥3")
    if "weight" not in (branches[0] if branches else {}):
        rep.add("warning", "WEIGHT_DEFAULT", "branches[*].weight",
                "no explicit branch weights; using default Fibonacci sequence")

    seen_hyp: set[str] = set()
    for h in hypotheses:
        hid = h.get("id", "")
        if not HYP_ID_RE.match(hid):
            rep.add("error", "HYP_ID", f"hypotheses[{hid}].id",
                    f"hypothesis id {hid!r} does not match ^[A-Z][1-9][0-9]*$")
            continue
        if hid in seen_hyp:
            rep.add("error", "HYP_DUP", f"hypotheses[{hid}].id",
                    f"duplicate hypothesis id {hid!r}")
        seen_hyp.add(hid)

        # parents[]: default = [hid[0]]; explicit overrides
        parents = h.get("parents") or [hid[0]]
        for p in parents:
            if p not in branch_ids:
                rep.add("error", "PARENT_MISSING", f"hypotheses[{hid}].parents",
                        f"parent branch {p!r} not in branches.yaml")
        # parent_weights consistency
        pw = h.get("parent_weights") or {}
        if pw and len(parents) <= 1:
            rep.add("warning", "PARENT_WEIGHTS_UNUSED", f"hypotheses[{hid}].parent_weights",
                    "parent_weights set on a single-parent leaf is harmless but unnecessary")
        for k, v in pw.items():
            if k not in parents:
                rep.add("error", "PARENT_WEIGHTS_KEY", f"hypotheses[{hid}].parent_weights",
                        f"parent_weights key {k!r} not in parents[]")
            check_weight(v, f"hypotheses[{hid}].parent_weights[{k}]", rep)
        check_weight(h.get("weight"), f"hypotheses[{hid}].weight", rep)


def check_leaves(hypotheses: list[dict], rep: Report):
    for h in hypotheses:
        hid = h.get("id", "?")
        path = f"hypotheses[{hid}]"

        falsif = h.get("falsification") or []
        if not falsif:
            rep.add("error", "FALSIF_MISSING", path,
                    "leaf has zero falsification entries — every leaf MUST have ≥1 kill condition")

        observable_count = 0
        for j, f in enumerate(falsif):
            normf = normalise_falsification(f)
            text = normf.get("text", "")
            ftype = normf.get("type", "directional")
            if not text:
                rep.add("error", "FALSIF_EMPTY", f"{path}.falsification[{j}]",
                        "empty falsification text")
                continue
            if ftype not in {"observable", "directional", "mechanism"}:
                rep.add("error", "FALSIF_TYPE", f"{path}.falsification[{j}].type",
                        f"unknown type {ftype!r}")
                continue
            if ftype == "observable":
                observable_count += 1
                if not is_observable(text):
                    rep.add("error", "FALSIF_UNOBSERVABLE", f"{path}.falsification[{j}]",
                            f"declared observable but no number/date/proper-noun trigger: {text[:80]!r}")
            elif ftype == "directional":
                rep.add("warning", "FALSIF_DIRECTIONAL", f"{path}.falsification[{j}]",
                        f"directional kill condition (no tripwire): {text[:80]!r}")
            elif ftype == "mechanism":
                rep.add("warning", "FALSIF_MECHANISM", f"{path}.falsification[{j}]",
                        f"mechanism kill condition (structural-cause): {text[:80]!r}")

        if falsif and observable_count == 0:
            rep.add("warning", "FALSIF_NO_OBSERVABLE", path,
                    "leaf has no observable falsification — kill switches cannot fire automatically")

        verdict = h.get("verdict")
        if verdict not in VERDICT_ALL:
            rep.add("error", "VERDICT_VOCAB", f"{path}.verdict",
                    f"verdict {verdict!r} not in closed vocabulary")
        if verdict in VERDICT_LEGACY:
            rep.add("warning", "VERDICT_LEGACY", f"{path}.verdict",
                    f"using legacy 3-value verdict {verdict!r}; new trees should use 6-value vocab")

        for j, ev in enumerate(h.get("baseline_data") or []):
            ok, reason = has_source_refs(ev)
            if not ok:
                rep.add("error", "EVIDENCE_SOURCE", f"{path}.baseline_data[{j}]",
                        f"missing source ref: {reason}")
        for j, ev in enumerate(h.get("recent_evidence") or []):
            ok, reason = has_source_refs(ev)
            if not ok:
                rep.add("error", "EVIDENCE_SOURCE", f"{path}.recent_evidence[{j}]",
                        f"missing source ref: {reason}")

        if not (h.get("hypothesis_full") or "").strip():
            rep.add("error", "HYP_FULL_EMPTY", path, "hypothesis_full is empty")
        if not (h.get("title") or "").strip():
            rep.add("error", "HYP_TITLE_EMPTY", path, "title is empty")
        if not (h.get("baseline_data") or []):
            rep.add("error", "BASELINE_EMPTY", path,
                    "baseline_data is empty — every leaf needs an evidentiary anchor")


def check_acyclic(branches: list[dict], hypotheses: list[dict], rep: Report):
    """Real DFS: with multi-parent leaves now legal, validate strict acyclicity."""
    branch_ids = {b.get("id") for b in branches}
    edges: dict[str, set[str]] = {ROOT_ID: set(branch_ids)}
    for b in branches:
        edges.setdefault(b.get("id", ""), set())
    for h in hypotheses:
        hid = h.get("id", "")
        parents = h.get("parents") or ([hid[0]] if hid else [])
        for p in parents:
            edges.setdefault(p, set()).add(hid)
        edges.setdefault(hid, set())

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in edges}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for v in edges.get(u, set()):
            if color.get(v, WHITE) == GRAY:
                rep.add("error", "ACYCLIC", f"node {u}", f"cycle detected via edge {u} -> {v}")
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    dfs(ROOT_ID)


def check_tracking_events(events: list[dict], rep: Report):
    for i, e in enumerate(events):
        if not isinstance(e, dict):
            continue
        t = e.get("time")
        if t is None:
            continue
        t = str(t)
        if not ISO8601_TIME_RE.match(t):
            rep.add("error", "TIME_FORMAT", f"tracking_events[{i}].time",
                    f"{t!r} is not ISO 8601 (expected YYYY-MM-DD, YYYY-MM, or YYYY-Q[1-4])")


def check_aggregation_block(agg: dict, rep: Report):
    if not agg:
        return
    if "scoring" in agg:
        for k, v in (agg["scoring"] or {}).items():
            if not isinstance(v, (int, float)):
                rep.add("error", "AGG_SCORING_TYPE", f"aggregation.scoring[{k}]",
                        f"score must be numeric, got {v!r}")
    bw = agg.get("branch_weight_default")
    if bw and bw not in {"fibonacci", "linear", "uniform"}:
        rep.add("error", "AGG_WEIGHT_DEFAULT", "aggregation.branch_weight_default",
                f"unknown sequence {bw!r}")
    for fld in ("branch_kill_threshold", "h0_kill_threshold"):
        if fld in agg and not isinstance(agg[fld], (int, float)):
            rep.add("error", "AGG_KILL_TYPE", f"aggregation.{fld}", "must be numeric")


def check_linked_trees(linked: list[dict], rep: Report):
    for i, lt in enumerate(linked):
        if not isinstance(lt, dict):
            continue
        if not lt.get("ticker"):
            rep.add("error", "LINKED_TICKER", f"linked_trees[{i}].ticker", "missing ticker")
        if lt.get("relation") not in {"mirror", "counter", "upstream", "downstream"}:
            rep.add("error", "LINKED_RELATION", f"linked_trees[{i}].relation",
                    f"unknown relation {lt.get('relation')!r}")
        hyp = lt.get("hypothesis")
        if hyp and not HYP_ID_RE.match(hyp):
            rep.add("error", "LINKED_HYP_ID", f"linked_trees[{i}].hypothesis",
                    f"hypothesis id {hyp!r} invalid")


def validate(doc: dict) -> Report:
    rep = Report()
    if doc.get("drawtree_version") != "0.2":
        rep.add("warning", "VERSION", "$.drawtree_version",
                f"drawtree_version is {doc.get('drawtree_version')!r}; this validator targets 0.2")

    consensus = doc.get("consensus") or {}
    root = doc.get("root") or {}
    branches = doc.get("branches") or []
    hypotheses = doc.get("hypotheses") or []

    check_root(root, consensus, rep)
    check_decomposition(root, branches, hypotheses, rep)
    check_leaves(hypotheses, rep)
    check_acyclic(branches, hypotheses, rep)
    check_tracking_events(doc.get("tracking_events") or [], rep)
    check_aggregation_block(doc.get("aggregation") or {}, rep)
    check_linked_trees(doc.get("linked_trees") or [], rep)
    return rep


def emit(rep: Report, label: str, agg_summary: dict | None = None):
    if not rep.issues:
        print(f"✓ {label}: PASS — 0 errors, 0 warnings")
    else:
        err_n = len(rep.errors)
        warn_n = len(rep.warnings)
        icon = "✗" if err_n else "⚠"
        print(f"{icon} {label}: {err_n} error(s), {warn_n} warning(s)")
        for issue in rep.issues:
            bullet = "  ERR " if issue.severity == "error" else "  WARN"
            print(f"{bullet} [{issue.code}] {issue.path}: {issue.message}")
    if agg_summary:
        print(f"  → H-0: {agg_summary['h0_verdict']} (score={agg_summary['h0_score']}, "
              f"conviction={agg_summary['conviction']})  expected_return={agg_summary['expected_return']}")
        for b in agg_summary["branches"]:
            print(f"     · {b['id']} (w={b['weight']:.2f}): {b['verdict']} (score={b['score']:.2f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--show-aggregation", action="store_true")
    args = ap.parse_args()

    total_errors = 0
    total_warnings = 0

    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists():
            print(f"✗ {path}: file not found", file=sys.stderr)
            total_errors += 1
            continue
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"✗ {path}: invalid JSON ({e})", file=sys.stderr)
            total_errors += 1
            continue
        rep = validate(doc)
        agg_summary = aggregate(doc) if args.show_aggregation else None
        emit(rep, str(path), agg_summary)
        total_errors += len(rep.errors)
        total_warnings += len(rep.warnings)

    print()
    print(f"Total: {total_errors} error(s), {total_warnings} warning(s)")
    if total_errors:
        sys.exit(2)
    if args.strict and total_warnings:
        sys.exit(2)


if __name__ == "__main__":
    main()
