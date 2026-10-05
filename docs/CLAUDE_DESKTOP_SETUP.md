# Wiring drawtree-mcp into Claude Desktop (or any MCP client)

Two ways in. The hosted HTTPS server needs no install; the local stdio server runs the same kernel on
your machine.

## Option A — hosted server (claude.ai, Claude Desktop connectors, ChatGPT, Perplexity)

URL: `https://drawtree-mcp.onrender.com/mcp`

Add it as a remote MCP server / custom connector in your client. Authentication is OAuth (the server
publishes `/.well-known/oauth-protected-resource`); sign in with your drawtree account, or paste an API
key as a Bearer token where the client allows it. The hosted server exposes the full surface: kernel
tools, the Create-mode draft flow, the valuation gate, the point-in-time reads, View mode, and the
`search` / `fetch` pair ChatGPT requires.

## Option B — local stdio server

### Prerequisites

- Python 3.10+
- A drawtree-api account (free) — Step 2

### Step 1 — Install

The package is not published on PyPI. Install from the repository:

```bash
pip install "git+https://github.com/hopakhei/drawtree-mcp.git"
# or, for development
git clone https://github.com/hopakhei/drawtree-mcp.git
cd drawtree-mcp && pip install -e .
```

Verify:

```bash
echo "drawtree-mcp installed at: $(which drawtree-mcp)"
```

### Step 2 — Register your agent on drawtree-api

```bash
curl -X POST https://drawtree-api.onrender.com/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"handle":"YOUR_HANDLE","display_name":"Your Name"}'
```

The response contains `api_key` (`dt_…`). **Save it now — it is only returned once.**

### Step 3 — Edit Claude Desktop's config

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "drawtree": {
      "command": "drawtree-mcp",
      "env": {
        "DRAWTREE_API_URL": "https://drawtree-api.onrender.com",
        "DRAWTREE_API_KEY": "dt_PASTE_YOUR_KEY_HERE"
      }
    }
  }
}
```

If you already have other servers, add `drawtree` inside the existing `mcpServers` object. If
`drawtree-mcp` is not on your PATH (`pip install --user`), use the full path from
`python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"`.

### Step 4 — Restart Claude Desktop

Quit fully, reopen, and open the tools panel. The stdio server advertises these 20 tools:

```
drawtree
  kernel (free, no model calls)   validate_tree · aggregate_tree · migrate_tree · sweep_conditions
  publish / read                  commit_tree · read_tree · read_tree_versions · read_tree_state_at
  valuation gate (free)           evaluate_valuation · report_two_decisions · approve_decisions
  frameworks                      suggest_framework
  paid, credit-metered            register_narrative · enrich_branches · suggest_falsification ·
                                  derive_scenario_values · subscribe_alerts
  account                         balance · confirm_charge · refund_charge
```

The Create-mode draft flow (`start_draft` … `commit_draft_tree`, `summarize_tree`, View mode) is on the
hosted server only; the stdio server is the kernel plus publish, read and the valuation gate.

## Step 5 — Load the starter skill

Paste [`docs/starter-skill.md`](starter-skill.md) into your Claude Project's instructions. It encodes the
draw-tree v6 procedure (four steps, two human gates: the framework gate and the two-decision gate), the
five questions, the eight leaf-admission questions, and the reader-text rules the report follows.

## Step 6 — Smoke test

```
You: Validate and aggregate this tree.   (paste tests/fixtures/crwd_structure_2026-10-03.json)

Claude → validate_tree → aggregate_tree
  h0_score 0.0425 · Inconclusive · conviction 0.3525 · price-implied base 0.8815 / bear 0.1185
```

Those are the figures the maintainer's fleet engine reports for the same document; matching them is
the acceptance test for the sync.

## Troubleshooting

- **`command not found: drawtree-mcp`** — see the PATH note in Step 3.
- **"MCP server failed to start"** — run `DRAWTREE_API_KEY=dt_xxx drawtree-mcp` in a terminal; it waits
  on stdin (that is correct). A JSON syntax error in the config (trailing comma) is the usual cause.
- **`commit_tree` returns 401** — the `env` block must sit inside the `drawtree` server entry.
- **The tree is missing on the dashboard** — default visibility is `private`; open
  `https://drawtree-dashboard.vercel.app/t/{TICKER}?agent_handle=YOUR_HANDLE`, or commit with
  `visibility: "public"`.
- **`approve_decisions` returns `GATE_NOT_PASSED`** — the stored report still has errors; run
  `evaluate_valuation` until `errors` is empty and `report_two_decisions` again.
