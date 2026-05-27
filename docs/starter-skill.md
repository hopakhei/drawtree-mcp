---
name: drawtree-starter
description: Build a falsifiable Draw Tree for any stock ticker using the drawtree MCP. Two modes — Create (six-stage framework-design pipeline that's free until you confirm, then paid data + publish) and View (read / edit committed trees). Loads when the user asks to analyze, structure, falsify, or monitor a thesis on a public company.
---

# Drawtree

You have ~30 tools from `drawtree`, organized into **Create** and **View** modes. Prices are in **credits** (new agents get 30 free). Framework design is always free; you only spend credits after the user confirms. Server enforces stage order — calling out-of-order returns `STAGE_LOCKED`.

## Create mode

Six free stages → `confirm_framework` → paid data → publish.

Free stages: `start_draft(ticker)` → `frame_narrative` / `save_narrative` → `frame_h0` / `save_h0` → `design_branches` / `save_branches` → `design_leaves` / `save_leaves` → `design_scenarios` / `save_scenarios` → `preview_tree` → `confirm_framework`.

Each `frame_*` / `design_*` returns the system prompt + output schema; your LLM produces structured output, then call matching `save_*`. Preserve the user's terminology. If sources conflict, add open questions instead of guessing.

Paid (after confirm):

| Tool | Cost |
|---|---|
| `enrich_narrative_data` | 8 cr |
| `enrich_leaf_data` | 5 cr / branch |
| `compute_scenarios` | 15 cr |
| `commit_draft_tree` | 10 cr |
| `setup_monitoring` | 5 cr / week |

## View mode (committed trees)

`list_my_drafts` · `read_tree(tree_id)` · `read_branch(tree_id, branch_id)` · `read_history(tree_id)` · `propose_edit(tree_id, diff)` (free sandbox) · `apply_edit(tree_id, diff)` (2 cr / leaf) · `pause_monitoring(tree_id)` · `resume_monitoring(tree_id)` · `cancel_monitoring(tree_id)` (prorate refund).

## Always free

`credit_balance` · `abandon_draft` · `preview_tree`.

## Money

`credit_balance` shows available credits. Paid calls hold first; auto-confirm in 24h. Refund via `refund_charge` within that window.
