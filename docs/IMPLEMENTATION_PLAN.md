# Plan: Antigravity-Only Proxy

## Current Status (Updated: 2026-01-18)

**What Works:**
- ✅ OAuth authentication with Google OAuth 2.0
- ✅ Model detection for Antigravity models
- ✅ CLI commands: `init`, `start`, `stop`, `status`, `logs`, `auth`
- ✅ Proxy health check and Antigravity status
- ✅ File read tool calls work end-to-end via Claude Code
- ✅ Tool-use streaming sends `input_json_delta` (fixes missing tool args)
- ✅ Web summary works end-to-end using built-in tools when MCP tools are absent
- ✅ One-line install script adds `anticlaude` shell helper
- ✅ Shell helper auto-starts proxy and guards setup
- ✅ Shell helper auto-start validated with a stubbed proxy + CLI

**What Needs Attention:**
- 🔧 Confirm Playwright MCP tool registration and usage
- 🔧 Reduce WebFetch 403 reliance (prefer Playwright tool when available)
- 🔧 Monitor rate-limit spikes and retry behavior

---

## Goals

1. **Antigravity-only operation** (no API key mode)
2. **Clean, consistent documentation** aligned with OAuth-only usage
3. **Reliable tool-call handling** with clear error messages
4. **Repeatable validation steps** for file access and web browsing tool calls

---

## In Progress

### 1) Antigravity-only cleanup (completed)

**Tasks:**
- [x] Remove legacy API key references from server startup and docs
- [x] Remove fallback model mappings in detector logic
- [x] Update README/CLAUDE docs to Antigravity-only
- [x] Enforce OAuth-only startup validation

### 2) Validate tool-call integration

**Tasks:**
- [x] Confirm file read tool call works end-to-end
- [x] Fix tool-use streaming to include `input_json_delta`
- [x] Confirm web summary works end-to-end (built-in tools)
- [ ] Confirm Playwright MCP tools are registered and invoked

### 3) MCP/Playwright verification

**Tasks:**
- [ ] Ensure Playwright MCP tools appear in tool schema list
- [ ] Re-run HackerRank summary and verify Playwright tool invocation
- [ ] Add CLI defaults or docs for `--mcp-config` if needed

### 4) Simplified install UX (completed)

**Tasks:**
- [x] Add `scripts/install.sh` for no-clone installation
- [x] Add `gclaude install-shell` to manage shell integration
- [x] Shell helper auto-starts proxy and provides setup guidance

---

## Known Risks

| Area | Risk | Impact |
|------|------|--------|
| OAuth tokens | Expired or invalid tokens | Requests fail until re-auth |
| Model access | Restricted subscription access | Certain models unavailable |
| Tool schemas | Unsupported schema fields | Tool calls rejected |
| MCP tools | MCP server not loaded | Web automation falls back to WebFetch |

---

## Validation Checklist

```bash
# Check proxy status
python -m gclaude status

# Tail logs
python -m gclaude logs -f

# Health check
curl http://127.0.0.1:8082/health | jq

# Verify Antigravity status
curl http://127.0.0.1:8082/antigravity-status | jq

# File read test
claude --settings ~/.claude/antigravity-settings.json \
  --dangerously-skip-permissions -p --model haiku \
  "Read README.md and tell me the first line."

# MCP test (Playwright)
claude --settings ~/.claude/antigravity-settings.json \
  --mcp-config ~/.claude/mcp_config.json \
  --dangerously-skip-permissions -p --model haiku \
  "Use the Playwright MCP browser to open https://www.hackerrank.com and summarize the homepage."
```
