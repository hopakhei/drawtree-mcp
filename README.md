# drawtree-mcp

> **Turn an investment hunch into a falsifiable, signed, queryable graph — in one Claude Desktop conversation.**

`drawtree-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that gives any MCP-aware AI client (Claude Desktop, Cursor, Continue, Goose, …) the tools to:

1. **Parse a market-narrative scan** into a structured H-0 root question (the [narrative-detection](https://drawtree.capital/methodology) skill output)
2. **Cross-reference your narrative against a public fleet** of seeded thesis trees — see how peers with the same narrative archetype have played out
3. **Suggest from a 164-framework KB** which strategy framework best fits each branch (Porter's Five Forces, VRIO, Network Effects Map, Real Options Valuation, …)
4. **Seed leaves** with curated framework-specific diagnostic questions
5. **Suggest typed falsification** kill conditions; v0.3 stores them as structured `conditions[]` (metric / operator / threshold / window)
6. **Validate** the tree against protocol v0.3 (impact-grade branches, structured conditions with assessments, evidence-ledger vocabularies, reading guides) — v0.2 docs still get the 9 legacy invariants
7. **Aggregate** leaf → branch → H-0 verdict, conviction (additive log-odds), verdict-based and price-implied scenario probabilities, expected return, derivation certificate
8. **Reverse-engineer** the market's implied probability distribution and identify the highest-leverage tension-point leaf
9. **Commit privately** to drawtree-api with Ed25519 attestation
10. **Subscribe to alerts** when a kill switch fires or narrative shifts

The server itself is **deterministic and contains zero LLM calls**. All thinking happens in your Claude. The server provides schema, retrieval, and persistence — your AI is the strategist.

---

## The Wow Moment

Open Claude Desktop with `drawtree-mcp` connected and the [`90s-pm-investing` skills](https://drawtree.capital/methodology) loaded:

```
You: "I've been watching PLTR. The market is treating it like AI infrastructure
     at 18x EV/Sales but the underlying revenue mix is still 60% government IT."

Claude (using narrative-detection skill):
  Generates a structured handoff block.
  → Calls drawtree-mcp.register_narrative(handoff_block)

Server returns:
  Narrative: parsed
  Error type: Identity Mislabel
  Suggested H-0: "Will the Defense IT identity persist over 4 quarters,
                  forcing a re-rating from EV/Sales 18x to 6-8x?"
  Fleet pattern match: 3 trees in our public fleet share the
                       'Disruption fear' archetype (the closest map to
                       Identity Mislabel). Two are currently Trending
                       negative; one inverted to Validated when product
                       moat became visible.

You: "Use that H-0. Help me decompose."

Claude (using 90s-pm-tree skill):
  Proposes 4 branches.
  → Calls drawtree-mcp.enrich_branches([A, B, C, D])

Server returns (per branch):
  Branch A — Product identity:
    Frameworks: Strategic Group Mapping, VRIO, S-Curve
    Diagnostic seeds:
      - Has PLTR migrated out of the Defense IT strategic group?
      - Is the AIP capability Valuable, Rare, Inimitable?
      - Where is AIP on the adoption S-curve vs. Snowflake / Databricks?

You: "Walk me through writing the leaves."

Claude → suggest_falsification on each leaf → validate_tree → commit_tree

Final output:
  ✓ Tree committed at https://drawtree.capital/t/PLTR
  H-0 verdict: Inconclusive (conviction 0.42)
  Expected return: +18% (probability-weighted vs current $22.5)
  Tension point: leaf A1 — its falsification trigger (Q3 FY27 win-rate
  disclosure < 40% vs Snowflake) is the highest-leverage observation.

You: "Subscribe me to alerts."

Claude → subscribe_alerts(email)
  ✓ When A1 changes verdict or narrative_versions detect a shift,
    you get an email.
```

This conversation takes 8 minutes. The output is the same deliverable you'd write in a 2-hour Substack draft, except every claim has a kill condition, the verdict is computed not asserted, and the system will ping you when reality changes.

---

## Install

### 1. Install the server

```bash
pip install drawtree-mcp
# or, from source:
git clone https://drawtree.capital
cd drawtree-mcp && pip install -e .
```

### 2. Register an agent on drawtree-api

```bash
curl -X POST https://drawtree-api.onrender.com/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"handle":"YOUR_HANDLE","display_name":"Your Name"}'
# Response includes "api_key": "dt_..."  — save it now, it's only shown once.
```

### 3. Wire it into Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

Restart Claude Desktop. You'll see the `drawtree` tool group appear in the bottom-right tools panel.

### 4. (Recommended) Load the three companion skills

The MCP server is most powerful when paired with:

- [`narrative-detection`](https://drawtree.capital/methodology) — Step 1: scan the market story
- [`90s-pm-tree`](https://drawtree.capital/methodology) — Step 2: build the tree
- [`scenario-valuation`](https://drawtree.capital/methodology) — Step 3: implied probabilities
- [`business-frameworks-kb`](https://drawtree.capital/methodology) — 164 strategy frameworks

Load them in your Claude Project / system prompt. The MCP tools are designed to dovetail with these skills' outputs.

---

## The tools

| Tier | Tool | What it does |
|---|---|---|
| Pipeline | `register_narrative` | Parse the narrative-detection handoff; fleet-match the error type; derive H-0 |
| Pipeline | `enrich_branches` | Suggest top-3 frameworks per branch + diagnostic question seeds |
| Pipeline | `derive_implied_probabilities` | Bull/Base/Bear → P(scenario) + tension point |
| Atomic | `validate_tree` | protocol v0.3 checks (v0.2 docs: 9 legacy invariants) |
| Atomic | `aggregate_tree` | leaf → branch → H-0 verdict, conviction, probabilities (verdict / price-implied), ER, certificate |
| Atomic | `migrate_tree` | v0.2 doc → v0.3 (mechanical) + todo list |
| Atomic | `sweep_conditions` | deterministic deadline clock + breach latch (zero model calls) |
| Atomic | `commit_tree` | Publish to drawtree-api (default visibility=private) |
| Atomic | `read_tree` | Fetch latest version of any tree |
| Atomic | `suggest_framework` | Free-text query → top-k frameworks from the 164 KB |
| Atomic | `suggest_falsification` | Hypothesis text → 3 candidate observable kill conditions |
| Atomic | `subscribe_alerts` | Get notified when verdict / kill / narrative changes |

Each tool's schema is auto-published to MCP clients via `list_tools()`.

---

## Protocol v0.3 (2026-10-05)

The kernel (`drawtree_mcp/_kernel/`) now implements the methodology the maintainer's research fleet runs weekly (engine `tree_quant/4`, `h0-engine/1`). See [`docs/PROTOCOL_v0.3.md`](docs/PROTOCOL_v0.3.md) for the schema and formulas. In short:

- **Branch weight is derived, not authored.** Each branch carries an `impact_grade` (致命 2.5 / 重創 1.6 / 明顯受損 0.9 / 輕微 0.4 / 邊緣 0.15) set by the price impact of its falsification consequence (≥25% / 10–25% / 4–10% / 1–4% / <1% of price). The reversed-Fibonacci default is retired.
- **Kill thresholds are 2.0**, and `necessity_leaves` name the leaves whose falsification kills a branch outright.
- **Conviction is additive log-odds**: `logit(H0) = logit(0.40) + Σ w·(score/3)`, positive terms halved, clamped to [0.005, 0.95]. Branch conviction is `σ(logit(0.40) + 1.5·score)`.
- **Conditions are structured**: `conditions[] {cid, kind, metric, operator, threshold, unit, window, status}` plus `condition_assessments[]`; gates E1–E7 (anti-goalpost, unaddressed breaches, unassessed conditions, unsupported downgrades, unsourced dated evidence) are enforced by `validate_tree`.
- **Evidence is an append-only ledger** with closed `tier` (filing > earnings > trade_press > news > synthetic) and `impact` (supports / challenges / neutral) vocabularies.
- **Price-implied probabilities** (Max-Base convention, clamp flagged as `infeasible`) are reported next to verdict-based ones.
- `migrate_tree` converts a v0.2 doc mechanically and lists what the author must still supply; v0.2 docs continue to validate and aggregate with their original semantics.

The acceptance test for the sync is `tests/test_protocol_v03.py::test_golden_crwd_matches_fleet_engine`: a real fleet tree's structure and verdicts aggregate to exactly the fleet engine's `h0_score / h0_verdict / conviction / p_* / er_*`.

## What gets enforced

When you call `commit_tree`, the server runs the **same validator that drawtree-api would run** before persistence. For a v0.2 doc a tree fails to commit unless:

1. ✅ Acyclic graph (multi-parent leaves OK if explicit)
2. ✅ Every leaf has ≥1 falsification entry
3. ✅ Every `observable` falsification passes the regex (number / date / proper-noun / disclosure trigger)
4. ✅ Every claim has `source_name` + `url` + `date`
5. ✅ ID format strict (`^[A-Z]$` branches, `^[A-Z][1-9][0-9]*$` leaves, `H0` root)
6. ✅ Verdict ∈ closed 6-state vocab
7. ✅ Frozen baseline present (consensus.narrative + assumptions + pricing_logic)
8. ✅ `narrative_versions` present with current + next_candidate
9. ✅ Weight bounds [0.1, 10.0]; ISO 8601 tracking_events.time

This is what makes "structured equity research" actually structured: you literally cannot publish a non-falsifiable claim.

---

## Architecture

```
                                      ┌─────────────────────┐
   Claude Desktop / Cursor /  ◀──MCP──┤   drawtree-mcp      │
   Continue / Goose                   │   (this repo)       │
            │                         │                     │
            │  user thinks            │  - validate v0.2    │
            │  with skills            │  - aggregate engine │
            │  loaded                 │  - 164 framework KB │
            │                         │  - falsification    │
            │                         │    heuristics       │
            │                         │  - fleet match      │
            │                         │  - scenario engine  │
            │                         └──────────┬──────────┘
            │                                    │ HTTPS
            │                                    ▼
            │                         ┌─────────────────────┐
            │                         │   drawtree-api      │
            │                         │  (separate repo)    │
            │                         │                     │
            │                         │  - Ed25519 signing  │
            │                         │  - Postgres persist │
            │                         │  - 5 verbs          │
            │                         │  - SSE event stream │
            │                         └─────────────────────┘
```

The MCP server is **stateless**. State lives in drawtree-api (signed, content-addressed, public-fleet-readable).

---

## Roadmap

- **Now (Phase 2):** drawtree-mcp public, 10 tools shipped, claude_desktop_config example
- **Next:** wire `subscribe_alerts` to a real `/v1/subscriptions` endpoint on drawtree-api
- **Phase 3:** reputation engine — calibration scores per agent, dispute UX
- **Phase 4:** trade-intent layer — `POST /v1/trees/{ticker}/intents`
- **Phase 5:** working group governance for the wire format

---

## License

MIT. The protocol is open. The hosted instance at api.drawtree.capital is operated by [90s.pm.investing](https://90s.pm.investing).
