# Running Notes

This document tracks the current working state, issues observed, and fixes applied while integrating Claude Code with Antigravity/Gemini.

## Current State
- Proxy starts and serves `/health` at `http://127.0.0.1:8082`.
- OAuth (Antigravity) path is active; Gemini API key path is optional.
- Tool calling is partially working for local tools (file read tests passed earlier).
- Web browsing via MCP (Playwright) is still failing.

## Recent Tests
- File read via Claude Code succeeded previously (used `Read` tool).
- Web browsing requests (`hackerrank.com`) still fail due to tool parameter issues and/or MCP availability.
- CLI execution can fail with `No assistant messages found` when Antigravity rate limits return 429s.

## Known Issues
1. **Web browsing tool call fails**
   - Symptoms: `Invalid tool parameters` or tool chain stalls after `tabs read`.
   - Observed tools: `ListMcpResourcesTool`, `ReadMcpResourceTool`, `WebFetch`.
   - Likely causes: missing MCP resources (Playwright MCP not registered), or tool args missing required fields (e.g., `url`, `prompt`).

2. **Rate limits cause Claude Code to crash**
   - Symptoms: `No assistant messages found` in the Claude Code CLI.
   - Proxy logs show repeated 429s with backoff.

3. **`claude` command not found**
   - `claude` is not on PATH in the current shell; use `npm i -g @anthropic-ai/claude-code` or run the CLI by absolute path.

## Fixes Applied
- **Tool-call argument handling**
  - Added decoding for proto-style args (`fields`, `listValue`).
  - Fill required params from recent user text (e.g., inferred `url`, `prompt`, `query`).
  - Map common aliases (e.g., `url` ⇄ `link`, `query` ⇄ `prompt`).
  - Preserve `functionCall.id` for tool result matching.

- **Thought signature handling**
  - Captures `thoughtSignature` from response parts and forwards it on tool calls.

- **Tool result handling**
  - Preserve structured tool results (lists/dicts) instead of flattening to text.

- **Rate-limit backoff**
  - Added async sleep during backoff to prevent tight retry loops.

## Web Browsing (MCP) Progress
- `ListMcpResourcesTool` calls return no resources when Playwright MCP is not registered.
- When Playwright MCP is available, tool calls must include required `url` and `prompt` fields to avoid `Invalid tool parameters`.
- Current focus: ensure MCP tool results are passed through intact and tool args are filled correctly.

## Next Steps
- Verify Playwright MCP registration in Claude Code config.
- Re-test `hackerrank.com` using Playwright MCP after rate limits clear.
- If tool errors persist, log the exact tool name/args that failed and add per-tool defaults.

