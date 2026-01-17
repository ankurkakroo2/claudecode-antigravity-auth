# Handover: Antigravity (OAuth) Works in CLI, Claude Code "anticlaude" Session Does Not

## Goal

Make Claude Code work reliably using Google OAuth-only (Antigravity) so that Claude Code can use the user’s paid Google AI Pro / higher-tier models (no API key, no AI Studio key creation).

Desired outcome:
- `anticlaude` mode starts a Claude Code session and returns responses normally.
- Model routing uses the *correct* Antigravity model IDs.
- The proxy should not silently fail / return empty streaming responses.

Non-goals:
- Using `GEMINI_API_KEY` or any API-key-based Gemini path.


## User’s Position (Important)

The user is adamant:
- They are *not* actually rate-limited in the real world.
- They can send requests via Antigravity and get responses from the higher-tier / thinking models.
- Therefore, any 429/RESOURCE_EXHAUSTED behavior we observe in the proxy is likely due to:
  - wrong model IDs,
  - wrong endpoint/bucket,
  - wrong request shape/headers/userAgent,
  - or proxy/Claude Code concurrency behavior,
  - NOT because the account lacks access.

Treat this as a “proxy mismatch” problem, not an entitlement problem.


## Current Local Setup (as observed on the machine)

### Repo
- Path: `gemini-for-claude-code/`
- Proxy entrypoint used by LaunchAgent and tests: `gemini-for-claude-code/server.py` (legacy single-file server).

### Shell command used for Claude Code
- `anticlaude()` function in `~/.zshrc` runs:
  - `claude --settings ~/.claude/antigravity-settings.json --dangerously-skip-permissions ...`
- `~/.claude/antigravity-settings.json` sets:
  - `ANTHROPIC_BASE_URL=http://127.0.0.1:8082`
  - `ANTHROPIC_AUTH_TOKEN=dummy-key-proxy-handles-auth`

### OAuth token storage
- `~/.config/gclaude/antigravity-accounts.json`
- Contains:
  - `email`: user’s Google account
  - `project_id`: discovered Code Assist / AI Companion project (example seen: `perceptive-legend-22j41`)

### gclaude config
- `~/.gclaude/config.json`
- `auth.enabled=true`
- Model routes are set to Antigravity models (example seen):
  - haiku -> `antigravity-gemini-3-pro-high`
  - sonnet -> `antigravity-claude-sonnet-4-5-thinking`
  - opus -> `antigravity-claude-opus-4-5-thinking`

### LaunchAgent
- `~/Library/LaunchAgents/com.claude.gemini-proxy.plist`
- Updated to be OAuth-only:
  - `USE_ANTIGRAVITY=true`
  - `ANTIGRAVITY_HAIKU_MODEL`, `ANTIGRAVITY_SONNET_MODEL`, `ANTIGRAVITY_OPUS_MODEL`
  - Removed `GEMINI_API_KEY` from LaunchAgent.
- The proxy process must own port 8082; if another server instance is running, LaunchAgent will fail to bind.


## What Fails

### Symptom in Claude Code
When starting Claude Code in `anticlaude` mode, the user reports "no response" / session doesn’t behave normally.

### Proxy-level reproduction
When sending requests to the proxy while the issue is happening:
- Streaming `/v1/messages?beta=true` can produce SSE with `message_start` and then `stop_reason:error` without text.
- Non-streaming `/v1/messages` can return `429` with `RESOURCE_EXHAUSTED` from `https://cloudcode-pa.googleapis.com`.

The proxy logs often show:
- `Rate limit hit on https://daily-cloudcode-pa.sandbox.googleapis.com`
- then `Rate limit hit on https://cloudcode-pa.googleapis.com`
- `RESOURCE_EXHAUSTED`

This contradicts the user’s claim of being able to call higher-tier models via Antigravity outside the proxy.


## What Works

- The OAuth account is present and refresh works.
- `GET /health` and `GET /antigravity-status` respond and show Antigravity enabled.
- Direct Antigravity usage outside Claude Code is reported to work by user (this must be verified precisely).


## Why This Is Likely a Proxy Mismatch (Not “User Lacks Access”)

Given user’s insistence that the same account can call these models successfully, the most plausible categories are:

1) Model ID mismatch / naming drift
- The codebase contains multiple naming variants across files (historical):
  - `antigravity-claude-opus-4.5-thinking` vs `antigravity-claude-opus-4-5-thinking`
  - `antigravity-gemini-3-pro` vs `antigravity-gemini-3-pro-high/low`
- If the proxy uses an invalid model name, upstream errors can be confusing and may be mis-classified.

2) Request “shape” mismatch (quota bucket / policy)
- `antigravity_client.py` uses specific headers and wrapper fields:
  - `User-Agent: antigravity/1.11.5 windows/amd64`
  - `Client-Metadata` and `X-Goog-Api-Client`
  - body wrapper: `{ project, model, request, requestType, userAgent, requestId }`
- If the user’s working CLI uses different headers/body fields, it may hit a different quota bucket or avoid a policy path.

3) Claude Code concurrency + streaming behavior
- Claude Code tends to do more parallel activity (streaming, health checks, etc.).
- Even if single requests succeed, concurrency could cause 429 more easily.
- Also, the proxy can emit an SSE envelope that ends with an error stop_reason without delivering useful error text.

4) Local server lifecycle issues
- Multiple servers fighting for port 8082 can cause confusing behavior.


## Code Changes Already Made in This Session

### 1) Improve Antigravity model access detection to use discovered project_id
Problem:
- `gclaude/detector.py` previously tested access using a hardcoded fallback project id (`rising-fact-p41fc`), which can give misleading “license” errors or make paid models appear unavailable.

Fix:
- Updated `gemini-for-claude-code/gclaude/detector.py` to accept `project_id`.
- Updated `gemini-for-claude-code/gclaude/cli.py` so `gclaude init` and `gclaude set-model --detect` pass the discovered `project_id` from the user’s stored OAuth account.

### 2) LaunchAgent made OAuth-only
- Updated `~/Library/LaunchAgents/com.claude.gemini-proxy.plist` to remove `GEMINI_API_KEY` and set `USE_ANTIGRAVITY=true` plus explicit Antigravity model env vars.

### 3) Removed leaked API key from shell startup
- Removed `export GEMINI_API_KEY=...` from `~/.zshrc` (security fix).


## Key Files

- Proxy server: `gemini-for-claude-code/server.py`
- Antigravity client: `gemini-for-claude-code/antigravity_client.py`
- Quota routing: `gemini-for-claude-code/quota_manager.py`
- OAuth: `gemini-for-claude-code/antigravity_auth.py`
- CLI: `gemini-for-claude-code/gclaude/cli.py`
- Model detection: `gemini-for-claude-code/gclaude/detector.py`
- Claude settings: `~/.claude/antigravity-settings.json`
- Zsh function: `~/.zshrc` (`anticlaude()`)


## What To Test Next (Do This In Order)

### A) Establish a clean baseline: only one server instance
1) Ensure port is free, then start ONE server:
   - Preferred: LaunchAgent
     - `launchctl kickstart -k gui/$(id -u)/com.claude.gemini-proxy`
   - Verify:
     - `lsof -n -i :8082`
     - `curl -s http://127.0.0.1:8082/health`
     - `curl -s http://127.0.0.1:8082/antigravity-status`

### B) Verify the user’s claim: “I can call these models via Antigravity and it works”
This is the single most important step.

Do NOT rely on Claude Code yet. Reproduce a successful call using the SAME OAuth token and SAME endpoint family.

1) Write a minimal python snippet (or reuse existing code) that calls:
   - `AntigravityClient(access_token, project_id).generate_content(model, ...)`
2) Test each model that the user claims works:
   - `antigravity-gemini-3-flash`
   - `antigravity-gemini-3-pro-high` (or whichever “thinking/high” variant)
   - `antigravity-claude-sonnet-4-5-thinking`
   - `antigravity-claude-opus-4-5-thinking`
3) Record results with timestamps.

If this direct test fails with 429/RESOURCE_EXHAUSTED, the user’s claim is not reproducible at that moment (quota/backoff is real).
If it succeeds consistently, the proxy is doing something different.

### C) If direct python client succeeds but proxy fails, diff request shape
Capture and compare:
- headers
- request wrapper fields
- model name passed to API (after prefix stripping)

Actionable technique:
- Add temporary logging in `antigravity_client.py` right before `_make_request` executes to print:
  - selected endpoint
  - request JSON keys and relevant values (no tokens)
  - model name being sent

Then compare against the working CLI request (user-provided command/tool).

### D) Make Claude Code failure deterministic
1) Run a single “one-shot” Claude Code request through settings:
   - `claude --settings ~/.claude/antigravity-settings.json --dangerously-skip-permissions "ping"`
2) Tail logs at the same time:
   - `python -m gclaude logs -f` (if using gclaude server)
   - or `tail -f /tmp/gemini-proxy.log` (if using LaunchAgent)
3) Observe whether:
   - requests are parallel,
   - it’s always streaming,
   - and whether failures are 429 vs auth/license vs malformed stream.

### E) (Optional but recommended) Fix “empty streaming response” behavior
Currently, when Antigravity errors during streaming, the proxy can emit SSE that terminates without useful text.

Proposed improvement:
- If `QuotaManager.antigravity_state.is_available()` is false or `rate_limited_until` is active, return an HTTP 429 with `Retry-After` BEFORE starting SSE.
- This makes Claude Code behave predictably (backoff) instead of “no response”.


## Notes / Constraints

- User explicitly does not want an API key solution.
- The proxy is intended to be OAuth-only.
- If there is a `.env` file present, it may still set `GEMINI_API_KEY` via dotenv; remove it for a truly OAuth-only environment.


## Definition of Done

- `anticlaude` reliably responds in Claude Code sessions.
- Verified that the proxy can call the user’s claimed paid models via Antigravity.
- Model naming is consistent and correct.
- Failures (if any) surface clearly (HTTP status + message), not silent/empty SSE.
