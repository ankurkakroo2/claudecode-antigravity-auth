# Antigravity Fixes Summary (Chronological)

1) Normalize Claude 4.5 model IDs and update model mappings so 4.5 uses `4-5` across the proxy (`gemini-for-claude-code/antigravity_client.py`, `gemini-for-claude-code/gclaude/detector.py`, `gemini-for-claude-code/CLAUDE.md`).
2) Add Autopush endpoint to Antigravity fallback lists and detection logic (`gemini-for-claude-code/antigravity_client.py`, `gemini-for-claude-code/gclaude/detector.py`).
3) Inject the Antigravity system instruction with `systemInstruction.role = "user"` to match CLIProxy behavior (`gemini-for-claude-code/antigravity_client.py`).
4) Ensure streaming requests include `Accept: text/event-stream` for SSE compatibility (`gemini-for-claude-code/antigravity_client.py`).
5) Surface local rate-limit backoff as a real Antigravity rate-limit error with Retry-After (`gemini-for-claude-code/quota_manager.py`).
6) Default Antigravity Sonnet/Opus env mappings to the Claude thinking models (`gemini-for-claude-code/server.py`).
7) Improve model detection + CLI defaults to prefer Antigravity Claude 4.5 thinking models when available (`gemini-for-claude-code/gclaude/detector.py`, `gemini-for-claude-code/gclaude/cli.py`).
8) Prefer prod for `loadCodeAssist` and extract managed project IDs from nested payloads; pass `duetProject` hint when available (`gemini-for-claude-code/antigravity_auth.py`).
9) Refresh the stored project ID on first Antigravity use to match managed project expectations (`gemini-for-claude-code/quota_manager.py`).
10) Add Claude thinking defaults in Antigravity requests (thinkingConfig, max output) and attach a stable `sessionId` (`gemini-for-claude-code/antigravity_client.py`).
11) Send `anthropic-beta: interleaved-thinking-2025-05-14` for Claude thinking models to mirror opencode behavior (`gemini-for-claude-code/antigravity_client.py`).
12) Disable the active Ralph loop stop hook state in this repo by moving `./.claude/ralph-loop.local.md` to `./.claude/ralph-loop.local.md.bak`.

Validation

1) `opencode run -m google/antigravity-claude-sonnet-4-5-thinking "ping"`
2) `opencode run -m google/antigravity-claude-opus-4-5-thinking "ping"`
3) `anticlaude -p --model sonnet "ping"`
4) `anticlaude -p --model opus "ping"`
