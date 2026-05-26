"""Thin client for drawtree-api — wraps publish / read / list / subscribe.

Configured via env vars set in Claude Desktop's MCP server config:
    DRAWTREE_API_URL  default https://drawtree-api.onrender.com
    DRAWTREE_API_KEY  required for any mutation tool

This module is intentionally synchronous — MCP servers run requests serially
per session, async overhead is not justified.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _base_url() -> str:
    return os.environ.get("DRAWTREE_API_URL", "https://drawtree-api.onrender.com").rstrip("/")


def _api_key() -> str | None:
    return os.environ.get("DRAWTREE_API_KEY")


def _http(method: str, path: str, body: dict | None = None, auth: bool = False) -> dict:
    url = f"{_base_url()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if auth:
        key = _api_key()
        if not key:
            raise RuntimeError(
                "DRAWTREE_API_KEY not set — register via "
                "POST /v1/agents and add the key to your MCP server env."
            )
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8") if e.fp else ""
        try:
            err = json.loads(body_text)
        except Exception:
            err = {"detail": body_text}
        raise RuntimeError(f"API {e.code}: {json.dumps(err)[:600]}")


def publish(tree: dict) -> dict:
    return _http("POST", "/v1/trees", body=tree, auth=True)


def read_tree(ticker: str, agent_handle: str | None = None) -> dict:
    q = f"?agent_handle={agent_handle}" if agent_handle else ""
    return _http("GET", f"/v1/trees/{ticker}{q}")


def list_trees(limit: int = 200) -> list[dict]:
    out = _http("GET", f"/v1/trees?limit={limit}")
    return out.get("trees", [])


def diff_versions(ticker: str, from_hash: str, to_hash: str | None = None,
                  agent_handle: str | None = None) -> dict:
    q = f"?from_hash={from_hash}"
    if to_hash:
        q += f"&to_hash={to_hash}"
    if agent_handle:
        q += f"&agent_handle={agent_handle}"
    return _http("GET", f"/v1/trees/{ticker}/diff{q}")


def open_dispute(ticker: str, body: dict) -> dict:
    return _http("POST", f"/v1/trees/{ticker}/disputes", body=body, auth=True)


# ----- Paid endpoints (Phase 2)

def paid_call(endpoint: str, payload: dict) -> dict:
    """Call a paid endpoint on drawtree-api. Server holds the charge until
    confirm or 24h auto-confirm."""
    return _http("POST", f"/v1/paid/{endpoint}", body=payload, auth=True)


def get_balance() -> dict:
    return _http("GET", "/v1/billing/balance", auth=True)


def confirm_charge(charge_id: str) -> dict:
    return _http("POST", f"/v1/billing/charges/{charge_id}/confirm", auth=True)


def refund_charge(charge_id: str, reason: str = "") -> dict:
    return _http(
        "POST",
        f"/v1/billing/charges/{charge_id}/refund",
        body={"reason": reason},
        auth=True,
    )


# ----- Draft / Create-mode endpoints (Phase 3)

def draft_call(path: str, body: dict | None = None, method: str = "POST") -> dict:
    """Generic call into /v1/drafts/* — every draft endpoint requires auth."""
    return _http(method, f"/v1/drafts{path}", body=body, auth=True)


def draft_get(path: str) -> dict:
    return _http("GET", f"/v1/drafts{path}", auth=True)


def credit_balance() -> dict:
    return _http("GET", "/v1/drafts/_credits/balance", auth=True)
