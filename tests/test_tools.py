"""Smoke tests for every tool, run without a network or MCP transport."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from drawtree_mcp import (  # noqa: E402
    falsification, framework_retrieval, fleet_match, narrative,
)
from drawtree_mcp.scenario import (  # noqa: E402
    ScenarioInputs, identify_tension_point, reverse_engineer, what_market_betting,
)
from drawtree_mcp._kernel.aggregation import aggregate, fibonacci_weights  # noqa: E402
from drawtree_mcp._kernel.validate import validate  # noqa: E402

# Fully imports server so tool handlers are exercised
from drawtree_mcp.server import TOOL_HANDLERS  # noqa: E402


SAMPLE_HANDOFF = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE HANDOFF — for Hypothesis Tree Construction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Palantir Technologies | PLTR | 2026-05-22

[Current Market Story]
The market currently treats PLTR as an AI infrastructure pure-play, valuing it at
EV/Sales 18x in line with Snowflake / Databricks. Sell-side reports anchor on
"AIP commercial traction" and DCF over 10-year explicit forecasts.

[Where the Market May Be Wrong]
Error Type: Identity Mislabel
Hypothesis: The market assumes PLTR is an AI infrastructure company, but in
reality it remains a Defense IT services company with adjacent commercial
traction. If this holds, the valuation framework should shift from EV/Sales 18x
to EV/Sales 6-8x.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


def _minimal_tree():
    return {
        "drawtree_version": "0.2", "ticker": "DEMO", "snapshot_date": "2026-05-22",
        "consensus": {"narrative": "n", "implicit_assumptions": ["a"], "pricing_logic": "p"},
        "root": {
            "id": "H0", "verdict": "pending", "question": "?", "core_thesis": "t",
            "narrative_versions": {
                "current_version_id": "v1", "next_candidate_id": "v2",
                "versions": [
                    {"id": "v1", "label": "now", "status": "current"},
                    {"id": "v2", "label": "next", "status": "next_candidate"},
                ],
            },
        },
        "branches": [
            {"id": "A", "label": "Product", "core_question": "?"},
            {"id": "B", "label": "Lock-in", "core_question": "?"},
            {"id": "C", "label": "Cadence", "core_question": "?"},
        ],
        "hypotheses": [
            {
                "id": f"{x}1", "title": f"{x}1",
                "hypothesis_full": "AIP software ARR will exceed $500M by FY27",
                "baseline_data": [{"text": "x", "source_name": "S", "url": "https://x", "date": "2026-01-01"}],
                "verdict": "Trending positive",
                "falsification": [{"text": "FY27 H1 ARR not separately disclosed", "type": "observable"}],
            }
            for x in ["A", "B", "C"]
        ],
    }


def test_narrative_parse():
    p = narrative.parse_handoff(SAMPLE_HANDOFF)
    assert p["ticker"] == "PLTR"
    assert p["error_type"] == "Identity Mislabel"
    assert "Defense IT services" in p["hypothesis_parsed"]["in_reality"]
    assert "EV/Sales 18x" in p["hypothesis_parsed"]["framework_from"]
    print("✓ narrative.parse_handoff")


def test_root_question_derivation():
    p = narrative.parse_handoff(SAMPLE_HANDOFF)
    q = narrative.derive_root_question(p)
    assert "Will" in q and "PLTR" not in q  # generic phrasing, no ticker leakage
    print("✓ narrative.derive_root_question:", q[:120])


def test_framework_retrieval():
    r = framework_retrieval.search("AI infrastructure customer lock-in network effects", top_k=3)
    assert len(r) == 3
    names = [x["name"] for x in r]
    print("✓ framework_retrieval.search top 3:", names)


def test_falsification_observable():
    s = falsification.suggest("AIP software ARR will exceed $500M by FY27")
    assert len(s) > 0
    print("✓ falsification.suggest:", s[0]["text"][:80])


def test_aggregate():
    t = _minimal_tree()
    r = aggregate(t)
    assert r["h0_verdict"] in (
        "Validated", "Trending positive", "Inconclusive",
        "Trending negative", "Approaching falsification", "Falsified",
    )
    print(f"✓ aggregate: h0={r['h0_verdict']} conviction={r['conviction']}")


def test_validate():
    rep = validate(_minimal_tree())
    assert not rep.errors, [(i.code, i.message) for i in rep.errors]
    print("✓ validate: 0 errors")


def test_scenario_reverse_engineer():
    inputs = ScenarioInputs(bull_value=35, base_value=24, bear_value=14, current_price=22.5)
    p = reverse_engineer(inputs)
    total = round(p.bull + p.base + p.bear, 2)
    assert abs(total - 1.0) < 0.02, f"probs sum = {total}"
    print(f"✓ scenario: P(bull)={p.bull} P(base)={p.base} P(bear)={p.bear}")


def test_tension_point():
    t = _minimal_tree()
    inputs = ScenarioInputs(bull_value=35, base_value=24, bear_value=14, current_price=22.5)
    probs = reverse_engineer(inputs)
    tp = identify_tension_point(t, probs)
    assert tp is not None
    assert tp["leaf_id"] in {"A1", "B1", "C1"}
    print(f"✓ tension point: leaf {tp['leaf_id']} (eff_weight={tp['effective_weight']})")


def test_tool_handlers_callable():
    """Every advertised tool has a handler."""
    expected = {
        "validate_tree", "aggregate_tree", "commit_tree", "read_tree",
        "register_narrative", "suggest_framework", "enrich_branches",
        "suggest_falsification", "derive_implied_probabilities", "subscribe_alerts",
    }
    assert set(TOOL_HANDLERS.keys()) == expected
    print(f"✓ all 10 tool handlers wired")


def test_register_narrative_e2e():
    # Run the actual MCP tool handler (exercises parser + fleet_match's mocked path)
    handler = TOOL_HANDLERS["register_narrative"]
    out = asyncio.run(handler({"narrative_handoff_block": SAMPLE_HANDOFF}))
    assert out["ok"] is True
    assert out["narrative"]["ticker"] == "PLTR"
    assert "Will" in out["suggested_h0_question"]
    # fleet_pattern_match may be empty if API offline, that's OK
    print(f"✓ register_narrative tool: H-0='{out['suggested_h0_question'][:80]}...'")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed} / {len(tests)} passed")
    sys.exit(1 if failed else 0)
