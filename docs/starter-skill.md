---
name: drawtree-starter
description: Build a falsifiable Draw Tree for any stock ticker using the drawtree MCP. Two modes — Create (six-stage framework-design pipeline → data fetch → publish) and View (read / edit committed trees). Loads when the user asks to analyze, structure, falsify, or monitor a thesis on a public company.
---

# Drawtree

The drawtree MCP exposes ~30 tools across **Create** and **View** modes. Server enforces stage order — calling out-of-order returns `STAGE_LOCKED`. Each `frame_*` / `design_*` tool returns the system prompt + schema your LLM needs to produce structured output; then call the matching `save_*`.

## Create mode

Six framework stages → `confirm_framework` → data fetch → publish.

`start_draft(ticker)` → `frame_narrative` / `save_narrative` → `frame_h0` / `save_h0` → `design_branches` / `save_branches` → `design_leaves` / `save_leaves` → `design_scenarios` / `save_scenarios` → `preview_tree` → `confirm_framework`.

After confirm: `enrich_narrative_data` → `enrich_leaf_data(branch_ids)` → `compute_scenarios` → `commit_draft_tree(visibility)` → `setup_monitoring(weeks)`.

Workflow rules:
- Preserve the user's terminology where it exists.
- If sources conflict, add an open-questions entry instead of guessing.
- Confirm before any data/publish step — the user may want to revise the framework first.

## View mode

`list_my_drafts` (in-progress) · `list_my_trees` (committed) · `read_tree(tree_id)` · `read_branch(tree_id, branch_id)` · `read_history(tree_id)` · `propose_edit(tree_id, diff)` (sandbox) · `apply_edit(tree_id, diff)` · `pause_monitoring` · `resume_monitoring` · `cancel_monitoring`.

## Account

`credit_balance` shows the agent's available credits. Charges hold first and auto-confirm in 24h; `refund_charge(charge_id)` issues a refund within that window. `abandon_draft` discards an in-progress draft.
