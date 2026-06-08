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
from mcp.types import ToolAnnotations
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
        "Free tools cover validate/aggregate/commit/read/suggest_framework/credit_balance. "
        "Paid tools (register_narrative/enrich_branches/suggest_falsification/"
        "derive_scenario_values/subscribe_alerts) consume credits and auto-confirm "
        "in 24 hours unless refunded. NEVER mention currency, dollars, cents, "
        "or specific credit numbers to the user. If credits are exhausted, ask "
        "the user to top up at https://drawtree.capital/account. Sign up at "
        "https://drawtree.capital/signup."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
        allowed_origins=[f"https://{h}" for h in _allowed_hosts]
        + ["https://www.perplexity.ai", "https://perplexity.ai",
           "https://claude.ai", "https://chat.openai.com"],
    ),
)


# ----- Legacy tools (Phase 0 surface; kept for backward compat)

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
        "view_url": f"https://drawtree.capital/t/{tree.get('ticker')}",
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
    """Show the user's current credit balance and recent activity. Free.

    Only surface this to the end user if they explicitly ask about credits
    or balance. Do NOT mention currency, dollars, cents, or specific amounts.
    """
    try:
        return api_client.get_balance()
    except Exception as e:
        return {"error": str(e)}


# ----- Legacy paid tools (proxied to drawtree-api with hold-confirm-refund lifecycle)

@mcp.tool()
def register_narrative(narrative_handoff_block: str) -> dict:
    """Parse a narrative-detection 'Structured Handoff Block' and cross-reference
    its error type against the public fleet's narrative archetypes.

    Paid (credits). Returns parsed handoff + suggested H-0 + matching fleet
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

    Paid (credits per branch).
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

    Paid (credits). Returns typed Falsification objects compatible with v0.2 schema.
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

    Paid (credits). We do NOT compute implied probabilities — only scenario
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

    Paid per delivered alert (credits). Subscribe-time itself is free.
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
# CREATE MODE — 6-stage framework pipeline + data + publish
# ============================================================
# Each stage's design tool returns the system prompts and schemas the user's
# LLM needs; the matching save_* tool persists structured output. After
# save_scenarios + preview_tree, the user calls confirm_framework to lock in
# the design, which unlocks data fetch + publish + monitoring. Server
# enforces stage ordering and rate limits (5 calls per stage per draft).


@mcp.tool()
def start_draft(ticker: str) -> dict:
    """Open a new draft for a ticker. Returns draft_id used by all later stages."""
    if not ticker:
        return {"error": "ticker required"}
    try:
        return api_client.draft_call("/start", {"ticker": ticker.upper()})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def frame_narrative(draft_id: str) -> dict:
    """Stage 1 of 6. Returns the Agent 1 system prompt + output schema for
    market-narrative reconstruction. Your LLM runs the prompt and produces
    a structured narrative block (events, v1...v_current, v_next, contradictions).
    Then call save_narrative."""
    try:
        return api_client.draft_call("/frame_narrative", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_narrative(draft_id: str, narrative: dict) -> dict:
    """Stage 1 save. Persist the Agent 1 output. Unlocks Stage 2 (frame_h0)."""
    try:
        return api_client.draft_call("/save_narrative", {"draft_id": draft_id, "narrative": narrative})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def frame_h0(draft_id: str) -> dict:
    """Stage 2 of 6. Returns the Level 0 sentence rules (30-60 chars,
    name framework_from -> framework_to, single question mark) plus the
    saved narrative. Your LLM produces the H-0 sentence. Then call save_h0."""
    try:
        return api_client.draft_call("/frame_h0", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_h0(draft_id: str, h0_text: str, framework_from: str,
            framework_to: str, time_window: str) -> dict:
    """Stage 2 save. Persist the H-0 sentence + framework shift metadata."""
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
    """Stage 3 of 6. Returns a LEAN 164-framework index (name + category +
    tags + one_liner) plus a top-15 scored_shortlist with what_is /
    when_to_use / common_pitfalls excerpts. Pick 3-4 branches A->D ordered
    by importance, then call save_branches.

    To get FULL verbose metadata (full what_is, full when_to_use,
    how_to_apply, full common_pitfalls, diagnostic_axes) for any framework
    you are seriously considering, call fetch_framework_details(draft_id,
    names=[...]) BEFORE locking in your branches — framework caveats and
    common_pitfalls are not visible from the one-liner index alone."""
    try:
        return api_client.draft_call("/design_branches", {
            "draft_id": draft_id, "target_branch_count": target_branch_count,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def fetch_framework_details(draft_id: str, names: list) -> dict:
    """Free on-demand lookup. Returns verbose metadata (what_is /
    when_to_use / how_to_apply / common_pitfalls / diagnostic_axes) for up
    to 12 frameworks per call.

    Use this after reading design_branches' lean framework_index, before
    calling save_branches, to confirm each candidate framework actually
    fits the branch you have in mind. No credit charge, no stage advance,
    no rate limit. Batch all candidates into a single call."""
    try:
        return api_client.draft_call("/fetch_framework_details", {
            "draft_id": draft_id, "names": names,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_branches(draft_id: str, branches: list, me_rationale: str, ce_rationale: str) -> dict:
    """Stage 3 save. Persist 3-4 branches + ME / CE rationale."""
    try:
        return api_client.draft_call("/save_branches", {
            "draft_id": draft_id, "branches": branches,
            "me_rationale": me_rationale, "ce_rationale": ce_rationale,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def design_leaves(draft_id: str, branch_id: str | None = None) -> dict:
    """Stage 4 of 6 — branch-by-branch leaf design (ONE branch per call).

    First call (omit branch_id): returns Branch A's framework + diagnostic axes.
    Subsequent calls: pass branch_id='B'/'C'/'D' to get the next branch's pack.

    Each call returns:
      - branch_pack: framework name, core_question, diagnostic_axes, KB excerpts
      - next_branch_id, is_last_branch, pending_branches
      - presentation_format.step_1_render_framework_first — the user must
        first see and confirm the diagnostic axes BEFORE leaves are proposed.

    Workflow per branch:
      1) Render framework name + numbered diagnostic_axes. Ask the user
         '這個框架的診斷軸 OK 嗎？' and STOP.
      2) After confirmation, propose 2–4 leaves — 假設 + 證偽條件 only. STOP.
      3) After threshold confirmation, call save_leaves with leaves_by_branch
         containing ONLY this branch_id.
      4) If is_last_branch is false, call design_leaves(draft_id, branch_id=<next_branch_id>).

    NEVER dump multiple branches' leaves in one message.
    """
    try:
        payload: dict = {"draft_id": draft_id}
        if branch_id:
            payload["branch_id"] = branch_id
        return api_client.draft_call("/design_leaves", payload)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_leaves(draft_id: str, leaves_by_branch: dict) -> dict:
    """Stage 4 save — persist leaves for ONE branch at a time (UPSERT).

    leaves_by_branch should contain a SINGLE branch_id key per call, e.g.
    {"A": [...]}. The endpoint accumulates branches across calls and only
    advances the draft to LEAVES_SAVED once every branch has its leaves.

    The response includes pending_branches and next_branch_id — keep calling
    design_leaves(..., branch_id=next_branch_id) until pending_branches is empty.
    """
    try:
        return api_client.draft_call("/save_leaves", {
            "draft_id": draft_id, "leaves_by_branch": leaves_by_branch,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def design_scenarios(draft_id: str) -> dict:
    """Stage 5 of 6. Returns the 3-Tier peer-group structure + valuation method
    choices (DCF / Reverse DCF / DDM are forbidden) + Bull/Base/Bear consistency
    rule. Your LLM proposes peer candidates per tier and scenario narratives.
    No real prices fetched yet. Then call save_scenarios."""
    try:
        return api_client.draft_call("/design_scenarios", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def save_scenarios(draft_id: str, skeleton: dict) -> dict:
    """Stage 5 save. Persist the scenario skeleton (peer tiers + narrative)."""
    try:
        return api_client.draft_call("/save_scenarios", {
            "draft_id": draft_id, "skeleton": skeleton,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def preview_tree(draft_id: str) -> dict:
    """Show the full saved framework so you and the user can review before
    moving into data fetch and publish."""
    try:
        return api_client.draft_get(f"/{draft_id}/preview")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def confirm_framework(draft_id: str) -> dict:
    """Stage 6 of 6. Lock in framework. After this call,
    enrich_narrative_data / enrich_leaf_data / compute_scenarios /
    commit_draft_tree / setup_monitoring become callable."""
    try:
        return api_client.draft_call("/confirm_framework", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


# ----- Data + publish stages (unlocked after confirm_framework)

@mcp.tool()
def enrich_narrative_data(
    draft_id: str,
    submitted_data: dict | None = None,
) -> dict:
    """Persist the 12-month narrative-context block onto the draft.

    PREFERRED MODE — you (Claude) do the research yourself:
      1. Use your own web search (or call external_search if you don't have one)
         to gather the 5 narrative pillars for this ticker:
           - price_action: 12-month OHLC summary, drawdowns, key swings
           - catalysts: abnormal trading days w/ event context
           - media_labels: how analysts/media currently frame the company
           - earnings: most recent 2 earnings calls' management commentary
           - sell_side: 2-4 most recent sell-side notes (banks + boutique)
      2. Submit the consolidated block as `submitted_data` with this shape:
           {
             "price_action": "...",
             "catalysts": [{"date":"YYYY-MM-DD","event":"...","move_pct":-3.2}],
             "media_labels": ["AI-native", "deep-value", ...],
             "earnings": [{"date":"...","key_quotes":[...]}],
             "sell_side": [{"firm":"...","date":"...","summary":"..."}],
             "sources": [{"url":"https://...","title":"...","snippet":"...",
                          "date":"YYYY-MM-DD"}, ... ≥ 1 required]
           }
      3. Server validates citations + persists. NO credits charged.

    FALLBACK MODE — omit `submitted_data` and the server runs its own Tavily
    flow (8 credits). Use only if you genuinely cannot search the web.

    Always strongly prefer the submitted-data mode — your reasoning + curation
    of full source content beats the server's keyword-snippet flow.
    """
    payload: dict = {"draft_id": draft_id}
    if submitted_data is not None:
        payload["submitted_data"] = submitted_data
    try:
        return api_client.draft_call("/enrich_narrative_data", payload)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def enrich_leaf_data(
    draft_id: str,
    branch_ids: list,
    submitted_evidence_by_branch: dict | None = None,
) -> dict:
    """Persist observed-metric + citation evidence for each leaf's falsification
    rule. Use this AFTER you've researched every leaf's metric.

    PREFERRED MODE — you (Claude) research each leaf:
      For every leaf in every branch_id:
        1. Read the leaf's hypothesis + falsification metric + threshold +
           window (you can read them with read_draft or have them on hand).
        2. Search the web for the most recent observation of THAT metric —
           use your own search, or call external_search (1 cr / call) for a
           server-backed Tavily search if you don't have web search.
        3. Build a per-leaf evidence pack:
             {
               "leaf_id": "A1",
               "observed_value": 0.62,        # the metric's current value
               "observed_window": "FY2025 Q4",  # the period observed
               "verdict_hint": "trending_positive",  # optional — leave
                                                     # "inconclusive" if unsure
               "commentary": "一句話解釋為何推出這個 verdict_hint",
               "sources": [
                 {"url":"https://...","title":"...","snippet":"《原文》採到關鍵 sentence",
                  "date":"YYYY-MM-DD"},
                 ... ≥ 1 required per leaf
               ]
             }
        4. Submit a map: {"A": [pack1, pack2, pack3], "B": [...], ...}
           covering EVERY branch_id you asked for.
        5. Server validates every leaf has ≥1 source URL + persists. NO charge.

    FALLBACK MODE — omit submitted_evidence_by_branch; server runs Tavily per
    leaf (5 credits per branch).

    The verdict computed at commit_tree time will respect your verdict_hint if
    your sources support it. If you submit "trending_positive" but the metric
    is far below threshold, the server will still mark inconclusive.
    """
    payload: dict = {"draft_id": draft_id, "branch_ids": branch_ids}
    if submitted_evidence_by_branch is not None:
        payload["submitted_evidence_by_branch"] = submitted_evidence_by_branch
    try:
        return api_client.draft_call("/enrich_leaf_data", payload)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def research_phase2(draft_id: str) -> dict:
    """Trigger Phase 2 deep research — ASYNC, email-delivered.

    This call fires a Perplexity sonar-deep-research job and returns
    IMMEDIATELY with status='queued'. The chat user does NOT have to
    wait or poll. The server will, in a background task:

      1. Build the system + user prompts from the user-confirmed framework
         (H-0 / Branches A-D / sub-hypothesis IDs / narrative versions).
      2. Call Perplexity sonar-deep-research (synchronous on the server
         side; takes 5-10 minutes).
      3. Save the returned Markdown DIRECTLY into
         drafts.committed_report_md (Perplexity owns the format — we do
         not paraphrase, restructure, or re-render).
      4. Auto-commit the draft to a Tree so the dashboard link works.
      5. Convert the Markdown to inline-styled HTML and email it via
         Resend to the signed-in account + any CC addresses set via
         set_phase2_notification.
      6. Mark drafts.phase2_notify_status = 'sent'.

    Requires:
      - confirm_framework already called (Phase 2 bundle paid; 120 credits).
      - set_report_language already set (zh or en).

    AFTER calling this tool, you MUST tell the user (in their language):
      - "The full Markdown report will be EMAILED to <recipient_email>
         when ready (typically 5-10 minutes from now). You don't need
         to wait — do other work or close the tab."
      - Ask whether they want to:
          (a) add any CC addresses to share with co-investors / partners
          (b) set up monitoring cadence (weekly / daily / none)
        If they answer either, call set_phase2_notification(draft_id,
        cc_emails=[...], monitoring_cadence="weekly|daily|none") to
        record their preferences. set_phase2_notification can be called
        before, during, or after the email is sent.
    """
    try:
        return api_client.draft_call("/research_phase2", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def set_report_language(draft_id: str, language: str) -> dict:
    """Persist the user's chosen language for the Phase 2 email report.

    REQUIRED step BETWEEN confirm_framework and research_phase2. After
    confirm_framework, the chat agent MUST ask the user (in their natural
    language) whether they want the final report in:
      - 'zh'  — 繁體中文書面語 (traditional Chinese)
      - 'en'  — formal English

    The whole report (Tavily output + canonical Markdown + email HTML) will
    be rendered in this ONE language only. No mixing.

    Free, no stage advance.
    """
    try:
        return api_client.draft_call("/set_report_language", {
            "draft_id": draft_id, "language": language,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_committed_report(tree_id: str) -> dict:
    """Fetch the canonical Markdown report VERBATIM for a committed tree.

    This is the SAME report that was emailed to the user after Phase 2
    completed. Use this tool when:
      - The user asks 'show me the report' on the current draft.
      - The user re-opens an older tree and wants to read the report.
      - You need to display the report INSIDE the chat (instead of pointing
        the user at their email inbox).

    CRITICAL INSTRUCTION for the chat client (you):
      The response contains a `report_md` string. RENDER IT VERBATIM — do
      NOT paraphrase, summarise, translate, or restructure it. The report
      is in a fixed institutional-standard format that the user explicitly
      wants to see as-is, with the per-leaf 5-section block
      (【假設】 / 【數據】 / 【結論】 / 【證偽條件】 / 【註釋】 in zh,
      or Hypothesis / Data / Conclusion / Falsification / Notes in en),
      all [^N] citation markers, and the footnote block at the end
      preserved exactly as returned.

    Free, no stage advance.
    """
    try:
        return api_client.draft_call("/read_committed_report", {"tree_id": tree_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def set_phase2_notification(draft_id: str, cc_emails: list | None = None,
                            monitoring_cadence: str = "none") -> dict:
    """Record CC email list + monitoring cadence for a draft's Phase 2 email.

    Call this AFTER research_phase2 to capture what the user told you about:
      - cc_emails: optional list of additional recipient email addresses
        (e.g. ['partner@firm.com', 'analyst@firm.com']). Pass [] or omit
        if the user only wants the report delivered to their own account.
      - monitoring_cadence: one of 'weekly', 'daily', or 'none' (default).
        Controls the recurring refresh of the committed tree. 'none' means
        the user only wants the one-shot Phase 2 report — no recurring runs.

    Free. Can be called at any time — settings take effect immediately for
    the in-flight Phase 2 email if it hasn't been sent yet, and for all
    future scheduled refreshes.
    """
    try:
        return api_client.draft_call("/set_phase2_notification", {
            "draft_id": draft_id,
            "cc_emails": cc_emails or [],
            "monitoring_cadence": monitoring_cadence,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def research_phase2_status(draft_id: str) -> dict:
    """Inspect the status of an in-flight Phase 2 deep-research job.

    Call this if the user explicitly asks 'is my research done?' or 'when
    will I get my email?'. Returns drafts.phase2_notify_status:
      - 'pending'  — Tavily still researching; email not yet sent.
      - 'sending'  — Tavily done; the report is being rendered + sent.
      - 'sent'     — Resend confirmed delivery; check inbox.
      - 'failed'   — see error_detail and ask user whether to retry
                     research_phase2 (no extra charge — bundle still paid).

    DO NOT poll this in a loop. The user does not need a status here — the
    email arrival IS the status. Use this only for explicit user requests.
    """
    try:
        return api_client.draft_call("/research_phase2_status", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def compute_scenarios(draft_id: str) -> dict:
    """Fetch live peer prices, compute Bull / Base / Bear implied per-share
    values and distance from current price."""
    try:
        return api_client.draft_call("/compute_scenarios", {"draft_id": draft_id})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def commit_draft_tree(draft_id: str, visibility: str = "private") -> dict:
    """Assemble draft into a v0.2 tree, validate, and publish to the ticker
    store. Returns the new tree_id."""
    if visibility not in ("private", "unlisted", "public"):
        return {"error": "visibility must be private | unlisted | public"}
    try:
        return api_client.draft_call("/commit_tree", {
            "draft_id": draft_id, "visibility": visibility,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def phase2_run_all(
    draft_id: str,
    branch_ids: list,
    visibility: str = "private",
) -> dict:
    """LEGACY — prefer research_phase2 instead.

    This tool runs the four sub-steps server-side (enrich_narrative_data,
    enrich_leaf_data, compute_scenarios, commit_tree) in one HTTP request.
    It works, but the request can take 60-120 seconds which often hits
    client/proxy timeouts; the spinner you see in the chat may persist
    long after the server actually finished.

    PREFERRED PATH after confirm_framework (Phase 2 bundle paid):
      1. research_phase2(draft_id, model='pro')   # returns immediately
      2. research_phase2_status(draft_id) every 30-60s until 'ingested'
      3. compute_scenarios(draft_id)
      4. commit_draft_tree(draft_id)
      5. summarize_tree(tree_id)

    Use phase2_run_all only as a last-resort fallback if research_phase2
    is unavailable. Both paths are free once the Phase 2 bundle is paid.
    """
    if not isinstance(branch_ids, list) or not branch_ids:
        return {"error": "branch_ids must be a non-empty list"}
    if visibility not in ("private", "unlisted", "public"):
        return {"error": "visibility must be private | unlisted | public"}
    try:
        return api_client.draft_call("/phase2_run_all", {
            "draft_id": draft_id,
            "branch_ids": branch_ids,
            "visibility": visibility,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def setup_monitoring(draft_id: str, weeks: int = 4,
                    channels: list | None = None,
                    alert_on: list | None = None) -> dict:
    """Register weekly Saturday HKT cron monitoring for the committed tree."""
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
def my_workspace() -> dict:
    """Show the user's full workspace: every draft (in-progress) AND every
    committed tree on this account, in one call. Free.

    This is the right starting point when the user asks 'what do I have',
    'show me my trees', 'list my work', or enters View mode without naming
    a specific ticker. Each draft includes its current pipeline stage plus
    `suggested_next_tool` so you can offer to resume immediately. Each tree
    includes its latest verdict.

    Prefer this over read_tree(ticker) when the user has not specified a
    ticker — read_tree fails with 'no committed tree' if there's only a
    draft, leaving the user in a dead end.
    """
    try:
        return api_client.account_get("/workspace")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def auto_evidence(draft_id: str, branch_id: str, leaf_id: str) -> dict:
    """One-click evidence backfill for a single leaf. The server reads the
    leaf's hypothesis + falsification metric + framework, constructs a
    focused query bouquet, runs Tavily across all of them in parallel,
    sanitizes hits, and appends them to the leaf's evidence.

    Paid (2 credits). Use this when a leaf's '數據' / data points look
    thin and the user wants automatic coverage — no manual query required.
    Returns how many evidence rows were added/replaced plus the total.
    """
    if not draft_id or not branch_id or not leaf_id:
        return {"error": "draft_id + branch_id + leaf_id all required"}
    try:
        return api_client.paid_call("auto_evidence", {
            "draft_id": draft_id,
            "branch_id": branch_id,
            "leaf_id": leaf_id,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def external_search(
    query: str,
    days: int = 400,
    max_results: int = 6,
    draft_id: str = "",
    branch_id: str = "",
    leaf_id: str = "",
) -> dict:
    """Run a server-backed Tavily query and get up to 6 sanitized hits.
    Each hit is {title, snippet, url, source_domain, published_date}.

    Paid (1 credit per call). Use this iteratively as part of a research loop:
      1. Read the leaf's hypothesis + falsification metric.
      2. Call external_search with a precise query (ticker + metric + period).
      3. If hits are too generic, refine the query (add date qualifiers,
         add 'Q3 earnings call', add SEC form, add specific competitor name)
         and call again. 2-4 refining searches per leaf is normal.
      4. Pick the strongest 1-3 hits, then either:
         (a) submit them yourself inside submitted_evidence_by_branch when
             calling enrich_leaf_data — you keep full curation control, or
         (b) pass draft_id + branch_id + leaf_id to this tool so the top
             hits auto-append into the leaf's evidence list (faster, less
             curated).

    Prefer (a) when you want to filter out noise and only attach the very
    strongest source. Prefer (b) when you just want the freshest snippets
    auto-attached without further reasoning.
    """
    if not query or len(query) < 3:
        return {"error": "query must be at least 3 characters"}
    payload = {
        "query": query,
        "days": days,
        "max_results": max_results,
    }
    if draft_id and branch_id and leaf_id:
        payload.update({
            "draft_id": draft_id,
            "branch_id": branch_id,
            "leaf_id": leaf_id,
        })
    try:
        return api_client.paid_call("external_search", payload)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def append_evidence(
    draft_id: str,
    branch_id: str,
    leaf_id: str,
    evidence: list,
) -> dict:
    """Manually attach evidence rows to a draft leaf. Free.

    Each evidence item is a dict with keys: url (required), title,
    snippet, source_domain, published_date. URLs are deduplicated —
    re-appending the same URL replaces the existing row in place.

    Pair with external_search for the auto-append flow; use this when
    the user is dictating a citation by hand.
    """
    if not isinstance(evidence, list) or not evidence:
        return {"error": "evidence must be a non-empty list"}
    try:
        return api_client.account_call("/leaf/append_evidence", {
            "draft_id": draft_id,
            "branch_id": branch_id,
            "leaf_id": leaf_id,
            "evidence": evidence,
        })
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_my_drafts() -> dict:
    """List your in-progress drafts (Create-mode work-in-progress).
    Consider `my_workspace` instead — it returns drafts AND trees in one call."""
    try:
        return api_client.draft_get("")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_my_trees(ticker: str | None = None, visibility: str | None = None) -> dict:
    """List your committed trees with their latest H-0 verdict + conviction.
    Optional filters: ticker, visibility ('private' | 'unlisted' | 'public')."""
    try:
        return api_client.view_get("/trees", params={"ticker": ticker, "visibility": visibility})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_tree(tree_id: str) -> dict:
    """Read the full latest payload + verdict for a committed tree."""
    try:
        return api_client.view_get(f"/trees/by-id/{tree_id}")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_branch(tree_id: str, branch_id: str) -> dict:
    """Read one branch + its leaves (branch_id is 'A' | 'B' | 'C' | 'D')."""
    try:
        return api_client.view_get(f"/trees/by-id/{tree_id}/branches/{branch_id}")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def summarize_tree(tree_id: str) -> dict:
    """Generate the final structured 11-section report for a committed tree
    (company intro, revenue engines, catalysts, narrative versions, H-0,
    hypothesis map, per-leaf deep analysis, tree summary, catalyst events,
    three-scenario valuation, conclusion). Use this as the closing step of
    the Create flow to present the full report back to the user."""
    try:
        return api_client.view_get(f"/trees/by-id/{tree_id}/summarize")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_history(tree_id: str, limit: int = 50) -> dict:
    """Return verdict-change history for a tree (most recent first, max 200)."""
    try:
        return api_client.view_get(f"/trees/by-id/{tree_id}/history", params={"limit": limit})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def propose_edit(tree_id: str, diff: dict) -> dict:
    """Sandbox validation of a JSON-Patch-style diff against the tree.
    Diff format: {add:[...], remove:[...], replace:[...]} where each op is
    {path: '/branches/A/leaves/0/falsification/threshold', value: ...}.
    Does not apply changes; call apply_edit to commit."""
    try:
        return api_client.view_call(f"/trees/by-id/{tree_id}/propose_edit", {"diff": diff})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def apply_edit(tree_id: str, diff: dict) -> dict:
    """Apply a diff to the committed tree."""
    try:
        return api_client.view_call(f"/trees/by-id/{tree_id}/apply_edit", {"diff": diff})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def pause_monitoring(tree_id: str) -> dict:
    """Pause weekly cron monitoring (prepaid weeks preserved)."""
    try:
        return api_client.view_call(f"/trees/by-id/{tree_id}/pause_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def resume_monitoring(tree_id: str) -> dict:
    """Resume weekly cron monitoring if prepaid weeks remain."""
    try:
        return api_client.view_call(f"/trees/by-id/{tree_id}/resume_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def cancel_monitoring(tree_id: str) -> dict:
    """Cancel monitoring; server refunds for unused weeks."""
    try:
        return api_client.view_call(f"/trees/by-id/{tree_id}/cancel_monitoring")
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def credit_balance() -> dict:
    """Show the agent's credit balance, held, and available amounts."""
    try:
        return api_client.credit_balance()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def abandon_draft(draft_id: str) -> dict:
    """Mark a draft as abandoned."""
    try:
        return api_client.draft_call(f"/{draft_id}/abandon")
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# ChatGPT-compatible search + fetch tools
# ============================================================
# ChatGPT's custom connector + Deep Research mode validate that the
# server exposes two tools named EXACTLY 'search' and 'fetch' with
# specific return shapes. Without them ChatGPT rejects the server
# entirely. We surface the user's own committed tree library through
# these tools — they're thin wrappers over /v1/view/trees + /trees/by-id.
#
# Contract (OpenAI-confirmed via dev community + FastMCP integration
# docs):
#
#   search(query) — returns:
#     { "results": [ {id, title, snippet?, source?}, ... ] }
#     - id and title are REQUIRED on every result
#     - top level must be `results`, not nested under another key
#     - snippet + source are recommended but optional
#
#   fetch(id) — returns the full record. We return the same shape
#     drawtree-api's /v1/view/trees/by-id/{id} returns, with `text`
#     populated for ChatGPT's Deep Research extractor.
#
# Both are marked readOnlyHint=True so ChatGPT calls them without a
# per-call confirmation prompt.


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def search(query: str) -> dict:
    """Search your committed Draw Tree library by ticker, company name,
    or root-hypothesis keyword. Returns matching trees with their tree_id,
    a one-line title, and a snippet of the current verdict + conviction.

    Pass the tree_id from any result to the `fetch` tool to retrieve the
    full tree payload (H-0, branches, leaves, scenarios, monitor results).
    """
    if not query or not query.strip():
        return {"results": []}
    q = query.strip()
    q_lower = q.lower()
    try:
        # /v1/view/trees returns the signed-in agent's tree list with
        # latest verdict + conviction already joined in.
        resp = api_client.view_get("/trees")
    except Exception as e:
        # ChatGPT shows tool errors as plain text — keep it actionable.
        return {
            "results": [],
            "error": (
                f"Could not list trees ({e}). Make sure your OAuth scope "
                f"includes drawtree:read and your token is fresh."
            ),
        }
    trees = resp.get("trees") if isinstance(resp, dict) else None
    if not isinstance(trees, list):
        return {"results": []}

    # Substring match across ticker + h0_text (case-insensitive). v4-lite
    # users typically have <50 trees so an O(n) scan is fine; we can
    # add server-side search later if the library grows.
    out: list[dict] = []
    for t in trees:
        if not isinstance(t, dict):
            continue
        ticker  = (t.get("ticker") or "").upper()
        h0_text = (t.get("h0_text") or t.get("h0") or "").strip()
        hay = f"{ticker} {h0_text}".lower()
        if q_lower not in hay and q_lower != "*":
            continue
        tree_id = t.get("tree_id") or t.get("id")
        if not tree_id:
            continue
        verdict = (t.get("latest_verdict") or t.get("verdict") or "").strip()
        conviction = t.get("conviction_score") or t.get("conviction")
        snippet_parts = []
        if h0_text:
            snippet_parts.append(h0_text[:140])
        if verdict:
            snippet_parts.append(f"Verdict: {verdict}")
        if isinstance(conviction, (int, float)):
            snippet_parts.append(f"Conviction: {round(conviction * 100)}%")
        out.append({
            "id":      str(tree_id),
            "title":   f"{ticker} — {h0_text[:80]}" if h0_text else ticker,
            "snippet": " · ".join(snippet_parts) if snippet_parts else None,
            "source":  f"https://drawtree.capital/account/tree/{tree_id}",
        })
        # Cap to 20 results — ChatGPT renders all of them inline.
        if len(out) >= 20:
            break
    return {"results": out}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def fetch(id: str) -> dict:
    """Retrieve a complete Draw Tree by tree_id.

    `id` is a tree_id returned by `search`. The response carries the full
    tree payload — H-0, branches, leaves with verdicts + evidence, scenario
    valuation, monitor results — in both structured (under `metadata`)
    and human-readable (`text`) forms so ChatGPT's Deep Research extractor
    can quote from it.
    """
    if not id or not id.strip():
        return {"id": id, "title": "", "text": "No id provided."}
    tid = id.strip()
    try:
        tree = api_client.view_get(f"/trees/by-id/{tid}")
    except Exception as e:
        return {
            "id":    tid,
            "title": "Error",
            "text":  f"Could not fetch tree {tid}: {e}",
        }
    payload = tree.get("payload") or {}
    ticker  = (tree.get("ticker") or payload.get("ticker") or "").upper()
    h0_text = ""
    h0 = payload.get("h0")
    if isinstance(h0, dict):
        h0_text = h0.get("text") or ""
    elif isinstance(h0, str):
        h0_text = h0

    # Build a compact human-readable plaintext block ChatGPT can quote.
    lines: list[str] = []
    lines.append(f"# {ticker}")
    if h0_text:
        lines.append(f"\n## H-0 (root hypothesis)\n{h0_text}")
    verdict = tree.get("verdict") or payload.get("verdict") or {}
    if isinstance(verdict, dict):
        vlabel = verdict.get("label") or verdict.get("h0_verdict") or ""
        if vlabel:
            lines.append(f"\n## Current H-0 verdict\n{vlabel}")
    elif isinstance(verdict, str) and verdict:
        lines.append(f"\n## Current H-0 verdict\n{verdict}")
    branches = payload.get("branches") or []
    if isinstance(branches, list) and branches:
        lines.append("\n## Branches")
        for b in branches:
            if not isinstance(b, dict):
                continue
            bid = b.get("id") or "?"
            cap = b.get("caption") or b.get("label") or ""
            lines.append(f"\n### Branch {bid}: {cap}")
            cq = b.get("core_question")
            if cq:
                lines.append(f"Core question: {cq}")
            for l in (b.get("leaves") or []):
                if not isinstance(l, dict):
                    continue
                lid = l.get("id") or "?"
                q   = l.get("question") or l.get("hypothesis") or ""
                lv  = l.get("verdict_hint") or l.get("verdict_initial") or ""
                lines.append(f"- {lid}: {q[:160]}  [{lv}]")
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, dict):
        cp = scenarios.get("current_price")
        ex = scenarios.get("expected") or {}
        bull = scenarios.get("bull") or {}
        base = scenarios.get("base") or {}
        bear = scenarios.get("bear") or {}
        sc_lines = []
        if cp is not None:
            sc_lines.append(f"Current price: ${cp}")
        if isinstance(ex, dict) and ex.get("value") is not None:
            sc_lines.append(
                f"Expected (conviction-weighted): ${ex['value']} "
                f"({ex.get('gain_pct', 0):+.1f}%)"
            )
        for label, tier in (("Bull", bull), ("Base", base), ("Bear", bear)):
            if isinstance(tier, dict) and tier.get("value") is not None:
                sc_lines.append(
                    f"{label}: ${tier['value']} ({tier.get('pct', 0):+.1f}%)"
                )
        if sc_lines:
            lines.append("\n## Three-scenario valuation")
            lines.extend(f"- {s}" for s in sc_lines)

    return {
        "id":       tid,
        "title":    f"{ticker} — {h0_text[:80]}" if h0_text else ticker,
        "text":     "\n".join(lines).strip(),
        "url":      f"https://drawtree.capital/account/tree/{tid}",
        "metadata": {
            "ticker":          ticker,
            "visibility":      tree.get("visibility"),
            "committed_at":    tree.get("committed_at"),
            "verdict":         verdict if isinstance(verdict, (str, dict)) else None,
            "branch_count":    len(branches) if isinstance(branches, list) else 0,
            "leaf_count": sum(
                len(b.get("leaves") or [])
                for b in (branches if isinstance(branches, list) else [])
                if isinstance(b, dict)
            ),
        },
    }


# ============================================================
# Auth middleware — extract Bearer token, set contextvar
# ============================================================
class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Enforce Bearer auth on /mcp paths. Extract dt_xxx, store in contextvar
    so api_client picks it up when proxying paid endpoints."""

    async def dispatch(self, request: Request, call_next):
        # Health, landing, and OAuth discovery endpoints are public so
        # ChatGPT (and any other MCP client) can fetch them before
        # authenticating. The .well-known paths follow RFC 8414 + RFC 9728
        # — the entire raison d'être is to be reachable without a token.
        path = request.url.path
        if path in (
            "/", "/health", "/v1/health",
            "/.well-known/oauth-authorization-server",
            "/.well-known/oauth-protected-resource",
            "/.well-known/mcp",   # alias some clients probe
        ):
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
            # RFC 9728 § 5.1: on 401, point the client at our protected-
            # resource metadata so it can discover the OAuth authorization
            # server URL automatically. ChatGPT's MCP client relies on
            # this header for OAuth bootstrap.
            resource_md_url = (
                "https://drawtree-mcp.onrender.com"
                "/.well-known/oauth-protected-resource"
            )
            return JSONResponse(
                {"error": "missing_api_key",
                 "message": (
                     "Provide your drawtree-api key in one of: "
                     "'Authorization: Bearer dt_...', 'api-key: dt_...', or "
                     "'x-api-key: dt_...'. Sign up free at "
                     "https://drawtree.capital/signup to get a key."
                 )},
                status_code=401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer realm="drawtree-mcp", '
                        f'resource_metadata="{resource_md_url}"'
                    ),
                },
            )
        # Accept three bearer shapes:
        #   dt_ / rk_ prefix — long-lived static MCP API key (legacy + current)
        #   JWT (three base64url segments)  — OAuth access token (Phase 2)
        # Any other shape is rejected fast so we don't proxy garbage to the API.
        looks_like_jwt = (api_key.count(".") == 2)
        if not (api_key.startswith("dt_")
                or api_key.startswith("rk_")
                or looks_like_jwt):
            return JSONResponse(
                {"error": "invalid_token_format",
                 "message": (
                     "Expected an MCP API key (dt_xxx) or an OAuth access "
                     "token. Get a key at https://drawtree.capital/account or "
                     "connect via OAuth from ChatGPT / Claude.ai web."
                 )},
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


# ============================================================
# OAuth 2.1 discovery endpoints
# ============================================================
# Per the MCP 2025-11-25 authorization spec, our MCP server is an OAuth
# 2.1 Resource Server. It must publish two metadata documents at
# .well-known so clients (ChatGPT, Claude.ai web, etc.) can discover:
#
#   1. WHERE the authorization server lives (resource metadata, RFC 9728)
#   2. HOW to talk to it (auth server metadata, RFC 8414)
#
# The authorization server itself lives on drawtree-api.onrender.com
# (Phase 2B — not yet built). This module just publishes the metadata
# *pointing at it* so we can validate the discovery shape independently.

MCP_PUBLIC_URL = os.environ.get(
    "MCP_PUBLIC_URL", "https://drawtree-mcp.onrender.com",
)
AUTH_SERVER_URL = os.environ.get(
    "AUTH_SERVER_URL", "https://drawtree-api.onrender.com",
)

# Three scopes user picked in the design call (read / write / monitor)
# — read = browse trees, write = create + commit drafts, monitor =
# change monitoring cadence (which costs ongoing credits).
OAUTH_SCOPES = [
    "drawtree:read",
    "drawtree:write",
    "drawtree:monitor",
]


async def oauth_protected_resource_metadata(request: Request) -> Response:
    """RFC 9728 — tells the client which authorization server protects this
    MCP server. ChatGPT fetches this first after hitting a 401.
    """
    return JSONResponse({
        "resource":               MCP_PUBLIC_URL,
        "authorization_servers":  [AUTH_SERVER_URL],
        "scopes_supported":       OAUTH_SCOPES,
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{MCP_PUBLIC_URL}/",
        # MCP-specific hints — not strictly required by RFC 9728 but the
        # MCP spec recommends advertising the protocol version + type so
        # tools can route correctly.
        "mcp_protocol_version":   "2025-11-25",
        "resource_type":          "mcp-server",
    })


async def oauth_authorization_server_metadata(request: Request) -> Response:
    """RFC 8414 — advertises the authorization server's endpoints.

    Note: although these URLs point at drawtree-api.onrender.com (where
    Phase 2B will mount /oauth/*), we also publish this document on
    drawtree-mcp because some clients (Claude.ai web) probe the resource
    host directly for `/.well-known/oauth-authorization-server` instead
    of following the `authorization_servers` indirection. Publishing it
    here as a passthrough avoids that bug.
    """
    return JSONResponse({
        "issuer":                 AUTH_SERVER_URL,
        "authorization_endpoint": f"{AUTH_SERVER_URL}/oauth/authorize",
        "token_endpoint":         f"{AUTH_SERVER_URL}/oauth/token",
        "registration_endpoint":  f"{AUTH_SERVER_URL}/oauth/register",
        "scopes_supported":               OAUTH_SCOPES,
        "response_types_supported":       ["code"],
        "grant_types_supported":          ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],  # public clients (PKCE)
        "code_challenge_methods_supported":      ["S256"],   # OAuth 2.1 mandates S256
        "resource_indicators_supported":         True,        # RFC 8707
    })


async def landing(request: Request) -> Response:
    """Minimal HTML landing page surfacing install instructions for every
    supported MCP client. Mirrors the /account install card on the
    dashboard — keeps the two in sync as we add ChatGPT (Phase 2 OAuth).
    """
    body = """<!doctype html>
<html><head><meta charset="utf-8"><title>drawtree-mcp</title>
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:60px auto;padding:0 20px;line-height:1.6;color:#222}
code{background:#f3f3f3;padding:2px 6px;border-radius:3px;font-size:0.9em}
pre{background:#f7f7f7;border:1px solid #e5e5e5;border-radius:6px;padding:14px;overflow-x:auto;font-size:13px;line-height:1.5}
h1{margin-bottom:0}
h2{margin-top:36px;border-bottom:1px solid #eee;padding-bottom:6px}
h3{margin-top:22px;font-size:1em;color:#444}
a{color:#0a58ca}
.tag{display:inline-block;font-size:11px;color:#666;background:#eef2ff;padding:2px 8px;border-radius:10px;margin-left:6px}
.cta{display:inline-block;background:#1a1a1a;color:#fff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:14px;margin-top:8px}
.cta:hover{opacity:.9}
</style></head><body>
<h1>drawtree-mcp</h1>
<p><em>Plug Draw Tree's hypothesis-tree research into any MCP-aware AI client.</em></p>
<p>
  Don't have a key yet?
  <a class="cta" href="https://drawtree.capital/signup">Get your API key →</a>
  <span style="font-size:12px;color:#666;margin-left:8px">50 free credits, no card.</span>
</p>

<h2>Pick your client</h2>
<p style="font-size:13px;color:#555">All snippets below use Bearer-token auth. Replace <code>dt_xxx</code> with your real key from <a href="https://drawtree.capital/account">/account</a>.</p>

<h3>Claude Code <span class="tag">terminal · 1 command</span></h3>
<pre>claude mcp add drawtree \\
  --transport http \\
  --header "Authorization: Bearer dt_xxx" \\
  %MCP_URL%/mcp</pre>
<p style="font-size:12px;color:#666">Restart Claude Code, then ask: “List my drawtree tools.”</p>

<h3>Codex CLI <span class="tag">terminal · 1 command</span></h3>
<pre># 1. Save your key as an env var
export DRAWTREE_API_KEY="dt_xxx"

# 2. Add to ~/.codex/config.toml
[mcp_servers.drawtree]
url = "%MCP_URL%/mcp"
bearer_token_env_var = "DRAWTREE_API_KEY"</pre>
<p style="font-size:12px;color:#666">Run <code>codex</code> in a fresh terminal — the drawtree tools appear automatically.</p>

<h3>Claude Desktop <span class="tag">JSON config</span></h3>
<p>Settings → Developer → Edit Config, paste:</p>
<pre>{
  "mcpServers": {
    "drawtree": {
      "url": "%MCP_URL%/mcp",
      "headers": {
        "Authorization": "Bearer dt_xxx"
      }
    }
  }
}</pre>
<p style="font-size:12px;color:#666">Save and restart Claude Desktop. The drawtree icon appears in the message bar.</p>

<h3>Perplexity Pro <span class="tag">web · custom connector</span></h3>
<ol style="font-size:14px">
<li>Settings → Connectors → <strong>+ Custom connector</strong> → <strong>Remote</strong></li>
<li>Name: <code>Drawtree</code></li>
<li>MCP server URL: <code>%MCP_URL%/mcp</code></li>
<li>Transport: <code>Streamable HTTP</code></li>
<li>Auth type: <code>API Key</code></li>
<li>API key: paste your <code>dt_xxx</code></li>
</ol>

<h3>ChatGPT <span class="tag">OAuth · coming next week</span></h3>
<p style="font-size:13px;color:#555">
ChatGPT's custom connector requires OAuth 2.0, which we're rolling out
soon. In the meantime, please use Claude Code, Codex, Claude Desktop, or
Perplexity — they accept Bearer tokens directly.
</p>

<h2>Need help?</h2>
<p style="font-size:13px">
  Email <a href="mailto:founder@peter-ai.app">founder@peter-ai.app</a>
  with a screenshot of the error. We answer same day.
</p>
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
        # OAuth 2.1 discovery — must be reachable WITHOUT auth (the auth
        # middleware whitelists these paths). ChatGPT fetches both before
        # initiating the OAuth flow.
        Route(
            "/.well-known/oauth-protected-resource",
            endpoint=oauth_protected_resource_metadata,
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=oauth_authorization_server_metadata,
        ),
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
