"""Smoke tests for the slim Path C MCP server."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from drawtree_mcp import framework_retrieval  # noqa: E402
from drawtree_mcp._kernel.aggregation import aggregate, fibonacci_weights  # noqa: E402
from drawtree_mcp._kernel.validate import validate  # noqa: E402
from drawtree_mcp.server import TOOL_HANDLERS  # noqa: E402


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
            {"id": "A", "label": "A", "core_question": "?"},
            {"id": "B", "label": "B", "core_question": "?"},
            {"id": "C", "label": "C", "core_question": "?"},
        ],
        "hypotheses": [
            {"id": f"{x}1", "title": f"{x}1", "hypothesis_full": "ARR exceeds $500M FY27",
             "baseline_data": [{"text": "x", "source_name": "S", "url": "https://x", "date": "2026-01-01"}],
             "verdict": "Trending positive",
             "falsification": [{"text": "FY27 H1 ARR not separately disclosed", "type": "observable"}]}
            for x in ["A", "B", "C"]
        ],
    }


def test_fibonacci_weights():
    assert fibonacci_weights(4) == [5.0, 3.0, 2.0, 1.0]
    print("✓ fibonacci_weights")


def test_framework_retrieval_no_ip_fields():
    """Ensure public retrieval returns only name + category + score."""
    r = framework_retrieval.search("AI infrastructure customer lock-in", top_k=3)
    assert len(r) == 3
    for item in r:
        assert set(item.keys()) <= {"name", "category", "score"}
        assert "leaf_affinity" not in item
        assert "diagnostic_questions" not in item
        assert "tags" not in item
    print(f"✓ framework_retrieval IP-clean — top: {[x['name'] for x in r]}")


def test_aggregate_basic():
    r = aggregate(_minimal_tree())
    assert r["h0_verdict"] in (
        "Validated", "Trending positive", "Inconclusive",
        "Trending negative", "Approaching falsification", "Falsified",
    )
    print(f"✓ aggregate: h0={r['h0_verdict']} conv={r['conviction']}")


def test_validate_basic():
    rep = validate(_minimal_tree())
    assert not rep.errors
    print("✓ validate: 0 errors")


def test_tool_handlers_set():
    """The advertised tools match what's wired."""
    expected = {
        # free
        "validate_tree", "aggregate_tree", "commit_tree", "read_tree",
        "suggest_framework", "balance",
        # portfolio (Phase 2)
        "get_portfolio_ideas", "size_portfolio", "build_rebalance",
        # paid
        "register_narrative", "enrich_branches", "suggest_falsification",
        "derive_scenario_values", "subscribe_alerts",
        # lifecycle
        "confirm_charge", "refund_charge",
    }
    actual = set(TOOL_HANDLERS.keys())
    assert actual == expected, f"missing: {expected - actual}; extra: {actual - expected}"
    print(f"✓ all {len(expected)} tools wired")


def test_no_ip_in_kb_file():
    import json
    kb = json.load(open(ROOT / "kb" / "frameworks.json"))
    for name, fw in kb["frameworks"].items():
        assert "leaf_affinity" not in fw, f"leaf_affinity leaked in {name}"
    print(f"✓ kb/frameworks.json clean of leaf_affinity ({len(kb['frameworks'])} frameworks)")


def _tree_record(ticker="NVDA", bull=260, bear=120, current=170, conviction=0.68):
    return {
        "ticker": ticker,
        "tree": {"valuation": {
            "snapshot_price": current,
            "scenarios": {
                "bull": {"target_price": bull},
                "bear": {"target_price": bear},
            },
        }},
        "aggregation": {"conviction": conviction},
    }


def test_portfolio_tree_to_idea_mapping():
    from drawtree_mcp import portfolio
    idea = portfolio.tree_to_idea(_tree_record())
    assert idea == {
        "ticker": "NVDA", "bull": 260, "bear": 120,
        "conviction_source": "mcp", "current": 170, "conviction": 0.68,
    }
    # a tree missing bull/bear targets is unusable -> None
    assert portfolio.tree_to_idea({"ticker": "X", "tree": {"valuation": {}}}) is None
    print("✓ tree_to_idea mapping + skip")


def test_get_portfolio_ideas_filters_and_skips():
    from drawtree_mcp import api_client, portfolio
    calls = {}
    fake = {"NVDA": _tree_record("NVDA"), "BAD": {"ticker": "BAD", "tree": {"valuation": {}}}}

    def fake_read(ticker, agent_handle=None):
        calls[ticker] = True
        return fake[ticker]

    orig = api_client.read_tree
    api_client.read_tree = fake_read
    try:
        out = portfolio.get_portfolio_ideas(["nvda", "bad"])
    finally:
        api_client.read_tree = orig
    assert [i["ticker"] for i in out["ideas"]] == ["NVDA"]
    assert out["skipped"] and out["skipped"][0]["ticker"] == "BAD"
    print("✓ get_portfolio_ideas filter + skip")


def test_size_and_build_call_backbone():
    from drawtree_mcp import api_client, portfolio
    seen = {}

    def fake_engine(payload):
        seen["payload"] = payload
        return {"ok": True, "allocations": [], "correlation": {}}

    orig = api_client.size_and_rebalance
    api_client.size_and_rebalance = fake_engine
    try:
        ideas = [{"ticker": "NVDA", "bull": 260, "bear": 120}]
        r = portfolio.size_portfolio(ideas=ideas)
        assert r["ok"] and "execution" not in seen["payload"]

        r2 = portfolio.build_rebalance(
            ideas=ideas, broker="futu", nlv=1_000_000,
            positions=[{"ticker": "NVDA", "shares": 1000}],
        )
        ex = seen["payload"]["execution"]
        assert ex["trd_env"] == "SIMULATE" and ex["broker"] == "futu"
        assert "PREVIEW ONLY" in r2["safety_note"]
    finally:
        api_client.size_and_rebalance = orig

    # validation guards
    assert "error" in portfolio.build_rebalance([], "futu", 1, [])
    assert "error" in portfolio.build_rebalance([{"ticker": "X"}], "robinhood", 1, [])
    assert "error" in portfolio.size_portfolio()
    print("✓ size_portfolio / build_rebalance backbone + guards")


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
