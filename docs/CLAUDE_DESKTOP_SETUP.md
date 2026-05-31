# Wiring drawtree-mcp into Claude Desktop

5-minute setup. After this, you can have the conversation in the README's "Wow Moment" section.

## Prerequisites

- Claude Desktop installed: https://claude.ai/download
- Python 3.10+
- A drawtree-api account (free) — see Step 2

## Step 1 — Install the MCP server

Pick one path:

### A. From PyPI (recommended)

```bash
pip install drawtree-mcp
```

### B. From source (latest changes)

```bash
git clone https://drawtree.capital
cd drawtree-mcp
pip install -e .
```

Verify it works:

```bash
drawtree-mcp --help 2>/dev/null  # the CLI is a stdio server, no --help; this is fine
echo "drawtree-mcp installed at: $(which drawtree-mcp)"
```

You should see a path like `/Users/you/.../bin/drawtree-mcp`.

## Step 2 — Register your agent on drawtree-api

```bash
curl -X POST https://drawtree-api.onrender.com/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"handle":"YOUR_HANDLE","display_name":"Your Name"}'
```

The response looks like:

```json
{
  "agent_id": "...",
  "handle": "YOUR_HANDLE",
  "api_key": "dt_xxxxxxxxxxxx"
}
```

**Save the `api_key` now — it's only returned once.**

## Step 3 — Edit Claude Desktop's config

Find the file:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

If it doesn't exist, create it. Add this:

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

If you already have other MCP servers, add `drawtree` as another key inside the existing `mcpServers` object — don't replace the whole file.

If `drawtree-mcp` isn't on your PATH (because you used `pip install --user`), use the full path:

```json
"command": "/Users/you/Library/Python/3.12/bin/drawtree-mcp"
```

## Step 4 — Restart Claude Desktop

Quit fully (Cmd+Q on macOS), then reopen. You'll see a small **"+ tool"** indicator in the bottom-right of the chat box. Click it and you should see:

```
drawtree
  - validate_tree
  - aggregate_tree
  - commit_tree
  - read_tree
  - register_narrative
  - suggest_framework
  - enrich_branches
  - suggest_falsification
  - derive_implied_probabilities
  - subscribe_alerts
```

## Step 5 — (Recommended) Load the three companion skills

For the full pipeline experience, load these into your Claude Project's system prompt:

1. `narrative-detection` (Step 1: scan market story)
2. `90s-pm-tree` (Step 2: build tree)
3. `scenario-valuation` (Step 3: implied probabilities)
4. `business-frameworks-kb` (164 framework reference)

Get them from: https://drawtree.capital/methodology

In Claude Desktop, create a new Project, paste the four skills' contents in the Project's system prompt, and save. Now any conversation you start in that Project has both the strategist (skills) and the toolkit (MCP server).

## Step 6 — Smoke test

In a Claude Desktop conversation:

```
You: Can you validate this minimal Draw Tree v0.2 doc?

{minimal valid tree paste, or just say "use the demo tree"}

Claude: I'll use the validate_tree tool.
[invokes drawtree.validate_tree]
✓ 0 errors, 2 warnings — tree is publishable
```

If you see this, you're done.

## Troubleshooting

### `command not found: drawtree-mcp`

`pip install --user` installs to a user-local bin that may not be on PATH. Find it:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

Use the full path in `claude_desktop_config.json`.

### Claude Desktop says "MCP server failed to start"

Run it manually to see the error:

```bash
DRAWTREE_API_KEY=dt_xxx drawtree-mcp
# It will hang waiting for stdio input — that's correct.
# Press Ctrl+C. If you see no errors, it works; the issue is in your config.
```

Common cause: trailing comma in `claude_desktop_config.json`, or wrong path.

### Tools appear but `commit_tree` returns 401

Your `DRAWTREE_API_KEY` env var isn't reaching the server. Check the JSON `env` block — it must be inside the `drawtree` server block, not at the top level.

### Tools work but the dashboard doesn't show your tree

Default visibility is `private`. The public dashboard at drawtree.capital only shows public trees. Either:

- Visit `https://drawtree.capital/t/{TICKER}?agent_handle=YOUR_HANDLE` (private trees show up if you query with your handle)
- Or call `commit_tree` with `visibility: "public"`
