# Plan: Antigravity Integration - Current Status & Next Steps

## Current Status (Updated: 2026-01-16)

**What Works:**
- ✅ OAuth authentication with Google OAuth 2.0
- ✅ Model detection working - detects 7 Antigravity models
- ✅ CLI commands: `init`, `start`, `stop`, `status`, `logs`, `auth`
- ✅ OAuth tokens stored in `~/.config/gclaude/antigravity-accounts.json`
- ✅ `antigravity()` shell function in `.zshrc` for launching Claude Code
- ✅ Auto-creation of `~/.claude/antigravity-settings.json` during init
- ✅ Proxy health check shows Antigravity available

**What Doesn't Work:**
- ❌ **Requests NOT using Antigravity** - falling back to Gemini CLI instead
- ❌ Invalid fallback model `gemini-2.5-pro-preview` doesn't exist (404 errors)
- ❌ Gemini CLI rate limited (quota exhausted on gemini-2.0-flash-exp)
- ❌ Tool schema error: `EnterPlanMode` incompatible with Gemini format
- ❌ Claude Code receives no responses (silent failures)

---

## Root Cause Analysis

**Primary Issue**: Proxy is NOT routing to Antigravity - falls back to Gemini CLI

From proxy logs (`~/.gclaude/logs/proxy.log`):
1. **Model routing broken** - requests use Gemini CLI instead of Antigravity
2. **Invalid fallback model** - `gemini-2.5-pro-preview` doesn't exist (404)
3. **Gemini CLI quota exhausted** - hitting rate limits on `gemini-2.0-flash-exp`
4. **Tool schema incompatibility** - `EnterPlanMode` fails Gemini validation

**Health check shows:**
```json
"antigravity": {
  "enabled": true,
  "available": true,
  "accounts": 1,
  "preferred": "antigravity"
}
```

But requests still fall back to Gemini CLI - routing logic issue.

---

## Next Steps - URGENT FIXES

### 1. ⚠️ Fix Model Routing (CRITICAL)

**Problem**: Proxy health shows Antigravity available but requests use Gemini CLI

**Action items:**
- [ ] Check `server.py` model routing logic - why is Antigravity not used?
- [ ] Verify `quota_manager.py` actually calls Antigravity client
- [ ] Add debug logging to see which quota backend is selected
- [ ] Test with direct Antigravity API call to verify OAuth works

### 2. Fix Invalid Fallback Models

**Problem**: Config has non-existent models

**Current config has:**
```json
"opus": { "target": "gemini-2.5-pro-preview", "type": "gemini" }
```

**Action items:**
- [ ] Update to valid Gemini model: `gemini-2.0-flash-exp` or `gemini-1.5-pro-latest`
- [ ] Or use Antigravity: `antigravity-claude-opus-4-5-thinking`
- [ ] Restart proxy after config change

### 3. Fix Tool Schema Errors

**Problem**: `EnterPlanMode` tool fails Gemini validation

**Action items:**
- [ ] Check `server.py` tool translation - ensure all tools have valid OBJECT schemas
- [ ] Test with simpler request (no tools) first
- [ ] Add tool schema validation before sending to Gemini

---

## Recent Changes (2026-01-16)

### Fixed Today ✅
| File | Change | Status |
|------|--------|--------|
| `gclaude/cli.py:186` | Fixed questionary.Choice bug - use Choice objects instead of dicts | ✅ Fixed |
| `gclaude/cli.py:189` | Changed Skip option value from `None` to `""` for proper falsy handling | ✅ Fixed |
| `gclaude/cli.py:272-283` | Auto-create `~/.claude/antigravity-settings.json` during init | ✅ Fixed |
| `~/.claude/antigravity-settings.json` | Created settings file for `antigravity()` shell function | ✅ Fixed |

### Still Broken ❌
| Component | Issue | Impact |
|-----------|-------|--------|
| Model routing | Requests use Gemini CLI instead of Antigravity | High - Antigravity never used |
| Fallback models | `gemini-2.5-pro-preview` doesn't exist | High - 404 errors |
| Gemini quota | Rate limited on `gemini-2.0-flash-exp` | High - No responses |
| Tool schemas | `EnterPlanMode` fails Gemini validation | Medium - Some requests fail |

---

## Current Configuration

**File**: `~/.gclaude/config.json`

```json
{
  "version": "1.0.0",
  "proxy": {
    "host": "127.0.0.1",
    "port": 8082,
    "log_level": "INFO"
  },
  "auth": {
    "enabled": true,
    "account_email": "ankurkakroo2@gmail.com"
  },
  "models": {
    "haiku": {
      "pattern": "*haiku*",
      "target": "antigravity-gemini-3-pro-high",
      "type": "antigravity"
    },
    "sonnet": {
      "pattern": "*sonnet*",
      "target": "antigravity-claude-sonnet-4-5-thinking",
      "type": "antigravity"
    },
    "opus": {
      "pattern": "*opus*",
      "target": "antigravity-claude-opus-4-5-thinking",
      "type": "antigravity"
    }
  },
  "fallback_api_key": "AIzaSyCfy24THExTSHt0aX1qs_J34VQVAOb4KA0"
}
```

**Shell Function**: `~/.zshrc` has `antigravity()` function that:
1. Waits for proxy health check
2. Launches Claude Code with `--settings ~/.claude/antigravity-settings.json`

**Claude Settings**: `~/.claude/antigravity-settings.json`
```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "dummy-key-proxy-handles-auth",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082",
    "API_TIMEOUT_MS": "3000000"
  }
}
```

---

## Detected Antigravity Models

From `gclaude init` model detection:
- ✓ antigravity-gemini-3-flash
- ✓ antigravity-gemini-3-pro-low
- ✓ antigravity-gemini-3-pro-high
- ✓ antigravity-claude-sonnet-4-5
- ✓ antigravity-claude-sonnet-4-5-thinking
- ✓ antigravity-claude-opus-4-5-thinking
- ✓ antigravity-gpt-oss-120b-medium

---

## Diagnostic Commands

```bash
# Check proxy status
gclaude status

# View logs in real-time
gclaude logs -f

# Test proxy health
curl http://127.0.0.1:8082/health | jq

# Check OAuth account
cat ~/.config/gclaude/antigravity-accounts.json | jq

# Check gclaude config
cat ~/.gclaude/config.json | jq

# Restart proxy
gclaude stop && gclaude start

# Test antigravity shell function
antigravity
```

---

## Architecture

```
Claude Code CLI
     ↓ (ANTHROPIC_BASE_URL=http://127.0.0.1:8082)
gclaude proxy (server.py)
     ↓ (routes based on model type)
     ├─→ Antigravity API (OAuth) → Google Gemini 3 models
     └─→ Gemini CLI API (API key) → Standard Gemini models (fallback)
```

**Current Problem**: Routing always goes to Gemini CLI fallback instead of Antigravity.
