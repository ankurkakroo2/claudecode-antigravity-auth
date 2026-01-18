# Running Notes

This document tracks the current working state, issues observed, and fixes applied while integrating Claude Code with Antigravity (OAuth).

## Current State
- Proxy starts cleanly and serves `/health` at `http://127.0.0.1:8082`.
- Antigravity-only flow is active (OAuth required; no API key mode).
- File read tool calls work end-to-end via Claude Code.
- Web summary works end-to-end (tool chain uses WebFetch/Bash when MCP tools are not registered).
- Playwright MCP registration still needs confirmation (tool list did not show Playwright tools in latest run).
- One-line install script is available and installs the `anticlaude` shell helper.

## Recent Tests
- Restarted proxy: `python -m gclaude stop` → `python -m gclaude start`.
- Health checks: `curl http://127.0.0.1:8082/health` and `/antigravity-status` OK.
- File read test (Claude Code):
  - Command: `claude --settings ~/.claude/antigravity-settings.json --dangerously-skip-permissions -p --model haiku "Read README.md and tell me the first line."`
  - Result: `# Antigravity OAuth Proxy for Claude Code`.
- Web summary test (Claude Code + MCP config):
  - Command: `claude --settings ~/.claude/antigravity-settings.json --mcp-config ~/.claude/mcp_config.json --dangerously-skip-permissions -p --model haiku "Use the Playwright MCP browser to open https://www.hackerrank.com and summarize the homepage."`
  - Result: Summary returned (tooling fell back to built-ins; Playwright tools not observed in tool list).
- Shell helper auto-start test (isolated HOME + stub CLI):
  - Command: `HOME=/tmp/gclaude-test PATH=/tmp/gclaude-test/bin:$PATH bash -lc "source /tmp/gclaude-test/rc; anticlaude 'ping'"`
  - Result: `anticlaude` started the proxy, wrote settings, and invoked the `claude` stub with `--settings`.

## Progress Log (Chronological)
- **Tool-call args normalization**
  - Added proto-args decoding (`fields`, `listValue`) and alias mapping (`url` ⇄ `link`, `query` ⇄ `prompt`) in `gclaude/proxy/antigravity_client.py`.
  - Preserved `functionCall.id` for tool result matching.
- **Thought signature forwarding**
  - Captured `thoughtSignature` from response parts and forwarded it with tool calls.
- **Tool result handling**
  - Preserved structured tool results (dict/list) instead of flattening to text.
- **Rate-limit backoff**
  - Added async backoff sleeps for 429s to avoid tight retry loops.
- **Antigravity-only cleanup**
  - Removed API-key mode and Gemini fallback references from code/docs; startup validates OAuth-only config.
- **Server start reliability**
  - `gclaude` now starts the proxy via `python -m gclaude.proxy.server` to avoid `No module named gclaude`.
- **Tool-use streaming fix (critical)**
  - Stream tool inputs using `input_json_delta` so Claude Code receives tool args properly.
  - This fixed missing `file_path` errors and tool-call hangs.
- **Path inference**
  - Extract file paths from user text to fill required tool args when the model omits them.
- **MCP test harness**
  - Added `--mcp-config ~/.claude/mcp_config.json` to enforce MCP server load during tests.
- **Install UX**
  - Added `scripts/install.sh` for no-clone installation.
  - Added `gclaude install-shell` to manage the shell helper.
  - `anticlaude` now auto-starts the proxy and guides setup if config is missing.

## Known Issues
1. **Playwright MCP tools not visible**
   - Tool schema list did not show Playwright tools in the latest run.
   - Need to confirm MCP server registration and tool availability.
2. **WebFetch 403s**
   - Built-in WebFetch occasionally returns 403; fallback path uses saved HTML + local parsing.
3. **Rate limits**
   - Antigravity quotas can still return 429s during heavy runs; backoff mitigates but doesn’t eliminate.

## Next Steps
- Confirm Playwright MCP tool registration (tools should appear in the schema list).
- If Playwright MCP loads, re-run the HackerRank summary and verify Playwright tools are invoked.
- If Playwright tools still missing, add explicit MCP config discovery in CLI defaults.
