# drawtree-mcp

> **Turn an investment thesis into a falsifiable, signed, point-in-time graph — from one conversation.**

`drawtree-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server. It gives any
MCP-aware client (Claude Desktop, claude.ai, ChatGPT, Perplexity, Cursor, Continue, Goose, …) the tools
to build, value, publish and monitor a **Draw Tree**: a root question (H-0) decomposed into branches and
observable leaves, each with structured conditions that say in advance what would prove it wrong.

It is two things in one package:

1. **The protocol kernel** (`drawtree_mcp/_kernel/`, protocol **v0.3**) — the validator, the aggregator,
   the condition sweep, the verdict-change gate and the v0.2 → v0.3 migrator. Pure Python, no model
   calls, no network. It is the same code the maintainer's research fleet runs weekly (engine
   `tree_quant/4`, `h0-engine/1`), and the same code `drawtree-api` runs server-side (`core/`).
2. **A thin client for `drawtree-api`** — the draft (Create-mode) flow, the valuation gate, publishing
   with Ed25519 attestation, append-only versions, and weekly monitoring. The API holds the state; this
   server holds none.

Research tooling only. Nothing it produces is investment advice.

---

## What a conversation looks like

```
You:    CRWD. Build a tree.

Claude: (starter skill, Step 1) researches the industry, the company and the pricing pack; writes the
        400–700-character background brief; reconstructs the narrative versions
        → start_draft · frame_narrative · save_narrative

        (Step 2) answers the five questions with numbers, writes the scenario ladder, drafts the H-0
        (one question mark, ≤120 characters, 「而非」 naming the bear outcome), the necessary-condition
        path, 3–5 branches with frameworks, and leaves that pass the eight admission questions
        → frame_h0 · save_h0 · design_branches · fetch_framework_details · save_branches ·
          design_leaves · save_leaves · preview_tree
        ■ FRAMEWORK GATE — shows you the framework summary and stops.

You:    Approved.

Claude: → confirm_framework
        (Step 3) assembles the two decisions — the bear / bull ratios to consensus with their anchors,
        sourced inputs, assumptions and cross-check, and the bear / bull peer tiers — and runs the gate
        → evaluate_valuation (until no errors) · report_two_decisions
        ■ TWO-DECISION GATE — shows you the report and stops.

You:    Two decisions as reported.

Claude: → approve_decisions(reply verbatim) · research_phase2 · compute_scenarios · commit_draft_tree
        (Step 4) → summarize_tree, and writes the reader report: §1 industry → company → why now,
        §2 what it sells / how it charges / where the money goes / last quarter, §3 consensus,
        §4 price chart with narrative bands, the tree, per leaf 現時判斷 → 甚麼會推翻 → 推翻之後,
        the three scenarios against the price.
        → setup_monitoring?
```

Every week after that the server searches, judges each leaf separately from the evidence pool, drops
any verdict change that does not cite this week's evidence or rests on price alone, latches breached
conditions, and appends a signed version. `read_tree_state_at(tree_id, "2026-10-03T13:30:00Z")` shows
exactly what the tree said that day.

---

## Install

### Hosted (no install)

`https://drawtree-mcp.onrender.com/mcp` — add it as a remote MCP server or custom connector. OAuth
sign-in; Bearer API keys also accepted. This is the full surface (kernel + draft flow + valuation gate +
point in time + View mode + ChatGPT `search` / `fetch`).

### Local stdio server

Not on PyPI. Install from the repository:

```bash
pip install "git+https://github.com/hopakhei/drawtree-mcp.git"
# or: git clone … && cd drawtree-mcp && pip install -e .
```

Register an agent (free) and wire the key into your client:

```bash
curl -X POST https://drawtree-api.onrender.com/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"handle":"YOUR_HANDLE","display_name":"Your Name"}'
# → "api_key": "dt_…"  (shown once)
```

```json
{
  "mcpServers": {
    "drawtree": {
      "command": "drawtree-mcp",
      "env": {
        "DRAWTREE_API_URL": "https://drawtree-api.onrender.com",
        "DRAWTREE_API_KEY": "dt_REPLACE_WITH_YOUR_KEY"
      }
    }
  }
}
```

Step-by-step, with troubleshooting: [`docs/CLAUDE_DESKTOP_SETUP.md`](docs/CLAUDE_DESKTOP_SETUP.md).

### The starter skill

Paste [`docs/starter-skill.md`](docs/starter-skill.md) into your Claude Project. It is the procedure
(draw-tree v6: four steps, two human gates), the five questions, the eight leaf-admission questions and
the reader-text rules. The tools are designed around it.

---

## Tools

### stdio server (20 tools)

| Group | Tool | What it does |
|---|---|---|
| Kernel (free, zero model calls) | `validate_tree` | Protocol v0.3 checks: impact-grade branches, structured `conditions[]` with assessments (gates E1–E7), evidence-ledger vocabularies, reading guides; v0.2 docs get the 9 legacy invariants |
| | `aggregate_tree` | leaf → branch → H-0 verdict, conviction (additive log-odds), verdict-based and price-implied scenario probabilities, expected return, derivation certificate |
| | `migrate_tree` | v0.2 doc → v0.3 mechanically, plus the list of what the author must still supply |
| | `sweep_conditions` | deterministic deadline clock and breach latch; appends synthetic ledger rows |
| Valuation gate (free) | `evaluate_valuation` | rules R1–R12 on a `decisions` object: tier statistics, derived multiples, implied prices, R5 hard gate, base-tier fit, numerator gate, R12 re-basing; with branches, price-derived impact grades and the coverage rule |
| | `report_two_decisions` | evaluate and store; returns the §4.40 report for the human |
| | `approve_decisions` | record the human's reply verbatim; builds the schema-2.1 valuation document the commit attaches |
| Publish / read | `commit_tree` | aggregate locally, publish to drawtree-api, which validates with the same kernel, signs (Ed25519) and records a version |
| | `read_tree` | latest version by ticker |
| | `read_tree_versions` | append-only history: hash, signature, source, actor, time, key_kind |
| | `read_tree_state_at` | the tree as recorded at or before a cutoff |
| Frameworks | `suggest_framework` | top-k from the 164-framework knowledge base |
| Paid (credit-metered) | `register_narrative` `enrich_branches` `suggest_falsification` `derive_scenario_values` `subscribe_alerts` | server-side research helpers; `derive_scenario_values` refuses DCF / DDM |
| Account | `balance` `confirm_charge` `refund_charge` | credit lifecycle (holds auto-confirm after 24 h) |

### Hosted server

Everything above, plus the Create-mode draft flow (`start_draft` → `frame_*` / `save_*` →
`preview_tree` → `confirm_framework` → `research_phase2` → `compute_scenarios` → `commit_draft_tree` →
`summarize_tree`), `read_valuation_draft`, `read_tree_version`, `diff_tree_versions`, View mode
(`my_workspace`, `read_tree`, `read_branch`, `read_history`, `propose_edit`, `apply_edit`, monitoring
controls) and the `search` / `fetch` pair ChatGPT connectors require. Schemas are published through
`list_tools()`.

---

## Protocol v0.3 (2026-10-05)

See [`docs/PROTOCOL_v0.3.md`](docs/PROTOCOL_v0.3.md) for schema and formulas. In short:

- **Branch weight is derived, not authored.** Each branch carries an `impact_grade` (致命 2.5 / 重創 1.6 /
  明顯受損 0.9 / 輕微 0.4 / 邊緣 0.15) set by the price impact of its falsification consequence (≥25% /
  10–25% / 4–10% / 1–4% / <1% of price). The reversed-Fibonacci default is retired.
- **Kill thresholds are 2.0**, and `necessity_leaves` name the leaves whose falsification kills a branch.
- **Conviction is additive log-odds**: `logit(H0) = logit(0.40) + Σ w·(score/3)`, positive terms halved,
  clamped to [0.005, 0.95]; branch conviction `σ(logit(0.40) + 1.5·score)`.
- **Conditions are structured** (`cid, kind, metric, operator, threshold, unit, window, due, status`) with
  `condition_assessments[]`; gates E1–E7 are enforced by `validate_tree`.
- **Evidence is an append-only ledger** with closed `tier` and `impact` vocabularies; search-side sources
  carry a `source_tier` (primary / wire / trade / aggregator / other) and only primary or wire settle a
  condition alone.
- **Valuation is two decisions** (§4.40): numerator = consensus × ratio, multiple = tier median; the author
  decides the bear / bull ratios and tiers, the human approves, the server derives the rest and refuses
  DCF / DDM / reverse DCF.
- **Point in time**: every write appends a content-addressed, signed version with provenance; nothing is
  rewritten in place.

Acceptance test: `tests/test_protocol_v03.py::test_golden_crwd_matches_fleet_engine` — a real fleet
tree aggregates to exactly the fleet engine's `h0_score / h0_verdict / conviction / p_* / er_*`.

## What gets enforced

- `validate_tree` and the API's publish path run the **same validator**; a document that fails it is not
  persisted. v0.3 documents: 3–5 branches, at least one fatal layer (or a declared `no_fatal_layer`), a
  numerator-delivery branch, a numeric leaf on every fatal branch, grades equal to the price-derived
  grade, every condition assessed, no unaddressed breach, sourced dated evidence. v0.2 documents: the
  nine legacy invariants (acyclic graph, ≥1 falsification per leaf, observable regex, sourced claims,
  strict ids, closed verdict vocabulary, frozen baseline, narrative versions, weight bounds).
- The valuation gate refuses an infeasible R5, an undeclared base mismatch, an unre-based snapshot after
  2026-10-06, and any banned method.
- The weekly monitor drops a verdict change that cites no evidence from this week, quotes no real
  condition when entering the falsification zone, or rests on price alone; latched conditions cannot be
  talked back to `not_met`.
- Signing happens in `drawtree-api` with the operator's Ed25519 key; `key_kind` on every version says
  whether it was the operator key or an ephemeral development key.

## Architecture

```
  MCP client (Claude Desktop / claude.ai / ChatGPT / Perplexity / IDEs)
        │ MCP (stdio or Streamable HTTP)
        ▼
  drawtree-mcp                      stateless; kernel v0.3 (validate · aggregate · sweep · verdict gate ·
  (this repo)                       migrate) + framework KB + thin HTTP client
        │ HTTPS, Bearer dt_…
        ▼
  drawtree-api  (Render)            drafts · valuation gate R1–R12 · weekly monitor · Ed25519 signing ·
        │                           append-only tree_versions · Postgres (Neon)
        ▼
  drawtree-dashboard  (Vercel)      reads the API
```

## Deployment

- Hosted MCP: Render Blueprint [`deploy/render-mcp.yaml`](deploy/render-mcp.yaml) (`Dockerfile.http`),
  auto-deploys from `main`; env `DRAWTREE_API_URL`, optional `ALLOWED_HOSTS`.
- CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — both transports import, advertise the
  kernel tools, and the golden test passes on Python 3.11 and 3.12.

## License

MIT. The protocol is open. The hosted instance is operated by the maintainer.
