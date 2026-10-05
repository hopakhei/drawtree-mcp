"""Protocol v0.3 tests: golden aggregation against the maintainer's fleet engine, validator,
migration, condition sweep and verdict-change gate. Runs without the `mcp` package."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from drawtree_mcp._kernel import protocol as P  # noqa: E402
from drawtree_mcp._kernel.aggregation import aggregate, aggregate_v02, is_v03, price_implied_probabilities  # noqa: E402
from drawtree_mcp._kernel.migrate import migrate_v02_to_v03  # noqa: E402
from drawtree_mcp._kernel.sweep import sweep_conditions  # noqa: E402
from drawtree_mcp._kernel.validate import validate  # noqa: E402
from drawtree_mcp._kernel.verdict_change import validate_verdict_change  # noqa: E402

FIX = json.loads((ROOT / "tests" / "fixtures" / "crwd_structure_2026-10-03.json").read_text(encoding="utf-8"))


def test_golden_crwd_matches_fleet_engine():
    """Acceptance test for the sync: aggregate(CRWD structure) == tree_quant/4 quant_history row."""
    r = aggregate(FIX)
    e = FIX["expected"]
    assert r["protocol"] == "0.3"
    assert r["h0_score"] == e["h0_score"], (r["h0_score"], e["h0_score"])
    assert r["h0_verdict"] == e["h0_verdict"]
    assert r["conviction"] == e["conviction"], (r["conviction"], e["conviction"])
    assert r["verdict_based"] == {"bull": e["p_bull"], "base": e["p_base"], "bear": e["p_bear"]}
    pi = {k: r["price_implied"][k] for k in ("bull", "base", "bear")}
    assert pi == {"bull": e["pi_bull"], "base": e["pi_base"], "bear": e["pi_bear"]}, pi
    assert r["expected_return_detail"]["verdict_based"] == e["er_verdict"]
    assert r["expected_return_detail"]["price_implied"] == e["er_price_implied"]
    for b in r["branches"]:
        x = FIX["expected_branches"][b["id"]]
        assert (b["score"], b["conviction"], b["verdict"], b["weight"]) == (x["score"], x["conviction"], x["verdict"], x["weight"]), (b, x)
    print(f"✓ golden CRWD: h0={r['h0_score']} {r['h0_verdict']} conv={r['conviction']} pi={pi}")


def test_v03_kill_thresholds_and_necessity():
    doc = copy.deepcopy(FIX)
    # a Falsified leaf with default weight 1.0 does NOT kill in v0.3 (threshold 2.0) …
    doc["hypotheses"][0]["verdict"] = "Falsified"
    r = aggregate(doc)
    a = next(b for b in r["branches"] if b["id"] == "A")
    assert a["kill_fired"] is True, "A1 is in necessity_leaves, so it must kill"
    doc["branches"][0]["necessity_leaves"] = []
    r = aggregate(doc)
    a = next(b for b in r["branches"] if b["id"] == "A")
    assert a["kill_fired"] is False and a["verdict"] != "Falsified"
    # … but leaf_weights ≥ 2.0 does.
    doc["branches"][0]["leaf_weights"] = {"A1": 2.0}
    r = aggregate(doc)
    a = next(b for b in r["branches"] if b["id"] == "A")
    assert a["kill_fired"] is True and r["h0_verdict"] == "Falsified"   # branch weight 2.5 ≥ 2.0 kills H-0
    print("✓ v0.3 kill semantics (2.0 threshold, necessity_leaves)")


def test_price_implied_clamp():
    assert price_implied_probabilities(100, 50, 90, 120)["infeasible"] is None
    assert price_implied_probabilities(130, 50, 90, 120) == {"bull": 1.0, "base": 0.0, "bear": 0.0, "infeasible": "above_bull"}
    assert price_implied_probabilities(40, 50, 90, 120)["infeasible"] == "below_bear"
    print("✓ price-implied Max-Base clamp flags")


def _v02_tree():
    return {
        "drawtree_version": "0.2", "ticker": "DEMO", "snapshot_date": "2026-05-22",
        "consensus": {"narrative": "n", "implicit_assumptions": ["a"], "pricing_logic": "p"},
        "root": {"id": "H0", "verdict": "pending", "question": "Will X hold rather than Y?", "core_thesis": "t",
                 "narrative_versions": {"current_version_id": "v1", "next_candidate_id": "v2",
                                        "versions": [{"id": "v1", "label": "now", "status": "current"},
                                                     {"id": "v2", "label": "next", "status": "next_candidate"}]}},
        "branches": [{"id": x, "label": x, "core_question": "?"} for x in "ABC"],
        "hypotheses": [
            {"id": f"{x}1", "title": f"{x}1 question?", "hypothesis_full": "ARR exceeds $500M FY27",
             "baseline_data": [{"text": "x", "source_name": "S", "url": "https://x", "date": "2026-01-01"}],
             "recent_evidence": [{"text": "y", "source_name": "S", "url": "https://y", "date": "2026-02-01"}],
             "verdict": "supported" if x == "A" else "Trending positive",
             "falsification": [{"text": "FY27 H1 ARR < $400M", "type": "observable"}]}
            for x in "ABC"],
    }


def test_v02_still_legacy_semantics():
    doc = _v02_tree()
    assert not is_v03(doc)
    r = aggregate(doc)
    assert r["protocol"] == "0.2" and r == aggregate_v02(doc)
    assert [b["weight"] for b in r["branches"]] == [3.0, 2.0, 1.0]
    print("✓ v0.2 docs still aggregate with legacy semantics")


def test_migration_then_validation():
    doc, rep = migrate_v02_to_v03(_v02_tree())
    assert doc["drawtree_version"] == "0.3" and is_v03(doc)
    assert [b["impact_grade"] for b in doc["branches"]] == ["明顯受損", "輕微", "邊緣"]   # Fibonacci 3,2,1 → legacy map
    assert all(b["weight"] == P.IMPACT_GRADES[b["impact_grade"]] for b in doc["branches"])
    a1 = doc["hypotheses"][0]
    assert a1["verdict"] == "Validated" and a1["conditions"][0]["cid"] == "A1-F1" and a1["condition_assessments"][0]["assessment"] == "not_met"
    assert a1["evidence_ledger"][0]["eid"] == "E001" and a1["evidence_ledger"][0]["tier"] == "news"
    assert rep["todo"], "migration must list what the author still has to supply"
    v = validate(doc)
    codes = {i.code for i in v.errors}
    # the mechanical migration cannot invent these; the validator must demand them
    for c in ("V3_BRANCH_ROLE", "V3_BRANCH_FIELD", "V3_NO_FATAL", "V3_NO_NUMERATOR_BRANCH", "V3_READING_GUIDE", "V3_LEAF_ROLE"):
        assert c in codes, (c, sorted(codes))
    print(f"✓ migrate v0.2→v0.3: {len(rep['changed'])} changes, {len(rep['todo'])} todo; validator demands the missing v0.3 fields")


def _v03_tree():
    rg = {k: "一句。" for k in P.SIX_LEVELS}
    def leaf(hid, verdict="Inconclusive", metric="arr_growth_pct", thr=20.0):
        return {"id": hid, "title": f"{hid} 問題？", "hypothesis_full": "命題", "verdict": verdict, "scenario_role": "兩者",
                "leaf_nature": "machine" if metric else "text", "short_question": "增長守得住嗎？", "reading_guide": rg,
                "baseline_data": [{"text": "x", "source_name": "10-K", "url": "https://sec.gov/x", "date": "2026-01-01"}],
                "conditions": [{"cid": f"{hid}-F1", "kind": "falsification", "text": "增長低於 20%", "metric": metric,
                                "operator": "<" if metric else None, "threshold": thr if metric else None, "unit": "pct", "window": "FY27Q1", "status": "open"}],
                "condition_assessments": [{"cid": f"{hid}-F1", "assessment": "not_met", "reason": "基線 25%"}],
                "evidence_ledger": [{"eid": "E001", "date": "2026-01-01", "text": "t", "source_name": "10-K", "url": "https://sec.gov/x",
                                     "tier": "filing", "impact": "supports", "bears_on": [f"{hid}-F1"], "digest": "t"}]}
    def br(bid, grade, role):
        return {"id": bid, "label": bid, "core_question": "?", "impact_grade": grade, "weight": P.IMPACT_GRADES[grade],
                "scenario_role": role, "necessary_condition": "c", "falsification_rule": "任一葉證偽即本層證偽",
                "framework": "VRIO｜第 2 冊｜護城河", "weight_rationale": "§1.5 衝擊評級：後果佔現價 30%", "aggregation": "portfolio",
                "falsification_consequence": ["bear_multiple"]}
    base = _v02_tree()
    base.update({"drawtree_version": "0.3",
                 "branches": [br("A", "致命", "倍數持久"), br("B", "重創", "分子交付"), br("C", "明顯受損", "加速器")],
                 "hypotheses": [leaf("A1"), leaf("A2", metric=None), leaf("B1", "Trending positive"), leaf("C1")]})
    return base


def test_v03_valid_tree_passes():
    rep = validate(_v03_tree())
    assert not rep.errors, [f"{i.code} {i.path} {i.message}" for i in rep.errors]
    print("✓ a complete v0.3 tree validates with 0 errors")


def test_v03_gates_fire():
    doc = _v03_tree()
    doc["hypotheses"][0]["conditions"][0]["status"] = "breached"
    doc["hypotheses"][0]["verdict"] = "Validated"
    doc["hypotheses"][0]["condition_assessments"] = []
    doc["branches"][0]["weight"] = 1.0
    doc["hypotheses"][2]["verdict"] = "challenged"
    codes = {i.code for i in validate(doc).errors}
    for c in ("V3_E2_GOALPOST", "V3_E3_UNADDRESSED", "V3_E7_UNASSESSED", "V3_WEIGHT_GRADE", "V3_VERDICT"):
        assert c in codes, (c, sorted(codes))
    print("✓ v0.3 gates: E2, E3, E7, weight⇔grade, legacy verdict")


def test_sweep_breach_and_deadline():
    doc = _v03_tree()
    doc["hypotheses"][0]["observations"] = [{"metric": "arr_growth_pct", "value": 15.0, "date": "2026-05-01", "window": "FY27Q1"}]
    doc["hypotheses"][1]["conditions"].append({"cid": "A2-D1", "kind": "deadline", "text": "Q2 前公布", "metric": None, "operator": None,
                                              "threshold": None, "unit": None, "window": None, "status": "open", "due": "2026-06-30",
                                              "basis": {"text": "管理層時間表", "url": "https://x"}})
    out = sweep_conditions(doc, today="2026-07-01")
    assert out["breached"][0]["cid"] == "A1-F1" and doc["hypotheses"][0]["conditions"][0]["status"] == "breached"
    assert doc["hypotheses"][0]["conditions"][0]["breach"]["value"] == 15.0
    assert out["expired"][0]["cid"] == "A2-D1" and doc["hypotheses"][1]["conditions"][1]["status"] == "expired_unfulfilled"
    syn = [e for e in doc["hypotheses"][1]["evidence_ledger"] if e["tier"] == "synthetic"]
    assert syn and syn[0]["eid"] == "SYN-A2-D1-2026-07-01" and syn[0]["impact"] == "challenges"
    again = sweep_conditions(doc, today="2026-07-01")
    assert not again["breached"] and not again["expired"], "sweep must be idempotent"
    print("✓ sweep: breach latch, deadline clock, synthetic rows, idempotent")


def test_verdict_change_gate():
    leaf = _v03_tree()["hypotheses"][0]
    week = [{"url": "https://news/1", "eid": "W001", "tier": "news", "impact": "challenges", "text": "guidance cut"}]
    ok = validate_verdict_change(leaf, {"new_verdict": "Trending negative", "reason": "guidance 下調", "cited_evidence_urls": ["https://news/1"],
                                        "driver_eids": ["W001"], "falsification_basis": ""}, week)
    assert ok["ok"] and ok["provenance"] == "new_evidence", ok
    r1 = validate_verdict_change(leaf, {"new_verdict": "Trending negative", "reason": "x", "cited_evidence_urls": ["https://other"]}, week)
    assert r1["dropped_reason"] == "rule_1_no_evidence_url_cited"
    r1d = validate_verdict_change(leaf, {"new_verdict": "Validated", "reason": "guidance 上調", "cited_evidence_urls": ["https://news/1"], "driver_eids": ["W001"]}, week)
    assert r1d["dropped_reason"].startswith("rule_1d")
    r2 = validate_verdict_change(leaf, {"new_verdict": "Falsified", "reason": "guidance 下調", "cited_evidence_urls": ["https://news/1"], "falsification_basis": "完全無關的句子"}, week)
    assert r2["dropped_reason"].startswith("rule_2")
    r2ok = validate_verdict_change(leaf, {"new_verdict": "Falsified", "reason": "guidance 下調", "cited_evidence_urls": ["https://news/1"], "falsification_basis": "增長低於 20%"}, week)
    assert r2ok["ok"], r2ok
    r3 = validate_verdict_change(leaf, {"new_verdict": "Trending negative", "reason": "股價下跌 20%", "cited_evidence_urls": ["https://news/1"]}, week)
    assert r3["dropped_reason"] == "rule_3_price_only_reason"
    r1c = validate_verdict_change(leaf, {"new_verdict": "Trending negative", "reason": "guidance", "cited_evidence_urls": ["https://news/1"], "driver_eids": ["E999"]}, week)
    assert r1c["dropped_reason"].startswith("rule_1c")
    print("✓ verdict-change gate: rules 1, 1c, 1d, 2, 3 and provenance")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback; traceback.print_exc()
            print(f"✗ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed} / {len(tests)} passed")
    sys.exit(1 if failed else 0)
