"""HTTPS MCP server for Perplexity / ChatGPT / claude.ai web.

Exposes the same 13 tools as the stdio server, but over Streamable HTTP
transport so any remote-MCP-aware client can connect.

The auth model is:
  - Header: `Authorization: Bearer dt_xxxxxxxx`
  - The `dt_xxx` key IS the user's drawtree-api API key (same key the stdio
    server consumes via DRAWTREE_API_KEY env var)
  - We inject it into a per-request context so the proxied paid endpoints
    on drawtree-api charge the right agent's balance

Run with:
    uvicorn drawtree_mcp.http_server:app --host 0.0.0.0 --port 8000

Or as a module:
    python -m drawtree_mcp.http_server --port 8000
"""
from __future__ import annotations

import contextvars
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from . import api_client, framework_retrieval
from ._kernel.aggregation import aggregate, annotate_doc
from ._kernel.validate import validate as validate_v02


# ============================================================
# Per-request API key context — injected by middleware, consumed
# by api_client when making outbound calls to drawtree-api.
# ============================================================
_request_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "drawtree_request_api_key", default=None,
)


def _override_api_client_for_request():
    """Monkey-patch api_client to read from contextvar instead of env var.

    api_client._api_key() falls back to env if contextvar is unset, so the
    stdio server keeps working unchanged.
    """
    original = api_client._api_key

    def _from_request_or_env() -> str | None:
        return _request_api_key.get() or original()

    api_client._api_key = _from_request_or_env  # type: ignore[assignment]


_override_api_client_for_request()


# ============================================================
# FastMCP server setup
# ============================================================
# Allowed hosts/origins for DNS-rebinding protection. In production this
# server is reachable as drawtree-mcp.onrender.com and (later)
# mcp.drawtree.capital; we also accept the same via $ALLOWED_HOSTS env
# (comma-separated) so we can rotate without a code change.
_default_hosts = [
    "drawtree-mcp.onrender.com",
    "mcp.drawtree.capital",
    "localhost", "127.0.0.1",
]
_env_hosts = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
_allowed_hosts = list(dict.fromkeys(_default_hosts + _env_hosts))

mcp = FastMCP(
    "drawtree-mcp",
    instructions=(
        "Draw Tree MCP server — turn investment theses into falsifiable graphs. "
        "13 tools: 6 free (validate/aggregate/commit/read/suggest_framework/balance) "
        "+ 5 paid (register_narrative/enrich_branches/suggest_falsification/"
        "derive_scenario_values/subscribe_alerts) + 2 lifecycle (confirm_charge/"
        "refund_charge). Paid calls hold against your HKD balance and auto-confirm "
        "in 24 hours unless you refund. Get started by registering at "
        "https://drawtree-api.onrender.com or by importing your API key."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
        allowed_origins=[f"https://{h}" for h in _allowed_hosts]
        + ["https://www.perplexity.ai", "https://perplexity.ai",
           "https://claude.ai", "https://chat.openai.com"],
    ),
)


# ----- FREE tools

@mcp.tool()
def validate_tree(tree: dict) -> dict:
    """Validate a candidate Draw Tree v0.2 doc against the 9 protocol invariants.

    Free. Returns errors + warnings. commit_tree refuses to publish trees with errors.
    """
    rep = validate_v02(tree)
    return {
        "ok": len(rep.errors) == 0,
        "errors": [{"code": i.code, "path": i.path, "message": i.message} for i in rep.errors],
        "warnings": [{"code": i.code, "path": i.path, "message": i.message} for i in rep.warnings],
        "summary": (
            f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s) — "
            f"{'tree is publishable' if not rep.errors else 'NOT publishable; fix errors'}"
        ),
    }


@mcp.tool()
def aggregate_tree(tree: dict) -> dict:
    """Compute leaf -> branch -> H-0 verdict, conviction (0-1), expected return.

    Free. Fibonacci-default branch weights unless overridden.
    """
    return aggregate(tree)


@mcp.tool()
def commit_tree(tree: dict, visibility: str = "private") -> dict:
    """Validate, aggregate, and publish a tree to drawtree-api. Default private.

    Returns version_hash + dashboard URL.
    """
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


@mcp.tool()
def read_tree_by_ticker(ticker: str, agent_handle: str | None = None) -> dict:
    """Fetch the latest version of a tree by ticker (legacy). Free.
    For View-mode access by tree_id, use read_tree."""
    if not ticker:
        return {"error": "ticker required"}
    try:
        return api_client.read_tree(ticker.upper(), agent_handle)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def suggest_framework(query: str, top_k: int = 3) -> dict:
    """Top-k framework names + categories from the 164-framework KB.

    Free. For diagnostic questions, leaf seeds, and metric heuristics, call
    enrich_branches (paid).
    """
    if not query:
        return {"error": "query required"}
    results = framework_retrieval.search(query, top_k=top_k)
    return {
        "query": query,
        "results": results,
        "note": (
            "Names + categories only. Call enrich_branches (paid) for diagnostic "
            "questions and leaf seeds."
        ),
    }


@mcp.tool()
def balance() -> dict:
    """Show current HKD balance, pending holds, and last 20 charges. Free."""
    try:
        return api_client.get_balance()
    except Exception as e:
        return {"error": str(e)}


# ----- PAID tools (proxied to drawtree-api with hold-confirm-refund lifecycle)

@mcp.tool()
def register_narrative(narrative_handoff_block: str) -> dict:
    """Parse a narrative-detection 'Structured Handoff Block' and cross-reference
    its error type against the public fleet's narrative archetypes.

    Paid: ~HKD $2 hold. Returns parsed handoff + suggested H-0 + matching fleet
    trees with their H-0 outcomes. Hold auto-confirms in 24h.
    """
    if not narrative_handoff_block:
        return {"error": "narrative_handoff_block required"}
    try:
        return api_client.paid_call("register_narrative",
                                    {"handoff_block": narrative_handoff_block})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def enrich_branches(branches: list[dict]) -> dict:
    """Deep framework retrieval per branch: top-3 frameworks from the 164 KB,
    plus diagnostic question seeds + leaf affinity.

    Paid: ~HKD $3 per branch hold.
    Each branch must be {id, label, core_question}.
    """
    if not isinstance(branches, list) or not branches:
        return {"error": "branches must be a non-empty list of {id, label, core_question}"}
    try:
        return api_client.paid_call("enrich_branches", {"branches": branches})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def suggest_falsification(hypothesis_full: str, leaf_id: str = "") -> dict:
    """Observable kill conditions for a hypothesis, linked to standard metrics.

    Paid: ~HKD $2. Returns typed Falsification objects compatible with v0.2 schema.
    """
    if not hypothesis_full:
        return {"error": "hypothesis_full required"}
    try:
        return api_client.paid_call("suggest_falsification", {
            "hypothesis_full": hypothesis_full, "leaf_id": leaf_id,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def derive_scenario_values(
    tree: dict,
    current_price: float,
    scenarios: dict,
    peer_group: list[str] | None = None,
    valuation_method: str | None = None,
) -> dict:
    """For each Bull/Base/Bear scenario, compute target value + distance from
    current price as a percentage. Server provides peer hints + method hints.

    Paid: ~HKD $10. We do NOT compute implied probabilities — only scenario
    values vs current price.
    """
    if not (current_price and scenarios):
        return {"error": "current_price + scenarios required"}
    payload = {
        "tree": tree,
        "current_price": current_price,
        "peer_group": peer_group,
        "valuation_method": valuation_method,
        "scenarios": scenarios,
    }
    try:
        return api_client.paid_call("derive_scenario_values", payload)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def subscribe_alerts(
    ticker: str,
    email: str | None = None,
    slack_webhook: str | None = None,
    alert_on: list[str] | None = None,
) -> dict:
    """Subscribe to alerts when a tree's verdict changes, kill switch fires, or
    narrative shifts.

    Paid per delivered alert: HKD $0.50 verdict change, $2 kill switch, $1 shift.
    Subscribe-time itself is free.
    """
    if not ticker or (not email and not slack_webhook):
        return {"error": "ticker + at least one of email / slack_webhook required"}
    try:
        return api_client.paid_call("subscribe_alerts", {
            "ticker": ticker.upper(), "email": email,
            "slack_webhook": slack_webhook,
            "alert_on": alert_on or ["verdict_changes", "kill_fires", "narrative_shifts"],
        })
    except Exception as e:
        return {"error": str(e)}


# ----- LIFECYCLE tools

@mcp.tool()
def confirm_charge(charge_id: str) -> dict:
    """Confirm a pending paid result you're satisfied with. Releases the hold
    and finalizes the charge. Holds auto-confirm in 24h."""
    if not charge_id:
        return {"error": "charge_id required"}
    try:
        return api_client.confirm_charge(charge_id)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def refund_charge(charge_id: str, reason: str = "") -> dict:
    """Refund a pending paid result you're unhappy with. Window: 24h after the call."""
    if not charge_id:
        return {"error": "charge_id required"}
    try:
        return api_client.refund_charge(charge_id, reason)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# CREATE MODE — Framework design (all free) + paid data stages
# ============================================================
# These tools follow a strict 6-stage pipeline. Each stage's free design tool
# returns the system prompts and schemas the user's LLM needs; the matching
# save_* tool persists structured output. After save_scenarios + preview_tree,
# the user calls confirm_framework (free) to lock in the design — which
# unlocks the paid data tools. Server enforces stage ordering and rate limits
# (5 calls per stage per draft).


@mcp.tool()
def start_draft(ticker: str) -> dict:
    """Open a new draft for a ticker. Free. Returns draft_id used by all later stages."""
    if not ticker:
        return {"error": "ticker required"}
    try:
        return api_client.draft_call("/start", {"ticker": ticker.upper()})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def frame_narrative(draft_id: str) -> dict:
    """Stage 1 / 6 — FREE. Returns the Agent 1 system prompt + output schema for
    market-narrative reconstruction. Your LLM runs the prompt and produces
    a structured narrative block (events, v1...v_current, v_next, contradictions).
    Then call save_narrative."""
    try:
        return api_client.draft_call("/frame_narrative", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_narrative(draft_id: str, narrative: dict) -> dict:
    """Stage 1 save — FREE. Persist the Agent 1 output. Unlocks Stage 2 (frame_h0)."""
    try:
        return api_client.draft_call("/save_narrative", {"draft_id": draft_id, "narrative": narrative})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def frame_h0(draft_id: str) -> dict:
    """Stage 2 / 6 — FREE. Returns the Level 0 sentence rules (30-60 chars,
    name framework_from -> framework_to, single question mark) plus the
    saved narrative. Your LLM produces the H-0 sentence. Then call save_h0."""
    try:
        return api_client.draft_call("/frame_h0", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_h0(draft_id: str, h0_text: str, framework_from: str,
            framework_to: str, time_window: str) -> dict:
    """Stage 2 save — FREE. Persist the H-0 sentence + framework shift metadata."""
    try:
        return api_client.draft_call("/save_h0", {
            "draft_id": draft_id, "h0_text": h0_text,
            "framework_from": framework_from, "framework_to": framework_to,
            "time_window": time_window,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def design_branches(draft_id: str, target_branch_count: int = 4) -> dict:
    """Stage 3 / 6 — FREE. Returns 8 candidate frameworks (with kb_source +
    fits_layer) plus MECE rules. Your LLM picks 3-4 branches A->D ordered by
    importance. Then call save_branches."""
    try:
        return api_client.draft_call("/design_branches", {
            "draft_id": draft_id, "target_branch_count": target_branch_count,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_branches(draft_id: str, branches: list, me_rationale: str, ce_rationale: str) -> dict:
    """Stage 3 save — FREE. Persist 3-4 branches + ME / CE rationale."""
    try:
        return api_client.draft_call("/save_branches", {
            "draft_id": draft_id, "branches": branches,
            "me_rationale": me_rationale, "ce_rationale": ce_rationale,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def design_leaves(draft_id: str) -> dict:
    """Stage 4 / 6 — FREE. Returns per-branch diagnostic question packs + leaf schema +
    falsification rules (metric/operator/threshold/window must all be quantified).
    Your LLM produces 2-4 leaves per branch. Then call save_leaves."""
    try:
        return api_client.draft_call("/design_leaves", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_leaves(draft_id: str, leaves_by_branch: dict) -> dict:
    """Stage 4 save — FREE. Persist leaves keyed by branch id."""
    try:
        return api_client.draft_call("/save_leaves", {
            "draft_id": draft_id, "leaves_by_branch": leaves_by_branch,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def design_scenarios(draft_id: str) -> dict:
    """Stage 5 / 6 — FREE. Returns the 3-Tier peer-group structure + valuation method
    choices (DCF / Reverse DCF / DDM are forbidden) + Bull/Base/Bear consistency
    rule. Your LLM proposes peer candidates per tier and scenario narratives.
    No real prices fetched yet — that's the paid compute_scenarios step.
    Then call save_scenarios."""
    try:
        return api_client.draft_call("/design_scenarios", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_scenarios(draft_id: str, skeleton: dict) -> dict:
    """Stage 5 save — FREE. Persist the scenario skeleton (peer tiers + narrative)."""
    try:
        return api_client.draft_call("/save_scenarios", {
            "draft_id": draft_id, "skeleton": skeleton,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def preview_tree(draft_id: str) -> dict:
    """FREE. Show the full saved framework so you and the user can review
    before paying. Also surfaces the credit cost of each next paid stage."""
    try:
        return api_client.draft_get(f"/{draft_id}/preview")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def confirm_framework(draft_id: str) -> dict:
    """Stage 6 / 6 — FREE boundary. Lock in framework, unlock paid data stages.
    After this call, enrich_narrative_data / enrich_leaf_data / compute_scenarios /
    commit_tree / setup_monitoring become callable."""
    try:
        return api_client.draft_call("/confirm_framework", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


# ----- PAID data stages (unlocked after confirm_framework)

@mcp.tool()
def enrich_narrative_data(draft_id: str) -> dict:
    """PAID — 8 credits. Fetch 12-month OHLC, abnormal days, earnings call
    excerpts, sell-side notes, ETF membership and media-label frequencies;
    inject into the saved narrative block."""
    try:
        return api_client.draft_call("/enrich_narrative_data", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def enrich_leaf_data(draft_id: str, branch_ids: list) -> dict:
    """PAID — 5 credits per branch. Fetch metric time series + threshold validation
    for each leaf's falsification metric."""
    try:
        return api_client.draft_call("/enrich_leaf_data", {
            "draft_id": draft_id, "branch_ids": branch_ids,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def compute_scenarios(draft_id: str) -> dict:
    """PAID — 15 credits. Fetch live peer prices, compute Bull / Base / Bear
    implied per-share values and distance from current price."""
    try:
        return api_client.draft_call("/compute_scenarios", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def commit_draft_tree(draft_id: str, visibility: str = "private") -> dict:
    """PAID — 10 credits. Assemble draft into a v0.2 tree, validate, and
    publish to the ticker store. Returns the new tree_id."""
    if visibility not in ("private", "unlisted", "public"):
        return {"error": "visibility must be private | unlisted | public"}
    try:
        return api_client.draft_call("/commit_tree", {
            "draft_id": draft_id, "visibility": visibility,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def setup_monitoring(draft_id: str, weeks: int = 4,
                    channels: list | None = None,
                    alert_on: list | None = None) -> dict:
    """PAID — 5 credits per week (held upfront). Register weekly Saturday HKT cron
    monitoring for the committed tree."""
    try:
        return api_client.draft_call("/setup_monitoring", {
            "draft_id": draft_id, "weeks": weeks,
            "channels": channels or ["slack"],
            "alert_on": alert_on or ["verdict_changes", "kill_fires", "narrative_shifts"],
        })
    except Exception as e:
        return {"error": str(e)}


# ----- VIEW MODE

@mcp.tool()
def list_my_drafts() -> dict:
    """FREE. List your in-progress drafts (Create-mode work-in-progress)."""
    try:
        return api_client.draft_get("")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_my_trees(ticker: str | None = None, visibility: str | None = None) -> dict:
    """FREE. List your COMMITTED trees with their latest H-0 verdict + conviction.
    Optional filters: ticker, visibility ('private' | 'unlisted' | 'public')."""
    try:
        return api_client.view_get("/trees", params={"ticker": ticker, "visibility": visibility})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_tree(tree_id: str) -> dict:
    """FREE. Read the full latest payload + verdict for a committed tree."""
    try:
        return api_client.view_get(f"/trees/{tree_id}")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_branch(tree_id: str, branch_id: str) -> dict:
    """FREE. Read one branch + its leaves (branch_id is 'A' | 'B' | 'C' | 'D')."""
    try:
        return api_client.view_get(f"/trees/{tree_id}/branches/{branch_id}")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_history(tree_id: str, limit: int = 50) -> dict:
    """FREE. Return verdict-change history for a tree (most recent first, max 200)."""
    try:
        return api_client.view_get(f"/trees/{tree_id}/history", params={"limit": limit})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def propose_edit(tree_id: str, diff: dict) -> dict:
    """FREE sandbox. Validate a JSON-Patch-style diff against the tree and return
    the per-leaf cost estimate. Diff format: {add:[...], remove:[...], replace:[...]}
    where each op is {path: '/branches/A/leaves/0/falsification/threshold', value: ...}."""
    try:
        return api_client.view_call(f"/trees/{tree_id}/propose_edit", {"diff": diff})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def apply_edit(tree_id: str, diff: dict) -> dict:
    """PAID — 2 credits per leaf changed. Apply a diff to the committed tree."""
    try:
        return api_client.view_call(f"/trees/{tree_id}/apply_edit", {"diff": diff})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def pause_monitoring(tree_id: str) -> dict:
    """FREE. Pause weekly cron monitoring (weeks_prepaid preserved)."""
    try:
        return api_client.view_call(f"/trees/{tree_id}/pause_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def resume_monitoring(tree_id: str) -> dict:
    """FREE. Resume weekly cron monitoring if prepaid weeks remain."""
    try:
        return api_client.view_call(f"/trees/{tree_id}/resume_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def cancel_monitoring(tree_id: str) -> dict:
    """FREE. Cancel monitoring; server refunds unused-week credits."""
    try:
        return api_client.view_call(f"/trees/{tree_id}/cancel_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def credit_balance() -> dict:
    """FREE. Show credit balance / held / available (credit-only, no HKD)."""
    try:
        return api_client.credit_balance()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def abandon_draft(draft_id: str) -> dict:
    """FREE. Mark a draft as abandoned. Paid stages already shipped are not refunded."""
    try:
        return api_client.draft_call(f"/{draft_id}/abandon")
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# Auth middleware — extract Bearer token, set contextvar
# ============================================================
class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Enforce Bearer auth on /mcp paths. Extract dt_xxx, store in contextvar
    so api_client picks it up when proxying paid endpoints."""

    async def dispatch(self, request: Request, call_next):
        # Health and discovery endpoints are public
        if request.url.path in ("/", "/health", "/v1/health"):
            return await call_next(request)

        # Accept the key from any of these headers so we work with whatever
        # Custom Connector UI is offered (Perplexity API-Key mode lets the
        # user pick the header name; common conventions vary).
        api_key = None
        authz = request.headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            api_key = authz[7:].strip()
        if not api_key:
            api_key = (request.headers.get("api-key")
                       or request.headers.get("x-api-key")
                       or request.headers.get("apikey")
                       or "").strip() or None
        # Some clients pass it as a query param during initial discovery
        if not api_key:
            api_key = request.query_params.get("api_key") or None

        if not api_key:
            return JSONResponse(
                {"error": "missing_api_key",
                 "message": (
                     "Provide your drawtree-api key in one of: "
                     "'Authorization: Bearer dt_...', 'api-key: dt_...', or "
                     "'x-api-key: dt_...'. Register at "
                     "https://drawtree-api.onrender.com for an HKD $100 free credit."
                 )},
                status_code=401,
            )
        if not (api_key.startswith("dt_") or api_key.startswith("rk_")):
            return JSONResponse(
                {"error": "invalid_token_format",
                 "message": "Expected dt_xxx (drawtree-api key) prefix."},
                status_code=401,
            )
        token = _request_api_key.set(api_key)
        try:
            return await call_next(request)
        finally:
            _request_api_key.reset(token)


# ============================================================
# Health + landing
# ============================================================
async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "drawtree-mcp",
                         "version": "0.2.0", "transport": "streamable_http"})


async def landing(request: Request) -> Response:
    body = """<!doctype html>
<html><head><meta charset="utf-8"><title>drawtree-mcp</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:60px auto;padding:0 20px;line-height:1.6;color:#222}
code{background:#f3f3f3;padding:2px 6px;border-radius:3px}
h1{margin-bottom:0}h2{margin-top:32px;border-bottom:1px solid #eee;padding-bottom:6px}
a{color:#0a58ca}</style></head><body>
<h1>drawtree-mcp</h1>
<p><em>HTTPS MCP transport for the Draw Tree wire protocol.</em></p>
<h2>Connect from Perplexity Pro</h2>
<ol>
<li>Settings → Connectors → <strong>+ Custom connector</strong> → <strong>Remote</strong></li>
<li>Name: <code>Drawtree</code></li>
<li>MCP server URL: <code>%MCP_URL%/mcp</code></li>
<li>Transport: <code>Streamable HTTP</code></li>
<li>Auth type: <code>API Key</code></li>
<li>API key: paste your <code>dt_...</code> from drawtree-api</li>
</ol>
<h2>Connect from Claude Desktop</h2>
<p>Add to <code>claude_desktop_config.json</code>:</p>
<pre>{
  "mcpServers": {
    "drawtree": {
      "url": "%MCP_URL%/mcp",
      "headers": {
        "Authorization": "Bearer dt_..."
      }
    }
  }
}</pre>
<h2>Don't have a key yet?</h2>
<p><code>POST https://drawtree-api.onrender.com/v1/agents</code> &mdash; new accounts get HKD $100 free credit.</p>
</body></html>"""
    body = body.replace("%MCP_URL%", "https://drawtree-mcp.onrender.com")
    return Response(body, media_type="text/html")


# ============================================================
# Build the Starlette app
#
# FastMCP's streamable_http_app() mounts the transport at "/mcp" internally,
# so we mount it at "/" of our outer app — that way our public endpoint is
# https://.../mcp without an intervening 307 redirect from /mcp -> /mcp/.
# We add explicit /mcp and /mcp/ aliases to be robust against clients that
# follow trailing-slash conventions either way.
# ============================================================
mcp_app = mcp.streamable_http_app()

# Critical: propagate the FastMCP session-manager lifespan to the outer app,
# otherwise we hit "Task group is not initialized" on every /mcp request.
app = Starlette(
    routes=[
        Route("/", endpoint=landing),
        Route("/health", endpoint=health),
        Route("/v1/health", endpoint=health),
        Mount("/", app=mcp_app),
    ],
    middleware=[],
    lifespan=mcp_app.router.lifespan_context,
)
app.add_middleware(APIKeyAuthMiddleware)


def main():
    import argparse
    import uvicorn
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
