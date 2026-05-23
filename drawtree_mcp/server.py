"""drawtree-mcp — stdio MCP server.

Exposes 9 tools that turn the user's Claude (loaded with the 90s-pm-investing
skills) into a structured-thesis copilot.

The server itself does ZERO LLM calls. All thinking happens client-side. The
server provides:
  - Schema validation (the same v0.2 invariants drawtree-api enforces)
  - Aggregation (leaf -> branch -> H-0 verdict + conviction + expected return)
  - Framework retrieval (164 frameworks indexed for keyword-based lookup)
  - Falsification heuristics (regex + framework affinity)
  - Fleet pattern matching (cross-reference user's narrative against the 44
    seeded trees' archetype classifications)
  - Implied-probability reverse engineering (scenario-valuation Step 3)
  - Persistence (publish to drawtree-api)

Configured for any MCP-aware client (Claude Desktop, Cursor, Continue, Goose, etc).
"""
from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import api_client, falsification, fleet_match, framework_retrieval, narrative
from . import scenario as scenario_mod
from ._kernel.aggregation import aggregate, annotate_doc
from ._kernel.validate import validate as validate_v02


server = Server("drawtree-mcp")


# ============================================================
# Tool: validate_tree
# ============================================================
async def tool_validate_tree(args: dict) -> dict:
    tree = args.get("tree")
    if not isinstance(tree, dict):
        return {"error": "tree must be a JSON object"}
    rep = validate_v02(tree)
    return {
        "ok": len(rep.errors) == 0,
        "errors": [{"code": i.code, "path": i.path, "message": i.message} for i in rep.errors],
        "warnings": [{"code": i.code, "path": i.path, "message": i.message} for i in rep.warnings],
        "summary": (
            f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s) — "
            f"{'tree is publishable' if not rep.errors else 'tree is NOT publishable; fix errors'}"
        ),
    }


# ============================================================
# Tool: aggregate_tree
# ============================================================
async def tool_aggregate_tree(args: dict) -> dict:
    tree = args.get("tree")
    if not isinstance(tree, dict):
        return {"error": "tree must be a JSON object"}
    return aggregate(tree)


# ============================================================
# Tool: commit_tree
# ============================================================
async def tool_commit_tree(args: dict) -> dict:
    tree = args.get("tree")
    if not isinstance(tree, dict):
        return {"error": "tree must be a JSON object"}
    visibility = args.get("visibility", "private")
    if visibility not in ("private", "unlisted", "public"):
        return {"error": "visibility must be private | unlisted | public"}
    annotate_doc(tree)
    if "_meta" not in tree:
        tree["_meta"] = {}
    tree["_meta"]["visibility"] = visibility
    try:
        result = api_client.publish(tree)
    except Exception as e:
        return {"error": f"publish failed: {e}"}
    return {
        "ok": True,
        "ticker": tree.get("ticker"),
        "version_hash": result.get("version_hash"),
        "tree_id": result.get("tree_id"),
        "aggregation": result.get("aggregation"),
        "attestation": result.get("attestation", "")[:48] + "...",
        "view_url": f"https://drawtree-dashboard.vercel.app/t/{tree.get('ticker')}",
    }


# ============================================================
# Tool: read_tree
# ============================================================
async def tool_read_tree(args: dict) -> dict:
    ticker = args.get("ticker", "").upper()
    if not ticker:
        return {"error": "ticker required"}
    agent_handle = args.get("agent_handle")
    try:
        return api_client.read_tree(ticker, agent_handle)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Tool: register_narrative
# ============================================================
async def tool_register_narrative(args: dict) -> dict:
    handoff_text = args.get("narrative_handoff_block", "")
    try:
        parsed = narrative.parse_handoff(handoff_text)
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
            "hint": (
                "The narrative-detection skill outputs a 'Structured Handoff Block' "
                "between two ━━ horizontal-line markers. Pass that block verbatim "
                "as the narrative_handoff_block argument."
            ),
        }

    similar = fleet_match.find_similar_trees(parsed["error_type"], parsed["ticker"])

    h0_question = narrative.derive_root_question(parsed)

    return {
        "ok": True,
        "narrative": parsed,
        "suggested_h0_question": h0_question,
        "fleet_pattern_match": {
            "error_type": parsed["error_type"],
            "matching_trees": similar,
            "matching_count": len(similar),
            "interpretation": (
                f"Found {len(similar)} tree(s) in our fleet with related narrative archetypes. "
                f"Their H-0 outcomes are above — use them as historical priors."
                if similar
                else "No close historical match in fleet. This narrative pattern is a fresh signal."
            ),
        },
        "next_step": (
            "Use suggest_branch_decomposition with this narrative + the suggested H-0 "
            "to scaffold the 4 MECE branches."
        ),
    }


# ============================================================
# Tool: suggest_framework
# ============================================================
async def tool_suggest_framework(args: dict) -> dict:
    query = args.get("query", "")
    top_k = int(args.get("top_k", 3))
    if not query:
        return {"error": "query required (e.g. 'AI infrastructure customer lock-in')"}
    results = framework_retrieval.search(query, top_k=top_k)
    enriched = []
    for r in results:
        enriched.append({
            **r,
            "diagnostic_questions": framework_retrieval.diagnostic_questions(r["name"]),
        })
    return {"query": query, "results": enriched}


# ============================================================
# Tool: enrich_branches
# ============================================================
async def tool_enrich_branches(args: dict) -> dict:
    """Given a list of {id, label, core_question}, suggest top frameworks
    and seed sub-hypotheses for each branch.
    """
    branches = args.get("branches") or []
    if not isinstance(branches, list) or not branches:
        return {"error": "branches must be a non-empty list of {id, label, core_question}"}

    out = []
    for b in branches:
        if not isinstance(b, dict):
            continue
        bid = b.get("id", "")
        label = b.get("label", "")
        cq = b.get("core_question", "")
        results = framework_retrieval.search_for_branch(label, cq, top_k=3)
        suggestions = []
        for r in results:
            qs = framework_retrieval.diagnostic_questions(r["name"])
            suggestions.append({
                "framework": r["name"],
                "category": r["category"],
                "score": r["score"],
                "leaf_seed_questions": qs,
            })
        out.append({
            "branch_id": bid,
            "branch_label": label,
            "core_question": cq,
            "framework_suggestions": suggestions,
        })
    return {"branches": out}


# ============================================================
# Tool: suggest_falsification
# ============================================================
async def tool_suggest_falsification(args: dict) -> dict:
    hyp = args.get("hypothesis_full", "")
    leaf_id = args.get("leaf_id", "")
    if not hyp:
        return {"error": "hypothesis_full required"}
    suggestions = falsification.suggest(hyp, leaf_id)
    return {
        "leaf_id": leaf_id,
        "hypothesis_full": hyp,
        "suggestions": suggestions,
        "note": (
            "Each suggestion is a TYPED Falsification object. The user's Claude should "
            "fill in the {threshold} / {year} / {N} placeholders with company-specific "
            "values, then validate that the final string passes the observability regex."
        ),
    }


# ============================================================
# Tool: derive_implied_probabilities
# ============================================================
async def tool_derive_implied_probabilities(args: dict) -> dict:
    tree = args.get("tree") or {}
    bull = float(args.get("bull_value", 0))
    base = float(args.get("base_value", 0))
    bear = float(args.get("bear_value", 0))
    price = float(args.get("current_price", 0))
    base_anchor = float(args.get("base_anchor", 0.5))
    if not (bull and base and bear and price):
        return {"error": "bull_value, base_value, bear_value, current_price required"}

    inputs = scenario_mod.ScenarioInputs(
        bull_value=bull, base_value=base, bear_value=bear,
        current_price=price, base_anchor=base_anchor,
    )
    probs = scenario_mod.reverse_engineer(inputs)
    error_type = (
        ((tree.get("root") or {}).get("narrative_versions") or {}).get("error_type")
        or args.get("error_type")
    )
    market_betting = scenario_mod.what_market_betting(probs, error_type=error_type)
    tension = scenario_mod.identify_tension_point(tree, probs)

    return {
        "implied_probabilities": {
            "bull": probs.bull, "base": probs.base, "bear": probs.bear,
        },
        "scenarios": {
            "bull": {"target_price": bull, "what_market_betting": market_betting["bull"]},
            "base": {"target_price": base, "what_market_betting": market_betting["base"]},
            "bear": {"target_price": bear, "what_market_betting": market_betting["bear"]},
        },
        "tension_point": tension,
        "core_stance": (
            "Display the mathematical structure of market pricing. Let the reader judge."
        ),
    }


# ============================================================
# Tool: subscribe_alerts
# ============================================================
async def tool_subscribe_alerts(args: dict) -> dict:
    """Phase 1 stub: persist a subscription record on drawtree-api."""
    ticker = args.get("ticker", "").upper()
    email = args.get("email")
    slack_webhook = args.get("slack_webhook")
    alert_on = args.get("alert_on") or ["verdict_changes", "kill_fires", "narrative_shifts"]
    if not ticker or (not email and not slack_webhook):
        return {"error": "ticker + at least one of email / slack_webhook required"}
    # The drawtree-api subscriptions endpoint is Phase 2 work; we record locally
    # and surface the request so it can be wired up server-side.
    return {
        "ok": True,
        "queued": True,
        "ticker": ticker,
        "channels": {"email": email, "slack_webhook": slack_webhook},
        "alert_on": alert_on,
        "note": (
            "Alert subscriptions are Phase 2 wiring; record stored client-side. "
            "When drawtree-api gains /v1/subscriptions, this tool will POST to it."
        ),
    }


# ============================================================
# Server bootstrap
# ============================================================
TOOL_HANDLERS = {
    "validate_tree": tool_validate_tree,
    "aggregate_tree": tool_aggregate_tree,
    "commit_tree": tool_commit_tree,
    "read_tree": tool_read_tree,
    "register_narrative": tool_register_narrative,
    "suggest_framework": tool_suggest_framework,
    "enrich_branches": tool_enrich_branches,
    "suggest_falsification": tool_suggest_falsification,
    "derive_implied_probabilities": tool_derive_implied_probabilities,
    "subscribe_alerts": tool_subscribe_alerts,
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="validate_tree",
            description=(
                "Run the Draw Tree v0.2 validator on a candidate tree. Surfaces "
                "structural errors (missing falsification, unobservable kill conditions, "
                "ID drift) and warnings. The server's commit_tree will refuse to publish "
                "any tree with errors."
            ),
            inputSchema={
                "type": "object",
                "required": ["tree"],
                "properties": {"tree": {"type": "object"}},
            },
        ),
        Tool(
            name="aggregate_tree",
            description=(
                "Compute leaf -> branch -> H-0 verdict aggregation, conviction (0..1), "
                "and expected return (if valuation is present). Uses Fibonacci-default "
                "branch weights unless overridden."
            ),
            inputSchema={
                "type": "object", "required": ["tree"],
                "properties": {"tree": {"type": "object"}},
            },
        ),
        Tool(
            name="commit_tree",
            description=(
                "Validate, aggregate, and publish a tree to drawtree-api. Returns "
                "version_hash + Ed25519 attestation + dashboard URL. Default visibility "
                "is private."
            ),
            inputSchema={
                "type": "object", "required": ["tree"],
                "properties": {
                    "tree": {"type": "object"},
                    "visibility": {"type": "string", "enum": ["private", "unlisted", "public"]},
                },
            },
        ),
        Tool(
            name="read_tree",
            description=(
                "Fetch the latest version of a tree by ticker. Optionally filter to a "
                "specific publishing agent_handle."
            ),
            inputSchema={
                "type": "object", "required": ["ticker"],
                "properties": {
                    "ticker": {"type": "string"},
                    "agent_handle": {"type": "string"},
                },
            },
        ),
        Tool(
            name="register_narrative",
            description=(
                "Parse a narrative-detection skill 'Structured Handoff Block' and "
                "cross-reference the detected error type against the public fleet of "
                "trees. Returns the parsed narrative, the H-0 root question derived "
                "from it, and similar historical trees with their H-0 verdicts. Use as "
                "Step 1 of the narrative-detection -> tree -> valuation pipeline."
            ),
            inputSchema={
                "type": "object", "required": ["narrative_handoff_block"],
                "properties": {
                    "narrative_handoff_block": {
                        "type": "string",
                        "description": "The exact handoff block emitted by the narrative-detection skill.",
                    },
                },
            },
        ),
        Tool(
            name="suggest_framework",
            description=(
                "Search the 164-framework business strategy KB for the top-k frameworks "
                "most relevant to a free-text query. Returns each framework's category, "
                "leaf-affinity tag, and curated diagnostic questions to seed leaves."
            ),
            inputSchema={
                "type": "object", "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3},
                },
            },
        ),
        Tool(
            name="enrich_branches",
            description=(
                "Given an array of {id, label, core_question}, suggest the top 3 "
                "frameworks per branch from the 164-framework KB, plus diagnostic "
                "questions to seed sub-hypotheses. The user's Claude then turns these "
                "into actual leaves with falsifications."
            ),
            inputSchema={
                "type": "object", "required": ["branches"],
                "properties": {
                    "branches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "label", "core_question"],
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "core_question": {"type": "string"},
                            },
                        },
                    },
                },
            },
        ),
        Tool(
            name="suggest_falsification",
            description=(
                "Given a hypothesis_full sentence, return up to 3 candidate falsification "
                "objects (typed: observable / directional / mechanism). The user's Claude "
                "fills in the {threshold} / {year} placeholders before commit."
            ),
            inputSchema={
                "type": "object", "required": ["hypothesis_full"],
                "properties": {
                    "hypothesis_full": {"type": "string"},
                    "leaf_id": {"type": "string"},
                },
            },
        ),
        Tool(
            name="derive_implied_probabilities",
            description=(
                "Reverse-engineer the market's implied probability distribution from "
                "the current price and the user's Bull/Base/Bear target prices. Identifies "
                "the highest-leverage tension-point leaf in the tree."
            ),
            inputSchema={
                "type": "object",
                "required": ["bull_value", "base_value", "bear_value", "current_price"],
                "properties": {
                    "tree": {"type": "object"},
                    "bull_value": {"type": "number"},
                    "base_value": {"type": "number"},
                    "bear_value": {"type": "number"},
                    "current_price": {"type": "number"},
                    "base_anchor": {"type": "number", "default": 0.5},
                    "error_type": {"type": "string"},
                },
            },
        ),
        Tool(
            name="subscribe_alerts",
            description=(
                "Subscribe to alerts when a tree's verdict changes, a kill switch fires, "
                "or a narrative shift is detected. Phase 1 stub — drawtree-api wiring "
                "lands in Phase 2."
            ),
            inputSchema={
                "type": "object", "required": ["ticker"],
                "properties": {
                    "ticker": {"type": "string"},
                    "email": {"type": "string"},
                    "slack_webhook": {"type": "string"},
                    "alert_on": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["verdict_changes", "kill_fires", "narrative_shifts"],
                        },
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]
    try:
        result = await handler(arguments or {})
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            server.create_initialization_options(),
        )


def cli():
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    cli()
