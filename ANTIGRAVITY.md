# Antigravity OAuth Setup Guide

This guide explains how the Antigravity OAuth integration works in gclaude.

## Overview

**Antigravity** is Google's internal AI service that provides higher-quota access to Gemini models through Google OAuth authentication. The gclaude CLI integrates with Antigravity to provide:

- **Higher rate limits** compared to standard Gemini API
- **Access to latest models** (Gemini 3, Claude Sonnet/Opus on Google infrastructure)
- **Google OAuth authentication** - no API keys needed

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────────────────────┐
│   Browser   │────▶│ Google OAuth │────▶│ Access Token (Bearer)            │
│  (User)     │     │   (accounts.  │     │ - Stored in ~/.config/gclaude/    │
│             │     │    google)   │     │ - Auto-refreshed on expiry        │
└─────────────┘     └──────────────┘     └──────────────────────────────────┘
                                                   │
                                                   ▼
                                          ┌────────────────┐
                                          │ gclaude Proxy  │
                                          │ localhost:8082 │
                                          └────────────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Antigravity API Endpoints                             │
├─────────────────────────────────────────────────────────────────────────┤
│ • https://daily-cloudcode-pa.sandbox.googleapis.com                     │
│ • https://autopush-cloudcode-pa.sandbox.googleapis.com                 │
│ • https://cloudcode-pa.googleapis.com                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## OAuth Flow (PKCE)

The authentication uses **OAuth 2.0 with PKCE** (Proof Key for Code Exchange):

1. **Generate PKCE pair**: Code verifier + code challenge
2. **Open browser**: User authorizes via Google OAuth consent screen
3. **Capture auth code**: Local HTTP server on port 51121 receives callback
4. **Exchange for tokens**: Auth code + verifier exchanged for access/refresh tokens
5. **Store tokens**: Saved to `~/.config/gclaude/antigravity-accounts.json`

## Configuration Files

### `~/.config/gclaude/antigravity-accounts.json`

Stores OAuth tokens for authenticated accounts:

```json
{
  "accounts": [
    {
      "account_id": "user@gmail.com",
      "email": "user@gmail.com",
      "access_token": "ya29.a0Af...",
      "refresh_token": "1//0g...",
      "expires_at": "2025-01-17T10:30:00Z",
      "created_at": "2025-01-16T10:30:00Z"
    }
  ]
}
```

### `~/.gclaude/config.json`

Stores model mappings and preferences:

```json
{
  "version": "1.0.0",
  "proxy_host": "127.0.0.1",
  "proxy_port": 8082,
  "auth_enabled": true,
  "account_email": "user@gmail.com",
  "models": {
    "haiku": {
      "pattern": "*haiku*",
      "target": "antigravity-gemini-3-flash",
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
  "fallback_api_key": "AIzaSy..."
}
```

### `~/.claude/antigravity-settings.json`

Claude Code settings (created by `gclaude init`):

```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "dummy-key-proxy-handles-auth",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082",
    "API_TIMEOUT_MS": "3000000"
  }
}
```

## Shell Alias (`.zshrc`)

The `anticlaude` function provides one-command access:

```bash
anticlaude() {
  echo "🤖 Anticlaude Mode Active - Using Google OAuth with Claude Code"
  echo "📡 Base URL: http://127.0.0.1:8082"

  # Wait up to 10 seconds for proxy to be healthy
  for i in {1..20}; do
    if curl -s http://127.0.0.1:8082/health > /dev/null 2>&1; then
      break
    fi
    if [ $i -eq 1 ]; then
      echo "⏳ Waiting for proxy..."
    fi
    sleep 0.5
  done

  # Final health check
  if ! curl -s http://127.0.0.1:8082/health > /dev/null 2>&1; then
    echo "❌ Error: Proxy not responding"
    echo "Start it: python -m gclaude start"
    return 1
  fi

  # Session marker for statusline
  local MARKER="/tmp/.claude-anticlaude-mode.$$"
  echo $$ > "$MARKER"

  cleanup() {
    rm -f "$MARKER"
  }
  trap cleanup EXIT INT TERM

  CLAUDE_MODE_MARKER="$MARKER" claude --settings ~/.claude/antigravity-settings.json --dangerously-skip-permissions "$@"
  cleanup
}
```

## Model Detection

The `gclaude init` command automatically detects which Antigravity models are available:

1. **OAuth authentication** required
2. **Test each model** with minimal API call
3. **Store results** in configuration
4. **Recommend mappings** based on access

### Detection Response Codes

| Status Code | Meaning |
|-------------|---------|
| 200 | Model available and accessible |
| 429 | Model exists but quota exhausted (still shows as available) |
| 401/403 | Authentication failed |
| 404 | Model not found |

## API Request Format

Antigravity uses a different API format than standard Gemini:

### Endpoint
```
POST https://cloudcode-pa.googleapis.com/v1internal:generateContent
```

### Request Headers
```
Authorization: Bearer {access_token}
Content-Type: application/json
User-Agent: antigravity/1.11.5 windows/amd64
X-Goog-Api-Client: google-cloud-sdk vscode_cloudshelleditor/0.1
Client-Metadata: {"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}
```

### Request Body
```json
{
  "project": "rising-fact-p41fc",
  "model": "gemini-3-flash",
  "request": {
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "hi"}]
      }
    ],
    "generationConfig": {
      "maxOutputTokens": 1
    }
  },
  "userAgent": "antigravity"
}
```

## Troubleshooting

### OAuth Issues

**Problem**: Authentication fails or token expired

**Solution**:
```bash
# Re-authenticate
python -m gclaude auth
```

### 429 Quota Exhausted

**Problem**: Model returns 429 (quota exhausted)

**Solution**:
- Wait for quota to reset (usually hourly)
- Or fall back to standard Gemini API key

### Proxy Not Responding

**Problem**: `anticlaude` shows "Proxy not responding"

**Solution**:
```bash
# Start the proxy
python -m gclaude start

# Check status
python -m gclaude status

# View logs
python -m gclaude logs -f
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTIGRAVITY_CLIENT_ID` | Override OAuth client ID | NoeFabris's client ID |
| `ANTIGRAVITY_CLIENT_SECRET` | Override OAuth client secret | NoeFabris's secret |
| `ANTIGRAVITY_REDIRECT_URI` | OAuth callback URL | `http://localhost:51121/oauth-callback` |

## Security Notes

- Access tokens are stored locally in `~/.config/gclaude/`
- Tokens are automatically refreshed when expired
- The default client ID is from NoeFabris's opencode-antigravity-auth project
- You can override with your own Google Cloud OAuth client

## References

- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2)
- [PKCE RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636)
- [opencode-antigravity-auth](https://github.com/NoeFabris/opencode-antigravity-auth)
