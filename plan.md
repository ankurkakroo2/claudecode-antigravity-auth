# Plan: Antigravity Models Integration for gemini-claude-proxy

## Overview
Integrate Antigravity's Google AI subscription models into the existing `gemini-for-claude-proxy` server, using Python OAuth implementation to match the `opencode-antigravity-auth` pattern.

---

## Phase 1: Discovery & Understanding ✅

### Current State
- **Proxy location**: `/Users/ankur/D/Playground/gemini-claude-proxy/gemini-for-claude-code/`
- **Current auth**: Direct `GEMINI_API_KEY` environment variable
- **Current model mapping**: Simple haiku → small_model, sonnet/opus → big_model
- **Port**: 8082

### Antigravity Auth Pattern (from opencode-antigravity-auth reference)
- **OAuth flow**: Google OAuth 2.0 with PKCE
- **Token storage**: `~/.config/opencode/antigravity-accounts.json`
- **Multi-account**: Supports account rotation for higher quotas
- **API endpoints**:
  - `https://daily-cloudcode-pa.sandbox.googleapis.com`
  - `https://autopush-cloudcode-pa.sandbox.googleapis.com`
  - `https://cloudcode-pa.googleapis.com`

### Available Antigravity Models
| Model Name | Type | Notes |
|------------|------|-------|
| `antigravity-gemini-3-pro` | Gemini | With thinking variants (low, high) |
| `antigravity-gemini-3-flash` | Gemini | With thinking variants (minimal, low, medium, high) |
| `antigravity-claude-sonnet-4.5-thinking` | Claude | With thinking budget variants |
| `antigravity-claude-opus-4.5-thinking` | Claude | With thinking budget variants |

---

## Phase 2: Model Mapping ✅ CONFIRMED

| Claude Code Request | → Antigravity Model | Model Type |
|--------------------|---------------------|------------|
| `*haiku*` | `antigravity-gemini-3-flash` | Gemini |
| `*sonnet*` | `antigravity-gemini-3-pro` | Gemini |
| `*opus*` | `antigravity-claude-opus-4.5-thinking` | Claude |

---

## Phase 3: Implementation Plan

### 3.1 New Files to Create

| File | Purpose |
|------|---------|
| `antigravity_auth.py` | OAuth 2.0 + PKCE flow, token refresh, account management |
| `antigravity_client.py` | Antigravity API client with endpoint fallback |
| `quota_manager.py` | Quota routing with automatic fallback |

### 3.2 Existing Files to Modify

| File | Changes |
|------|---------|
| `server.py` | Add Antigravity config to Config class; modify ModelManager for quota-aware routing; add startup event for auth init |
| `requirements.txt` | Add: `google-auth-oauth-lib`, `google-auth`, `aiohttp` |
| `.env.example` | Add: `USE_ANTIGRAVITY`, `ANTIGRAVITY_HAIKU_MODEL`, etc. |

### 3.3 Implementation Steps

**Step 1: Create OAuth Authentication Module (`antigravity_auth.py`)**
- Implement PKCE code verifier/challenge generation
- Build OAuth authorization URL with Google scopes
- Exchange authorization code for access/refresh tokens
- Token refresh logic with expiry handling
- Load/save accounts from `~/.config/opencode/antigravity-accounts.json`

Key OAuth Constants (from reference):
```python
ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
ANTIGRAVITY_CLIENT_SECRET = "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"
ANTIGRAVITY_REDIRECT_URI = "http://localhost:51121/oauth-callback"
ANTIGRAVITY_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
```

**Step 2: Create Antigravity API Client (`antigravity_client.py`)**
- HTTP client with Bearer token authentication
- Request format conversion (Anthropic → Gemini format)
- Response format conversion (Gemini → Anthropic format)
- Multi-endpoint fallback (daily → autopush → production)
- Streaming support

**Step 3: Create Quota Manager (`quota_manager.py`)**
- Track rate-limited quotas per model
- Automatic fallback from Antigravity → Gemini CLI quota
- Time-based rate limit reset tracking

**Step 4: Modify server.py**
- Add `USE_ANTIGRAVITY` config option
- Extend `ModelManager.validate_and_map_model()` to return quota type
- Route requests: Antigravity (primary) → Gemini CLI (fallback)
- Add `--antigravity-login` CLI command for OAuth setup

**Step 5: Update Dependencies**
```bash
# Add to requirements.txt
google-auth-oauth-lib>=1.0.0
google-auth>=2.20.0
aiohttp>=3.9.0
```

---

## Phase 4: Validation Plan

### Test Matrix

| Requested Model | Expected Antigravity Model | Stream | Tool Use |
|-----------------|---------------------------|--------|----------|
| `claude-3-5-haiku-20241022` | `antigravity-gemini-3-flash` | ✅ | ✅ |
| `claude-sonnet-4-5-20250514` | `antigravity-gemini-3-pro` | ✅ | ✅ |
| `claude-opus-4-5-20250514` | `antigravity-claude-opus-4.5-thinking` | ✅ | ✅ |

### Validation Steps

1. **OAuth Setup**: Run `python server.py --antigravity-login` to authenticate
2. **Start Proxy**: `python server.py` (verify Antigravity accounts loaded)
3. **Test Haiku**:
   ```bash
   curl -X POST http://localhost:8082/v1/messages \
     -H "Content-Type: application/json" \
     -d '{"model":"claude-3-5-haiku-20241022","max_tokens":100,"messages":[{"role":"user","content":"Hi"}]}'
   ```
4. **Test Sonnet + Opus**: Same as above with different models
5. **Test Streaming**: Add `"stream":true` to request
6. **Test Tool Use**: Request with tools parameter
7. **Test Fallback**: Trigger rate limit, verify fallback to Gemini CLI works

---

## Phase 5: Configuration Updates

### .env additions
```bash
# Enable Antigravity OAuth (default: false for backward compatibility)
USE_ANTIGRAVITY="true"

# Antigravity model mappings
ANTIGRAVITY_HAIKU_MODEL="antigravity-gemini-3-flash"
ANTIGRAVITY_SONNET_MODEL="antigravity-gemini-3-pro"
ANTIGRAVITY_OPUS_MODEL="antigravity-claude-opus-4.5-thinking"

# GEMINI_API_KEY remains as fallback
```

---

## Critical Files

| Path | Purpose |
|------|---------|
| `/Users/ankur/D/Playground/gemini-claude-proxy/gemini-for-claude-code/server.py` | Main FastAPI server (modify) |
| `/Users/ankur/D/Playground/gemini-claude-proxy/gemini-for-claude-code/antigravity_auth.py` | NEW: OAuth module |
| `/Users/ankur/D/Playground/gemini-claude-proxy/gemini-for-claude-code/antigravity_client.py` | NEW: API client |
| `/Users/ankur/D/Playground/gemini-claude-proxy/gemini-for-claude-code/quota_manager.py` | NEW: Quota routing |

---

## Status

- ✅ Phase 1: Discovery Complete
- ✅ Phase 2: Mapping Confirmed
- ✅ Phase 3: Implementation Plan Ready
- ✅ Phase 4: Validation Plan Ready
- ⏸️ Phase 5: Awaiting Execution (pending your review)

---

## Key Design Decisions

1. **Pure Python OAuth**: Using `google-auth-oauth-lib` instead of porting Node.js `@openauthjs/openauth`
2. **Backward Compatible**: `USE_ANTIGRAVITY=false` by default, existing behavior unchanged
3. **Dual Quota**: Antigravity (primary) → Gemini CLI (fallback)
4. **Shared Token Storage**: Uses same `~/.config/opencode/antigravity-accounts.json` as opencode for interoperability
5. **Multi-endpoint Fallback**: Tries daily → autopush → production endpoints

---

## OAuth Flow Diagram

```
User → CLI: python server.py --antigravity-login
       ↓
Browser opens: https://accounts.google.com/o/oauth2/v2/auth?...
       ↓
User grants permission
       ↓
Google redirects to: http://localhost:51121/oauth-callback?code=...
       ↓
Local server exchanges code for tokens
       ↓
Tokens stored in: ~/.config/opencode/antigravity-accounts.json
       ↓
Proxy uses access_token for API calls
```

---

## Review Decisions ✅

1. **Single account only** - No multi-account rotation for now (simpler implementation)
2. **Print URL only** - No auto-opening browser (user manually visits the URL)
3. **Add CLI commands** - Include account management commands:

| Command | Purpose |
|---------|---------|
| `--antigravity-login` | Authenticate with Google OAuth |
| `--antigravity-status` | Show current account and token status |
| `--antigravity-logout` | Remove stored credentials |
