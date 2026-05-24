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
def read_tree(ticker: str, agent_handle: str | None = None) -> dict:
    """Fetch the latest version of a tree by ticker. Free."""
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
# Auth middleware — extract Bearer token, set contextvar
# ============================================================
class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Enforce Bearer auth on /mcp paths. Extract dt_xxx, store in contextvar
    so api_client picks it up when proxying paid endpoints."""

    async def dispatch(self, request: Request, call_next):
        # Health and discovery endpoints are public
        if request.url.path in ("/", "/health", "/v1/health"):
            return await call_next(request)

        # All other paths require auth
        authz = request.headers.get("authorization", "")
        if not authz.startswith("Bearer "):
            return JSONResponse(
                {"error": "missing_bearer_token",
                 "message": "Set 'Authorization: Bearer dt_...' with your "
                            "drawtree-api key. Register at https://drawtree-api.onrender.com."},
                status_code=401,
            )
        api_key = authz[len("Bearer "):].strip()
        if not api_key.startswith("dt_") and not api_key.startswith("rk_"):
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
# ============================================================
mcp_app = mcp.streamable_http_app()

app = Starlette(
    routes=[
        Route("/", endpoint=landing),
        Route("/health", endpoint=health),
        Route("/v1/health", endpoint=health),
        Mount("/mcp", app=mcp_app),
    ],
    middleware=[],
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
