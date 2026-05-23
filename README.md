# drawtree-mcp

> **Turn an investment hunch into a falsifiable, signed, queryable graph — in one Claude Desktop conversation.**

`drawtree-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that gives any MCP-aware AI client (Claude Desktop, Cursor, Continue, Goose, …) the tools to:

1. **Parse a market-narrative scan** into a structured H-0 root question (the [narrative-detection](https://github.com/hopakhei/90s-pm-investing) skill output)
2. **Cross-reference your narrative against a public fleet** of seeded thesis trees — see how peers with the same narrative archetype have played out
3. **Suggest from a 164-framework KB** which strategy framework best fits each branch (Porter's Five Forces, VRIO, Network Effects Map, Real Options Valuation, …)
4. **Seed leaves** with curated framework-specific diagnostic questions
5. **Suggest typed falsification** kill conditions that pass the v0.2 observability regex
6. **Validate** the tree against the 9 protocol invariants (acyclic, source refs, observable kill conditions, frozen baseline, narrative versions, …)
7. **Aggregate** leaf → branch → H-0 verdict + conviction (0–1) + expected return (Σ P × distance)
8. **Reverse-engineer** the market's implied probability distribution and identify the highest-leverage tension-point leaf
9. **Commit privately** to drawtree-api with Ed25519 attestation
10. **Subscribe to alerts** when a kill switch fires or narrative shifts

The server itself is **deterministic and contains zero LLM calls**. All thinking happens in your Claude. The server provides schema, retrieval, and persistence — your AI is the strategist.

---

## The Wow Moment

Open Claude Desktop with `drawtree-mcp` connected and the [`90s-pm-investing` skills](https://github.com/hopakhei/90s-pm-investing) loaded:

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
  ✓ Tree committed at https://drawtree-dashboard.vercel.app/t/PLTR
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
git clone https://github.com/hopakhei/drawtree-mcp
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

- [`narrative-detection`](https://github.com/hopakhei/90s-pm-investing) — Step 1: scan the market story
- [`90s-pm-tree`](https://github.com/hopakhei/90s-pm-investing) — Step 2: build the tree
- [`scenario-valuation`](https://github.com/hopakhei/90s-pm-investing) — Step 3: implied probabilities
- [`business-frameworks-kb`](https://github.com/hopakhei/90s-pm-investing) — 164 strategy frameworks

Load them in your Claude Project / system prompt. The MCP tools are designed to dovetail with these skills' outputs.

---

## The 10 tools

| Tier | Tool | What it does |
|---|---|---|
| Pipeline | `register_narrative` | Parse the narrative-detection handoff; fleet-match the error type; derive H-0 |
| Pipeline | `enrich_branches` | Suggest top-3 frameworks per branch + diagnostic question seeds |
| Pipeline | `derive_implied_probabilities` | Bull/Base/Bear → P(scenario) + tension point |
| Atomic | `validate_tree` | v0.2 schema + 9 invariants check |
| Atomic | `aggregate_tree` | leaf → branch → H-0 verdict + conviction + ER |
| Atomic | `commit_tree` | Publish to drawtree-api (default visibility=private) |
| Atomic | `read_tree` | Fetch latest version of any tree |
| Atomic | `suggest_framework` | Free-text query → top-k frameworks from the 164 KB |
| Atomic | `suggest_falsification` | Hypothesis text → 3 candidate observable kill conditions |
| Atomic | `subscribe_alerts` | Get notified when verdict / kill / narrative changes |

Each tool's schema is auto-published to MCP clients via `list_tools()`.

---

## What gets enforced

When you call `commit_tree`, the server runs the **same validator that drawtree-api would run** before persistence. A tree fails to commit unless:

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
