"""drawtree-mcp — stdio MCP server (Path C: protocol kernel only, IP-clean).

This server has TWO clear bands:

  FREE (deterministic, local):
    - validate_tree
    - aggregate_tree
    - commit_tree (publish to drawtree-api)
    - read_tree
    - suggest_framework  (top-k framework name + category, no IP)

  PAID (proxied to drawtree-api; charges to user's balance, hold/confirm):
    - register_narrative           parse + fleet pattern match
    - enrich_branches              framework deep retrieval + diagnostic seeds
    - suggest_falsification        observable kill condition + linked metrics
    - derive_scenario_values       Bull/Base/Bear vs current price + peer hints
    - subscribe_alerts             monitoring + email/Slack
    - confirm_charge               accept a pending hold
    - refund_charge                reject a pending hold within 24h
    - balance                      current balance + pending holds

Server runs zero LLM calls and contains zero proprietary reasoning.
The 90s-pm-investing knowledge base lives behind paid endpoints on the
hosted drawtree-api instance.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import api_client, framework_retrieval
from ._kernel.aggregation import aggregate, annotate_doc
from ._kernel.validate import validate as validate_v02


server = Server("drawtree-mcp")


# ============================================================
# FREE TOOLS — local deterministic, no charge
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


async def tool_aggregate_tree(args: dict) -> dict:
    tree = args.get("tree")
    if not isinstance(tree, dict):
        return {"error": "tree must be a JSON object"}
    return aggregate(tree)


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
        "view_url": f"https://drawtree-dashboard.vercel.app/t/{tree.get('ticker')}",
    }


async def tool_read_tree(args: dict) -> dict:
    ticker = args.get("ticker", "").upper()
    if not ticker:
        return {"error": "ticker required"}
    agent_handle = args.get("agent_handle")
    try:
        return api_client.read_tree(ticker, agent_handle)
    except Exception as e:
        return {"error": str(e)}


async def tool_suggest_framework(args: dict) -> dict:
    """FREE retrieval: returns top-k framework name + category.

    For framework deep content (diagnostic questions, leaf seeds, metric
    heuristics) call the PAID enrich_branches tool instead.
    """
    query = args.get("query", "")
    top_k = int(args.get("top_k", 3))
    if not query:
        return {"error": "query required"}
    results = framework_retrieval.search(query, top_k=top_k)
    return {
        "query": query,
        "results": results,
        "note": (
            "These are framework names only. To get diagnostic questions, "
            "leaf seeds, and per-framework metric heuristics, call "
            "enrich_branches (paid)."
        ),
    }


async def tool_balance(args: dict) -> dict:
    """Show current balance + pending holds + recent charges."""
    try:
        return api_client.get_balance()
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# PAID TOOLS — thin proxies to drawtree-api paid endpoints
# Each returns a `charge_id` + 24h auto-confirm timestamp.
# ============================================================

async def tool_register_narrative(args: dict) -> dict:
    """PAID: parse handoff + fleet pattern match. credits."""
    text = args.get("narrative_handoff_block", "")
    if not text:
        return {"error": "narrative_handoff_block required"}
    try:
        return api_client.paid_call("register_narrative", {"handoff_block": text})
    except Exception as e:
        return {"error": str(e)}


async def tool_enrich_branches(args: dict) -> dict:
    """PAID: framework deep retrieval per branch. credits hold."""
    branches = args.get("branches") or []
    if not isinstance(branches, list) or not branches:
        return {"error": "branches must be a non-empty list of {id, label, core_question}"}
    try:
        return api_client.paid_call("enrich_branches", {"branches": branches})
    except Exception as e:
        return {"error": str(e)}


async def tool_suggest_falsification(args: dict) -> dict:
    """PAID: observable kill condition with linked metric. credits."""
    hyp = args.get("hypothesis_full", "")
    leaf_id = args.get("leaf_id", "")
    if not hyp:
        return {"error": "hypothesis_full required"}
    try:
        return api_client.paid_call("suggest_falsification", {
            "hypothesis_full": hyp,
            "leaf_id": leaf_id,
        })
    except Exception as e:
        return {"error": str(e)}


async def tool_derive_scenario_values(args: dict) -> dict:
    """PAID: Bull/Base/Bear values vs current price + peer hints. credits."""
    payload = {
        "tree": args.get("tree"),
        "current_price": args.get("current_price"),
        "peer_group": args.get("peer_group"),  # optional
        "valuation_method": args.get("valuation_method"),  # optional
        "scenarios": args.get("scenarios"),  # required
    }
    if not (payload["current_price"] and payload["scenarios"]):
        return {"error": "current_price + scenarios required"}
    try:
        return api_client.paid_call("derive_scenario_values", payload)
    except Exception as e:
        return {"error": str(e)}


async def tool_subscribe_alerts(args: dict) -> dict:
    """PAID: persistent subscription. Charges on each alert delivered."""
    payload = {
        "ticker": args.get("ticker", "").upper(),
        "email": args.get("email"),
        "slack_webhook": args.get("slack_webhook"),
        "alert_on": args.get("alert_on") or [
            "verdict_changes", "kill_fires", "narrative_shifts"
        ],
    }
    if not payload["ticker"] or (not payload["email"] and not payload["slack_webhook"]):
        return {"error": "ticker + at least one of email / slack_webhook required"}
    try:
        return api_client.paid_call("subscribe_alerts", payload)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# CHARGE LIFECYCLE — confirm or refund a pending hold
# ============================================================

async def tool_confirm_charge(args: dict) -> dict:
    """User happy with the result — release the hold and finalize the charge."""
    cid = args.get("charge_id")
    if not cid:
        return {"error": "charge_id required"}
    try:
        return api_client.confirm_charge(cid)
    except Exception as e:
        return {"error": str(e)}


async def tool_refund_charge(args: dict) -> dict:
    """User unhappy — release the hold without charging. Window: 24h."""
    cid = args.get("charge_id")
    if not cid:
        return {"error": "charge_id required"}
    reason = args.get("reason", "user dissatisfied")
    try:
        return api_client.refund_charge(cid, reason)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Server bootstrap
# ============================================================

TOOL_HANDLERS = {
    # FREE
    "validate_tree": tool_validate_tree,
    "aggregate_tree": tool_aggregate_tree,
    "commit_tree": tool_commit_tree,
    "read_tree": tool_read_tree,
    "suggest_framework": tool_suggest_framework,
    "balance": tool_balance,
    # PAID
    "register_narrative": tool_register_narrative,
    "enrich_branches": tool_enrich_branches,
    "suggest_falsification": tool_suggest_falsification,
    "derive_scenario_values": tool_derive_scenario_values,
    "subscribe_alerts": tool_subscribe_alerts,
    # CHARGE LIFECYCLE
    "confirm_charge": tool_confirm_charge,
    "refund_charge": tool_refund_charge,
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # FREE
        Tool(
            name="validate_tree",
            description=(
                "FREE. Validate a candidate Draw Tree v0.2 doc against the 9 protocol "
                "invariants. Returns errors + warnings. The server's commit_tree refuses "
                "to publish trees with errors."
            ),
            inputSchema={
                "type": "object", "required": ["tree"],
                "properties": {"tree": {"type": "object"}},
            },
        ),
        Tool(
            name="aggregate_tree",
            description=(
                "FREE. Compute leaf -> branch -> H-0 verdict, conviction (0-1), and "
                "expected return (if valuation present). Fibonacci-default branch "
                "weights unless overridden."
            ),
            inputSchema={
                "type": "object", "required": ["tree"],
                "properties": {"tree": {"type": "object"}},
            },
        ),
        Tool(
            name="commit_tree",
            description=(
                "FREE. Validate, aggregate, and publish a tree to drawtree-api. Default "
                "visibility is private. Returns version_hash + dashboard URL."
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
            description="FREE. Fetch the latest version of a tree by ticker.",
            inputSchema={
                "type": "object", "required": ["ticker"],
                "properties": {
                    "ticker": {"type": "string"},
                    "agent_handle": {"type": "string"},
                },
            },
        ),
        Tool(
            name="suggest_framework",
            description=(
                "FREE. Top-k framework names + categories from the 164-framework KB. "
                "For diagnostic questions, leaf seeds, and metric heuristics, call "
                "enrich_branches (PAID)."
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
            name="balance",
            description=(
                "FREE. Show current balance, pending holds, and last 20 charges."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),

        # PAID
        Tool(
            name="register_narrative",
            description=(
                "PAID (credits). Parse a narrative-detection 'Structured Handoff "
                "Block' and cross-reference the detected error type against the public "
                "fleet's narrative archetypes. Returns parsed handoff + suggested H-0 + "
                "matching fleet trees + their H-0 outcomes. Hold auto-confirms in 24h."
            ),
            inputSchema={
                "type": "object", "required": ["narrative_handoff_block"],
                "properties": {"narrative_handoff_block": {"type": "string"}},
            },
        ),
        Tool(
            name="enrich_branches",
            description=(
                "PAID (credits). Deep framework retrieval for each branch: "
                "top-3 frameworks from the 164-framework KB, plus diagnostic question "
                "seeds, leaf affinity, and metric heuristics. Hold auto-confirms in 24h."
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
                "PAID (credits). Returns observable kill conditions for a "
                "hypothesis, linked to standard metrics (NRR, gross margin, share, etc.) "
                "and disclosure triggers. Output is typed Falsification objects "
                "compatible with v0.2 schema."
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
            name="derive_scenario_values",
            description=(
                "PAID (credits). For each Bull/Base/Bear scenario the user defines, "
                "compute the implied scenario value using Peer Group Valuation + "
                "scenario-specific multiples, and report distance from current price as "
                "a percentage. Server provides peer hints from the fleet and method "
                "hints (EV/Sales, EV/EBITDA, P/E, P/FCF, DCF, …) — the user's Claude "
                "ultimately picks based on context."
            ),
            inputSchema={
                "type": "object",
                "required": ["tree", "current_price", "scenarios"],
                "properties": {
                    "tree": {"type": "object"},
                    "current_price": {"type": "number"},
                    "peer_group": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Optional. If omitted, server suggests from fleet.",
                    },
                    "valuation_method": {
                        "type": "string",
                        "description": (
                            "Optional, free text. Common values: EV/Sales, EV/EBITDA, "
                            "P/E, P/FCF, DCF, SOTP, DDM. Server returns method hints "
                            "regardless."
                        ),
                    },
                    "scenarios": {
                        "type": "object",
                        "required": ["bull", "base", "bear"],
                        "properties": {
                            "bull": {"type": "object"},
                            "base": {"type": "object"},
                            "bear": {"type": "object"},
                        },
                    },
                },
            },
        ),
        Tool(
            name="subscribe_alerts",
            description=(
                "PAID. Persistent subscription. Charge per delivered alert: credits"
                "for verdict change, credits credits."
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

        # CHARGE LIFECYCLE
        Tool(
            name="confirm_charge",
            description=(
                "Confirm a pending paid result you're satisfied with. Releases the "
                "hold and finalizes the charge. Holds auto-confirm in 24 hours."
            ),
            inputSchema={
                "type": "object", "required": ["charge_id"],
                "properties": {"charge_id": {"type": "string"}},
            },
        ),
        Tool(
            name="refund_charge",
            description=(
                "Refund a pending paid result you're unhappy with. Window: 24 hours "
                "after the call. Releases the hold without charging."
            ),
            inputSchema={
                "type": "object", "required": ["charge_id"],
                "properties": {
                    "charge_id": {"type": "string"},
                    "reason": {"type": "string"},
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
