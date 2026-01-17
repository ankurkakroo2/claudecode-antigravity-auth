# Antigravity OAuth Fix

## Problem
The proxy was failing with "Gemini Code Assist license" error when using Antigravity OAuth mode. The root cause was that the implementation was missing several critical components that the OpenCode antigravity-auth implementation has.

## Changes Made

### 1. Added Missing OAuth Scopes (`antigravity_auth.py`)
Added three critical scopes that were missing:
- `https://www.googleapis.com/auth/userinfo.profile`
- `https://www.googleapis.com/auth/cclog`
- `https://www.googleapis.com/auth/experimentsandconfigs`

These scopes tell Google that you're accessing Antigravity specifically, not just the regular Gemini API.

### 2. Project ID Discovery (`antigravity_auth.py`)
Added `discover_project_id()` function that:
- Calls the `/v1internal:loadCodeAssist` endpoint
- Dynamically discovers your Google Cloud project ID
- Tries multiple endpoints in order with fallback

This is critical because the hardcoded project ID `rising-fact-p41fc` is a fallback that doesn't have Antigravity licenses. You need to use YOUR actual Google Cloud project.

### 3. Updated Token Storage (`antigravity_auth.py`)
- Added `project_id` field to `AntigravityAccount` class
- Project ID is now discovered during OAuth authentication
- Stored in `~/.config/gclaude/antigravity-accounts.json`

### 4. Updated API Requests (`antigravity_client.py`)
Added missing fields to Antigravity API requests:
- `requestType: "agent"` - Tells Antigravity to use agent code assist quota
- `requestId: "agent-<uuid>"` - Unique request ID for tracking
- Uses discovered `project_id` instead of hardcoded fallback

### 5. Updated Client Initialization (`antigravity_client.py`, `quota_manager.py`)
- `AntigravityClient` now requires `project_id` parameter
- `quota_manager` extracts project_id from account and passes it to client

### 6. Fixed Server Startup Validation (`server.py`)
- Modified `validate_startup()` to allow Antigravity-only mode without GEMINI_API_KEY
- Added better logging for debugging

### 7. Fixed Model Name Preservation (`server.py`)
- Extract raw model from request body before Pydantic validation
- Ensures original Claude model name (e.g., `claude-sonnet-4-5-20250514`) is preserved
- Previous bug was converting it to Gemini model name before Antigravity routing

## How to Apply the Fix

### Step 1: Delete Old OAuth Accounts
```bash
rm ~/.config/gclaude/antigravity-accounts.json
```

### Step 2: Re-authenticate
```bash
cd /Users/ankur/D/Playground/gemini-claude-proxy
source .venv/bin/activate
python -m gclaude auth
```

This will:
1. Open your browser for Google OAuth
2. Request the new scopes (including `cclog` and `experimentsandconfigs`)
3. Discover your Google Cloud project ID
4. Store the project ID with your token

### Step 3: Restart the Proxy
```bash
python -m gclaude restart
```

### Step 4: Verify
Check that project ID was discovered:
```bash
cat ~/.config/gclaude/antigravity-accounts.json | jq .accounts[0].project_id
```

You should see your actual Google Cloud project ID, not `rising-fact-p41fc`.

## Why This Works

The OpenCode implementation works because it:
1. Uses the correct OAuth scopes that signal Antigravity access
2. Discovers YOUR Google Cloud project (not a hardcoded one)
3. Sends `requestType: "agent"` which tells Google to use Antigravity quota
4. Includes a `requestId` for proper request tracking

The previous implementation was:
- Missing critical scopes
- Using a hardcoded project ID that doesn't have licenses
- Missing the `requestType: "agent"` field

## Testing

After re-authenticating, test the proxy:

```bash
curl -s -X POST http://127.0.0.1:8082/v1/messages \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: dummy-key' \
  -d '{
    "model": "claude-sonnet-4-5-20250514",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "Say hello"}]
  }'
```

You should now get a successful response from Antigravity!

## Files Modified

1. `antigravity_auth.py` - OAuth scopes, project ID discovery, account storage
2. `antigravity_client.py` - Project ID parameter, requestType/requestId fields
3. `quota_manager.py` - Pass project ID to client
4. `server.py` - Startup validation, model name preservation

## References

- OpenCode Antigravity Auth: https://github.com/NoeFabris/opencode-antigravity-auth
- Issue #191: Discussion about the license error and solution
