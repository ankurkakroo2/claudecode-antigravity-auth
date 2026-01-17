# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

This is **gemini-claude-proxy**, a proxy server that translates between Anthropic's Messages API format (used by Claude Code) and Google's Gemini API. It enables using Claude Code CLI with Google Gemini or Antigravity (OAuth) models as the backend.

**Key capability:** The proxy includes Antigravity OAuth integration, which provides access to higher-quota Google AI subscription models.

---

## Repository Structure

The repository is a single top-level package:

- `server.py` - Standalone FastAPI server (legacy, can be run directly)
- `gclaude/` - Python package with CLI tool (recommended approach)

---

## Common Development Commands

### Environment Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install gclaude package in editable mode
pip install -e .
```

### Running the Proxy

**Recommended: Using gclaude CLI**
```bash
# Initialize with guided setup (OAuth + model detection)
python -m gclaude init

# Start the proxy server
python -m gclaude start

# Check status
python -m gclaude status

# View logs
python -m gclaude logs

# Follow logs in real-time
python -m gclaude logs -f

# Stop the proxy
python -m gclaude stop
```

**Alternative: Direct server.py execution**
```bash
# Run the standalone server
python server.py

# Development with auto-reload
uvicorn server:app --host 0.0.0.0 --port 8082 --reload
```

### Code Quality

```bash
# Format code with Black
black gclaude/ server.py *.py

# Lint with Ruff
ruff check gclaude/ server.py *.py

# Run both (if dev dependencies installed)
pip install -e ".[dev]"
black gclaude/
ruff check gclaude/
```

### Testing

```bash
# Run tests (if test suite exists)
pytest

# Run with coverage
pytest --cov=gclaude
```

---

## Architecture

### High-Level Design

```
Claude Code CLI
       │
       ▼ (Anthropic Messages API format)
┌──────────────────────┐
│  Proxy Server        │
│  (FastAPI)           │
└──────────────────────┘
       │
       ├─► Model Pattern Matching (*haiku*, *sonnet*, *opus*)
       │
       ├─► Mode Selection
       │    ├─► USE_ANTIGRAVITY=true → Antigravity API (OAuth)
       │    └─► USE_ANTIGRAVITY=false → Gemini API (API key)
       │
       ▼
┌──────────────────────┐
│  Translation Layer   │
│  Anthropic ↔ Gemini  │
└──────────────────────┘
       │
       ▼
Gemini or Antigravity API
```

### Key Components

**gclaude Package Structure:**

| File | Purpose |
|------|---------|
| `gclaude/cli.py` | CLI commands (init, start, stop, status, logs, auth) |
| `gclaude/server.py` | ProxyServer class - FastAPI server wrapper |
| `gclaude/config.py` | Configuration management (~/.gclaude/config.json) |
| `gclaude/detector.py` | Model access detection for Antigravity |
| `gclaude/auth.py` | OAuth UI flow |
| `gclaude/utils.py` | Utility functions (paths, process management) |
| `antigravity_auth.py` | OAuth 2.0 with PKCE implementation |
| `antigravity_client.py` | Antigravity API client |
| `quota_manager.py` | Quota management between Antigravity and Gemini |

**server.py (Legacy Standalone):**

- Single-file FastAPI application
- Can be run directly without gclaude package installation
- Contains all translation logic inline
- Uses environment variables for configuration (.env file)

### Request Flow

1. Claude Code sends request to `http://localhost:8082/v1/messages` (Anthropic format)
2. Proxy extracts model name and matches against patterns:
   - `*haiku*` → small model (e.g., `gemini-1.5-flash-latest`)
   - `*sonnet*` or `*opus*` → big model (e.g., `gemini-1.5-pro-latest`)
3. Check authentication:
   - If OAuth enabled and token valid → use Antigravity API
   - Otherwise → use Gemini API key (fallback)
4. Translate request:
   - Anthropic message format → Gemini/LiteLLM format
   - Tool definitions → Gemini function calling format
   - Content blocks (text, images, tool_use, tool_result)
5. Call backend API
6. Translate response:
   - Gemini format → Anthropic Messages API format
   - Handle streaming with error recovery
   - Convert tool calls and results

---

## Configuration

### Environment Variables (.env)

**Required:**
- `GEMINI_API_KEY` - Google AI Studio API key (fallback when OAuth unavailable)

**Optional:**
- `BIG_MODEL` - Model for sonnet/opus requests (default: `gemini-1.5-pro-latest`)
- `SMALL_MODEL` - Model for haiku requests (default: `gemini-1.5-flash-latest`)
- `HOST` - Server host (default: `0.0.0.0`)
- `PORT` - Server port (default: `8082`)
- `LOG_LEVEL` - Logging level (default: `WARNING`)
- `MAX_TOKENS_LIMIT` - Max tokens for responses (default: `8192`)
- `REQUEST_TIMEOUT` - Request timeout in seconds (default: `90`)
- `MAX_RETRIES` - LiteLLM retry attempts (default: `2`)
- `MAX_STREAMING_RETRIES` - Streaming retry attempts (default: `12`)
- `FORCE_DISABLE_STREAMING` - Disable streaming globally (default: `false`)
- `USE_ANTIGRAVITY` - Enable Antigravity OAuth (default: `false`)

### gclaude Config File (~/.gclaude/config.json)

Created by `python -m gclaude init`:

```json
{
  "version": "1.0.0",
  "proxy_host": "127.0.0.1",
  "proxy_port": 8082,
  "auth_enabled": true,
  "account_email": "user@gmail.com",
  "models": {
    "haiku": {"pattern": "*haiku*", "target": "antigravity-gemini-3-flash", "type": "antigravity"},
    "sonnet": {"pattern": "*sonnet*", "target": "antigravity-gemini-3-pro", "type": "antigravity"},
    "opus": {"pattern": "*opus*", "target": "antigravity-claude-opus-4.5-thinking", "type": "antigravity"}
  },
  "fallback_api_key": "AIzaSy..."
}
```

---

## Model Mapping

### Claude Code Patterns

The proxy maps Claude Code model requests to Gemini/Antigravity models:

| Claude Code Request | Default Mapping | Antigravity Option |
|---------------------|-----------------|-------------------|
| `*haiku*` | `gemini-1.5-flash-latest` | `antigravity-gemini-3-flash` |
| `*sonnet*` | `gemini-1.5-pro-latest` | `antigravity-gemini-3-pro-high` or `antigravity-claude-sonnet-4-5-thinking` |
| `*opus*` | `gemini-1.5-pro-latest` | `antigravity-claude-opus-4.5-thinking` |

### Available Antigravity Models

When authenticated with Google OAuth, these models may be available:

- `antigravity-gemini-3-flash` - Fast & efficient
- `antigravity-gemini-3-pro-low` - Faster responses, less thinking
- `antigravity-gemini-3-pro-high` - Deeper reasoning
- `antigravity-claude-sonnet-4-5` - Balanced capability
- `antigravity-claude-sonnet-4-5-thinking` - Extended reasoning
- `antigravity-claude-opus-4-5-thinking` - Advanced reasoning

The `gclaude init` command automatically detects which models you have access to.

---

## Translation Layer Details

### Anthropic → Gemini

**Content Blocks:**
- `text` → Gemini text content
- `image` → Gemini inline image data
- `tool_use` → Gemini function call
- `tool_result` → Gemini function response

**Tools/Functions:**
- Anthropic `Tool` format → Gemini `FunctionDeclaration`
- Schema cleaning: Removes `additionalProperties`, `default`, unsupported `format` values

**System Messages:**
- Anthropic system parameter → Gemini system instruction

### Gemini → Anthropic

**Streaming Response:**
- Gemini server-sent events → Anthropic streaming format
- Error recovery for malformed chunks
- Automatic retry with exponential backoff
- Fallback to non-streaming on persistent errors

**Tool Calls:**
- Gemini function call → Anthropic `tool_use` content block
- Generates unique tool_use_id

**Stop Reasons:**
- `STOP` → `end_turn`
- `MAX_TOKENS` → `max_tokens`
- `ERROR` → `error`

---

## API Endpoints

### Proxy Server Endpoints

- `POST /v1/messages` - Main Claude Code API endpoint
- `POST /v1/messages/count_tokens` - Token counting endpoint
- `GET /health` - Health check with API status
- `GET /test-connection` - Test API connectivity
- `GET /` - Server info and configuration
- `GET /antigravity-status` - Antigravity authentication and quota status

### Example Usage

```bash
# Test health endpoint
curl http://localhost:8082/health

# Test connection
curl http://localhost:8082/test-connection

# Start Claude Code with proxy
ANTHROPIC_BASE_URL=http://localhost:8082 claude

# Or use the anticlaude alias (created by gclaude init)
anticlaude
```

---

## Development Notes

### Adding New Models

To add a new Gemini model:

1. Add to `ModelManager.base_gemini_models` in `server.py`
2. Or set via `BIG_MODEL`/`SMALL_MODEL` environment variables
3. For Antigravity models, add to `get_available_antigravity_models()` in `gclaude/utils.py`

### Streaming Error Handling

The proxy has sophisticated streaming error recovery:
- Malformed JSON chunks are buffered and retried
- Exponential backoff for retries (configurable via `MAX_STREAMING_RETRIES`)
- Automatic fallback to non-streaming mode
- Connection error recovery for Gemini 500 errors

If experiencing streaming issues:
1. Check logs with `python -m gclaude logs`
2. Try `FORCE_DISABLE_STREAMING=true` in `.env`
3. Increase `MAX_STREAMING_RETRIES` for more resilience

### Antigravity OAuth Flow

The Antigravity integration uses OAuth 2.0 with PKCE:

1. User runs `python -m gclaude init` or `python -m gclaude auth`
2. Browser opens for Google OAuth authentication
3. Authorization code exchanged for tokens
4. Tokens stored in `~/.config/gclaude/antigravity-accounts.json`
5. Access token automatically refreshed when expired
6. Fallback to Gemini API key if OAuth fails

**Quota Management:**
- Primary: Antigravity OAuth endpoints (higher quota)
- Fallback: Gemini API key (standard quota)
- Automatic fallback on rate limit (429) or auth failure
- Multiple Antigravity endpoints tried in order

---

## File Conventions

### Configuration Files

- `.env` - Environment variables (create from `.env.example`)
- `.gitignore` - Excludes `.env`, `.venv`, `__pycache__`, etc.
- `~/.gclaude/config.json` - gclaude configuration (auto-created)
- `~/.config/gclaude/antigravity-accounts.json` - OAuth tokens (auto-created)
- `~/.claude/antigravity-settings.json` - Claude Code settings (auto-created)
- `~/.gclaude/logs/proxy.log` - Proxy server logs (auto-created)

### Python Code Style

- **Line length:** 100 characters (Black configured)
- **Imports:** Standard library → Third-party → Local
- **Logging:** Use `logging` module, not `print()`
- **Type hints:** Preferred for function signatures
- **Error messages:** Be specific and actionable

---

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Check what's using port 8082
lsof -i :8082
# Or change port in .env: PORT=8083
```

**OAuth authentication fails:**
```bash
# Remove stored accounts and try again
rm ~/.config/gclaude/antigravity-accounts.json
python -m gclaude auth
```

**Models not available:**
```bash
# Re-run model detection
python -m gclaude init
```

**Streaming errors:**
```bash
# Check logs
python -m gclaude logs

# Disable streaming temporarily
export FORCE_DISABLE_STREAMING=true
python -m gclaude restart
```

**API key issues:**
```bash
# Verify API key format (should start with "AIza" and be 39 chars)
python -c "import os; print(os.environ.get('GEMINI_API_KEY'))"

# Test connection
curl http://localhost:8082/test-connection
```

---

## Important Reminders

- **Never commit `.env` files** - Contains API keys and secrets
- **Never commit OAuth token files** - `~/.config/gclaude/antigravity-accounts.json`
- **Test proxy health** before using with Claude Code: `curl http://localhost:8082/health`
- **Check logs** when troubleshooting: `python -m gclaude logs`
- **Use gclaude CLI** for easier management vs direct `server.py` execution
- **Model detection** helps identify which Antigravity models you can access
- **Fallback works automatically** - if OAuth fails, proxy uses Gemini API key
