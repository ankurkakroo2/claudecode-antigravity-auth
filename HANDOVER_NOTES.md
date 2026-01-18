**Purpose**  
We’re making Claude Code work reliably through the Antigravity (Google OAuth / AI Pro) proxy so Claude Sonnet/Opus behave like native Claude Code: clean thinking display, stable streaming, and working tool calls/MCP integrations.

**Current goals**  
- Ensure Antigravity OAuth works without API keys.  
- Fix thinking output so it doesn’t blend with final answers.  
- Make tool calls reliable (no “Invalid tool parameters”).  
- Surface rate-limit/auth errors cleanly instead of hanging.

**What’s been changed so far**  
- Antigravity streaming now emits proper SSE stop events on errors to avoid “Unravelling…” hangs.  
- Added support for `thinking` content blocks so Claude Code accepts them.  
- Aligned Antigravity thinking behavior with opencode (no forced thoughts by default).  
- Tool call args are normalized and schema-coerced so required params aren’t missing.  
- Added a friendly rate-limit error message for streaming requests.

**How it works (summary)**  
Claude Code → proxy → Antigravity (OAuth).  
The proxy translates Anthropic request/response format to Antigravity/Gemini format, then translates back to Anthropic SSE events so Claude Code can display tool calls, streaming responses, and (optionally) thinking blocks.

**What still needs verification**  
- End-to-end: tool call success + clean output formatting in Claude Code.  
- MCP server registration: `listMcpResources` returns “No resources found” if MCP isn’t configured, so Playwright MCP must be registered in Claude Code’s MCP config.  
- Authentication stability: intermittent “Authentication failed” and rate-limit events still appear and need monitoring.

**How to test E2E (manual)**  
1. Start the proxy and verify it responds:  
   ```
   python -m gclaude stop
   python -m gclaude start
   curl -s http://127.0.0.1:8082/health
   ```
2. Tool call test:  
   ```
   anticlaude -p --model sonnet "read this directory and tell me what this project does"
   ```
3. MCP discovery test (requires MCP config):  
   ```
   anticlaude -p --model sonnet "can you check if playwright mcp server is installed"
   ```

**Known failure signals**  
- “Invalid tool parameters” → tool args missing or schema mismatch.  
- “No resources found” → MCP servers not configured.  
- “Unravelling…” stuck → stream did not finish properly.  
- “Authentication failed” / rate-limit → OAuth or quota issues.

**Next steps**  
- Confirm MCP server is registered in Claude Code’s MCP config.  
- Run E2E tests again with the proxy logs visible to capture any remaining errors.  
- If tool calls still fail, capture the raw tool name + schema and tighten argument coercion for that tool.
