---
name: drawtree-starter
description: Build a falsifiable Draw Tree for any stock ticker using the drawtree-mcp tools. Loads when the user asks to analyze, structure, or falsify a thesis on a public company.
---

# Drawtree starter

You have 13 MCP tools from `drawtree`. A `tree` is JSON: `ticker`, one `h0` root, 1–4 `branches` (each with `core_question` and `weight`), `leaves` with `falsifications`.

## Workflow

1. **Frame H-0.** Ask for ticker + one-sentence thesis. Phrase H-0 as a falsifiable claim.
2. **Suggest frameworks.** `suggest_framework` (free). Pick 1–4 branches covering the thesis. Order A → D by importance.
3. **Enrich branches.** `enrich_branches` (paid, ~HKD $3/branch) with `{id, label, core_question}` for diagnostic questions and candidate leaves.
4. **Write leaves.** Each leaf is one observable claim under one branch. Cite the source. If sources conflict, do NOT guess — add an `open_questions` entry.
5. **Falsify leaves.** `suggest_falsification` (paid, ~HKD $2/leaf) for typed kill conditions (metric, operator, threshold, window).
6. **(Optional) Value scenarios.** `derive_scenario_values` (paid, ~HKD $10) with Bull / Base / Bear inputs.
7. **Validate.** `validate_tree` (free). Fix errors before committing.
8. **Aggregate + commit.** `aggregate_tree` (free) previews H-0 verdict + conviction. `commit_tree` (free) publishes. Default visibility `private`.
9. **(Optional) Subscribe.** `subscribe_alerts` for verdict changes, kill fires, shifts.

## Money

`balance` shows HKD balance + holds. Paid calls hold first; you confirm via `confirm_charge` or refund via `refund_charge` within 24 hours. Holds auto-confirm after 24h.

## Style

Preserve the user's terminology. Never invent numbers; if a source is missing, leave the leaf empty and log an open question.
