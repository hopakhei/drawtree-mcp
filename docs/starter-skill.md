---
name: drawtree-starter
description: Co-design a falsifiable Draw Tree for a stock ticker with the user, one stage at a time, using the drawtree MCP. Two modes — Create (stage-by-stage framework design then data fetch and publish) and View (read / edit committed trees). Loads when the user asks to analyze, structure, falsify, or monitor a thesis on a public company.
---

# Drawtree

drawtree is a **co-design workflow**, not a one-shot generator. You work one stage at a time: call a tool, present its output to the user in plain language, ask whether to refine or proceed, then call the next `save_*` only after the user confirms.

## Entry gate (ALWAYS run first)

When the user enters just a ticker:

1. Confirm the company name behind the ticker.
2. Ask the user: **Create mode** (new tree, starting with the 6-step 市場叙事考古) or **View mode** (look at trees you've already committed for this ticker)?
3. Only proceed after the user picks. Do NOT auto-start `start_draft`.

If Create → `start_draft(ticker)` then Phase 1. If View → call `my_workspace()` first to show the user every draft AND tree they have. From there, resume a draft (`suggested_next_tool` is in the response) or open a tree with `read_tree(tree_id)`. Only fall back to `list_my_trees(ticker=...)` / `read_tree` directly if the user has named a specific tree.

**Important:** never call `read_tree(ticker=...)` cold when the user just says "view mode" — if the ticker has only a draft (not yet committed), `read_tree` returns "no committed tree" and the user is stuck. `my_workspace()` always returns something.

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

1. Narrative — `frame_narrative` → `save_narrative`. Run the **full 6-step** Agent 1 process and show each step in order: 股價異動考古 / 五信號掃描 / 叙事版本時間線 / 股價×叙事圖表 / 矛盾檢測 / v_next 生成. Never skip to v_next — the user must see the analysis.
2. H-0 — `frame_h0` → `save_h0`. Draft one sentence, explain the framework shift.
3. Branches — `design_branches` → `save_branches`. 3-4 MECE branches driven by their framework.
4. Leaves — `design_leaves` → `save_leaves`. Each leaf in the 5-section block: 假設 / 數據 (with [^n] footnotes) / 結論 (6-state verdict) / 證偽條件 / 註釋. Do a brief evidence sweep before drafting thresholds.
5. Scenarios — `design_scenarios` → `save_scenarios`. Bull / Base / Bear peer tiers.
6. `preview_tree` → `confirm_framework`. Only confirm after the user approves the whole framework.

### Phase 2: Research and publish

After `confirm_framework` the pause-and-confirm pattern stops. `confirm_framework` charges a flat **50-credit Phase 2 bundle** — every downstream Phase 2 tool on this draft is then free.

**Preferred — server-side Tavily /research (one button, deep, free polling):**

1. **`research_phase2(draft_id)`** — server calls Tavily /research with a strict output schema covering the 5 narrative pillars + a per-leaf evidence pack for every branch. Returns instantly with a Tavily request_id.
2. **`research_phase2_status(draft_id)`** every 30-60s until `status='ingested'`. Typical total time: 30-120s.
3. **`compute_scenarios(draft_id)`** — server fetches live peer prices + computes Bull/Base/Bear.
4. **`commit_draft_tree(draft_id, visibility='private')`** — publish the tree.
5. **`summarize_tree(tree_id)`** — render the final 10-section report.

This is the default path. Tavily handles the iterative search + synthesis; no per-leaf prompting needed.

**Alternative — manual Claude-driven submission (skip if research_phase2 works):**

**Preferred — Claude-driven research (free, deeper):**

1. **Research the narrative yourself.** Use your own web search (or call `external_search` for a Tavily-backed query, 1 cr per call) to gather the 5 narrative pillars: price_action / catalysts / media_labels / earnings / sell_side. Read the actual sources, don't just skim snippets. Then call:
   ```
   enrich_narrative_data(
     draft_id,
     submitted_data = {
       price_action, catalysts, media_labels, earnings, sell_side,
       sources: [{url, title, snippet, date}, ...]  // ≥ 1 required
     }
   )
   ```
   Server validates citations + persists. **No credits charged.**

2. **Research each leaf's metric yourself.** For every branch_id, for every leaf, search for the observed value of its falsification metric within its window. Build per-leaf packs:
   ```
   enrich_leaf_data(
     draft_id, branch_ids,
     submitted_evidence_by_branch = {
       "A": [{leaf_id, observed_value, observed_window, verdict_hint,
              commentary, sources:[{url,title,snippet,date}]}, ...],
       "B": [...], ...
     }
   )
   ```
   Server validates every leaf has ≥ 1 source URL + persists. **No credits charged.**

3. **`compute_scenarios(draft_id)`** — server fetches live peer prices + computes Bull/Base/Bear (15 cr; this step uses Yahoo OHLC only, no Tavily).
4. **`commit_draft_tree(draft_id, visibility='private')`** — publish the tree (10 cr).
5. **`summarize_tree(tree_id)`** — render the final 10-section report.

Research loop tips:
  * 2–4 refining `external_search` queries per leaf is normal; stop early once you have one strong source.
  * If a source URL is paywalled, still include it — the audit trail matters.
  * `verdict_hint` is optional; leave "inconclusive" when sources don't clearly support a stronger state.

**Fallback — server-side Tavily batch (1-button mode):**

Use only if Claude cannot do its own research (rare). One call:
  * **`phase2_run_all(draft_id, branch_ids=[all saved branches], visibility='private')`** — server runs `enrich_narrative_data` (Tavily, 8 cr) + `enrich_leaf_data` (Tavily, 5 cr/branch) + `compute_scenarios` + `commit_tree`. Then `summarize_tree(tree_id)`.

If `phase2_run_all` returns `ok=false`, surface `failed_step` + `error_detail` and ask whether to retry that step alone (individual tools remain available) or abandon. Earlier steps are saved — retrying skips them.

After `summarize_tree` ask once whether to `setup_monitoring(weeks)`.

## View mode

Start with `my_workspace()` — returns drafts + trees together so the user sees every piece of work on their account in one screen. Then drill down with `read_tree(tree_id)` / `read_branch(tree_id, branch_id)` / `read_history(tree_id)` / `propose_edit(tree_id, diff)` (sandbox) / `apply_edit(tree_id, diff)` / `pause_monitoring` / `resume_monitoring` / `cancel_monitoring`. `list_my_drafts` and `list_my_trees(ticker=...)` remain available for targeted lookups.

## Account

`credit_balance` is available if the user asks. Otherwise do not surface balance, charges, or costs.
