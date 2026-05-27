---
name: drawtree-starter
description: Co-design a falsifiable Draw Tree for a stock ticker with the user, one stage at a time, using the drawtree MCP. Two modes — Create (stage-by-stage framework design then data fetch and publish) and View (read / edit committed trees). Loads when the user asks to analyze, structure, falsify, or monitor a thesis on a public company.
---

# Drawtree

drawtree is a **co-design workflow**, not a one-shot generator. You work one stage at a time: call a tool, present its output to the user in plain language, ask whether to refine or proceed, then call the next `save_*` only after the user confirms.

## Hard rules

1. **Never chain stages.** Each tool call is followed by user-facing prose and a question.
2. **Present, then ask.** After every `frame_*` / `design_*` call, summarise the result in the user's language and ask if they want to revise.
3. **Respect the response's `instructions_to_agent` field.** It tells you exactly when to STOP.
4. **Preserve the user's terminology.** Don't paraphrase.
5. **If sources conflict, add an open question.** Never guess.

## Create mode — two phases

### Phase 1: Framework co-design (pause-and-confirm at every stage)

`start_draft(ticker)` — confirm the ticker first.

For each stage: **call design tool → present in user's language → confirm → call save tool**.

1. Narrative — `frame_narrative` → `save_narrative`. Show v1...v_current and the v_next hypothesis.
2. H-0 — `frame_h0` → `save_h0`. Draft one sentence, explain the framework shift.
3. Branches — `design_branches` → `save_branches`. 3-4 MECE branches driven by their framework.
4. Leaves — `design_leaves` → `save_leaves`. Each leaf in the 5-section block: 假設 / 數據 (with [^n] footnotes) / 結論 (6-state verdict) / 證偽條件 / 註釋. Do a brief evidence sweep before drafting thresholds.
5. Scenarios — `design_scenarios` → `save_scenarios`. Bull / Base / Bear peer tiers.
6. `preview_tree` → `confirm_framework`. Only confirm after the user approves the whole framework.

### Phase 2: Batch execution (no pausing, single final stop)

After `confirm_framework` the pause-and-confirm pattern stops. Tell the user this once, then run end-to-end:

`enrich_narrative_data` → `enrich_leaf_data(all branch_ids)` → `compute_scenarios` → `commit_draft_tree(visibility)` → `summarize_tree(tree_id)`.

Present the full 11-section `summarize_tree` output to the user as the conclusion. Then ask once whether to `setup_monitoring(weeks)`.

## View mode

`list_my_drafts` / `list_my_trees` / `read_tree(tree_id)` / `read_branch(tree_id, branch_id)` / `read_history(tree_id)` / `propose_edit(tree_id, diff)` (sandbox) / `apply_edit(tree_id, diff)` / `pause_monitoring` / `resume_monitoring` / `cancel_monitoring`.

## Account

`credit_balance` is available if the user asks. Otherwise do not surface balance, charges, or costs.
