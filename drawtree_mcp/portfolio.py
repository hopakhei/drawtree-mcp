"""Portfolio sizing & rebalance tools (Phase 2).

Thin wrappers over the stateless compute backbone deployed in
drawtree-dashboard:

    POST {DASHBOARD_BASE}/api/portfolio/size-and-rebalance

The whole engine — Kelly -> Fundamental-Law correlation haircut -> position
cap -> cash fallback -> board-lot rounding + no-trade threshold — runs on
that endpoint. Nothing here re-implements the math; this module only shapes
requests and maps the caller's committed trees into engine `idea` objects.

Execution is agent-orchestrated and paper-first. This server never holds
broker credentials and never places trades: build_rebalance returns a
broker-native order list (trd_env defaults to SIMULATE) for the user's own
Futu / IBKR MCP to place after a preview-confirm.
"""
from __future__ import annotations

from typing import Any

from . import api_client


def _dig(obj: Any, *path: str) -> Any:
    """Safe nested lookup; returns None if any hop is missing."""
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def tree_to_idea(record: dict) -> dict | None:
    """Map a committed tree record to an engine idea (spec §Tool 1).

    Field paths:
        ticker            <- record.ticker
        current           <- record.tree.valuation.snapshot_price
        bull              <- record.tree.valuation.scenarios.bull.target_price
        bear              <- record.tree.valuation.scenarios.bear.target_price
        conviction        <- record.aggregation.conviction
        conviction_source <- "mcp"

    Returns None when the tree lacks the bull/bear targets the engine needs.
    """
    ticker = record.get("ticker")
    bull = _dig(record, "tree", "valuation", "scenarios", "bull", "target_price")
    bear = _dig(record, "tree", "valuation", "scenarios", "bear", "target_price")
    if not ticker or bull is None or bear is None:
        return None
    idea: dict[str, Any] = {
        "ticker": ticker,
        "bull": bull,
        "bear": bear,
        "conviction_source": "mcp",
    }
    current = _dig(record, "tree", "valuation", "snapshot_price")
    if current is not None:
        idea["current"] = current
    conviction = _dig(record, "aggregation", "conviction")
    if conviction is not None:
        idea["conviction"] = conviction
    return idea


def get_portfolio_ideas(tickers: list[str] | None = None) -> dict:
    """Pull the caller's committed trees and map them to engine ideas.

    `tickers` is an optional filter; default = all of the caller's trees.
    """
    skipped: list[dict] = []
    if tickers:
        records: list[dict] = []
        for t in tickers:
            sym = t.upper()
            try:
                records.append(api_client.read_tree(sym))
            except Exception as e:
                skipped.append({"ticker": sym, "reason": str(e)})
    else:
        try:
            records = api_client.list_my_trees()
        except Exception as e:
            return {"error": f"could not list your trees: {e}"}

    ideas: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        # Listing endpoints can return summaries without valuation/aggregation;
        # re-read the full tree so the field mapping has something to map.
        if _dig(rec, "tree", "valuation") is None and rec.get("ticker"):
            try:
                rec = api_client.read_tree(str(rec["ticker"]).upper())
            except Exception:
                pass
        idea = tree_to_idea(rec)
        if idea is None:
            skipped.append({
                "ticker": rec.get("ticker"),
                "reason": "missing bull/bear target_price in valuation.scenarios",
            })
        else:
            ideas.append(idea)
    return {"ideas": ideas, "skipped": skipped}


def size_portfolio(
    ideas: list[dict] | None = None,
    tickers: list[str] | None = None,
    params: dict | None = None,
    fetch_prices: bool = True,
) -> dict:
    """Compute target weights + correlation table (no execution)."""
    if ideas is None:
        if tickers:
            got = get_portfolio_ideas(tickers)
            if "error" in got:
                return got
            ideas = got["ideas"]
        else:
            return {"error": "provide `ideas` or `tickers`"}
    if not ideas:
        return {"error": "no ideas to size — none of the trees had bull/bear targets"}
    payload = {"ideas": ideas, "params": params or {}, "fetch_prices": fetch_prices}
    try:
        return api_client.size_and_rebalance(payload)
    except Exception as e:
        return {"error": str(e)}


def build_rebalance(
    ideas: list[dict],
    broker: str,
    nlv: float,
    positions: list[dict] | None = None,
    params: dict | None = None,
    trd_env: str = "SIMULATE",
) -> dict:
    """Same engine, with an execution block -> broker-native order list.

    Paper-first: trd_env defaults to SIMULATE and orders are PREVIEW only.
    """
    if not ideas:
        return {"error": "`ideas` required (run size_portfolio / get_portfolio_ideas first)"}
    if broker not in ("futu", "ibkr"):
        return {"error": "broker must be 'futu' or 'ibkr'"}
    if trd_env not in ("SIMULATE", "REAL"):
        return {"error": "trd_env must be 'SIMULATE' (paper) or 'REAL'"}
    payload = {
        "ideas": ideas,
        "params": params or {},
        "execution": {
            "broker": broker,
            "nlv": nlv,
            "positions": positions or [],
            "trd_env": trd_env,
        },
    }
    try:
        result = api_client.size_and_rebalance(payload)
    except Exception as e:
        return {"error": str(e)}
    if isinstance(result, dict):
        result["safety_note"] = (
            f"PREVIEW ONLY (trd_env={trd_env}). This server never places trades. "
            "Show the order list to the user, get explicit confirmation, then hand "
            "rebalance_command.orders to the user's Futu / IBKR MCP to place. Before "
            "any REAL order the user must unlock_trade (Futu) / disable read-only (IBKR)."
        )
    return result
