# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

This is **gemini-claude-proxy**, an **Antigravity OAuth-only** proxy server that translates between Anthropic's Messages API format (used by Claude Code) and the Antigravity API. It enables using Claude Code CLI with Google OAuth-backed models (Claude + Gemini via Antigravity).

**Key capability:** Antigravity OAuth integration with higher-quota Google AI subscription models.

---

## Repository Structure

- `gclaude/` - Python package with CLI tool (recommended approach)
- `gclaude/proxy/server.py` - FastAPI app (can be run directly)

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

**Alternative: Direct proxy module execution**
```bash
# Run the standalone server
python -m gclaude.proxy.server

# Development with auto-reload
uvicorn gclaude.proxy.server:app --host 0.0.0.0 --port 8082 --reload
```

### Code Quality

```bash
# Format code with Black
black gclaude/ gclaude/proxy/ *.py

# Lint with Ruff
ruff check gclaude/ gclaude/proxy/ *.py

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
       └─► Antigravity API (OAuth)
              │
              ▼
        Antigravity Backend
```

### Key Components

| File | Purpose |
|------|---------|
| `gclaude/cli.py` | CLI commands (init, start, stop, status, logs, auth) |
| `gclaude/server.py` | ProxyServer class - FastAPI server wrapper |
| `gclaude/config.py` | Configuration management (~/.gclaude/config.json) |
| `gclaude/detector.py` | Model access detection for Antigravity |
| `gclaude/auth.py` | OAuth UI flow |
| `gclaude/utils.py` | Utility functions (paths, process management) |
| `gclaude/proxy/antigravity_auth.py` | OAuth 2.0 with PKCE implementation |
| `gclaude/proxy/antigravity_client.py` | Antigravity API client |
| `gclaude/proxy/quota_manager.py` | Quota management |
| `gclaude/proxy/server.py` | FastAPI app (Claude ↔ Antigravity) |

### Request Flow

1. Claude Code sends request to `http://localhost:8082/v1/messages` (Anthropic format)
2. Proxy extracts model name and matches against patterns:
   - `*haiku*` → `ANTIGRAVITY_HAIKU_MODEL`
   - `*sonnet*` → `ANTIGRAVITY_SONNET_MODEL`
   - `*opus*` → `ANTIGRAVITY_OPUS_MODEL`
3. Proxy translates request to Antigravity format and forwards via OAuth
4. Response is translated back to the Anthropic Messages API format

---

## Configuration

### Environment Variables

**Optional:**
- `HOST` - Server host (default: `0.0.0.0`)
- `PORT` - Server port (default: `8082`)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `MAX_TOKENS_LIMIT` - Max tokens for responses (default: `8192`)
- `REQUEST_TIMEOUT` - Request timeout in seconds (default: `90`)
- `MAX_RETRIES` - Retry attempts (default: `2`)
- `MAX_STREAMING_RETRIES` - Streaming retry attempts (default: `12`)
- `FORCE_DISABLE_STREAMING` - Disable streaming globally (default: `false`)
- `EMERGENCY_DISABLE_STREAMING` - Emergency streaming disable (default: `false`)
- `TOKEN_COUNTER_MODEL` - Token counter model id (default: `gemini-1.5-flash-latest`)

**Antigravity Model Overrides:**
- `ANTIGRAVITY_HAIKU_MODEL` (default: `antigravity-gemini-3-flash`)
- `ANTIGRAVITY_SONNET_MODEL` (default: `antigravity-claude-sonnet-4-5-thinking`)
- `ANTIGRAVITY_OPUS_MODEL` (default: `antigravity-claude-opus-4-5-thinking`)

### gclaude Config File (`~/.gclaude/config.json`)

Created by `python -m gclaude init`:

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
    "account_email": "user@gmail.com"
  },
  "models": {
    "haiku": {"pattern": "*haiku*", "target": "antigravity-gemini-3-flash", "type": "antigravity"},
    "sonnet": {"pattern": "*sonnet*", "target": "antigravity-claude-sonnet-4-5-thinking", "type": "antigravity"},
    "opus": {"pattern": "*opus*", "target": "antigravity-claude-opus-4-5-thinking", "type": "antigravity"}
  }
}
```

---

## Model Mapping

The proxy maps Claude Code model requests to Antigravity models:

| Claude Code Request | Default Mapping |
|---------------------|-----------------|
| `*haiku*` | `antigravity-gemini-3-flash` |
| `*sonnet*` | `antigravity-claude-sonnet-4-5-thinking` |
| `*opus*` | `antigravity-claude-opus-4-5-thinking` |

### Available Antigravity Models

When authenticated with Google OAuth, these models may be available:

- `antigravity-gemini-3-flash`
- `antigravity-gemini-3-pro-low`
- `antigravity-gemini-3-pro-high`
- `antigravity-claude-sonnet-4-5`
- `antigravity-claude-sonnet-4-5-thinking`
- `antigravity-claude-opus-4-5-thinking`

The `gclaude init` command automatically detects which models you have access to.

---

## Translation Layer Details

### Anthropic → Antigravity

**Content Blocks:**
- `text` → Antigravity text content
- `image` → Antigravity inline image data
- `tool_use` → Antigravity function call
- `tool_result` → Antigravity function response

**Tools/Functions:**
- Anthropic `Tool` format → Antigravity function declaration
- Schema cleaning: Removes unsupported JSON-schema fields

**System Messages:**
- Anthropic `system` parameter → Antigravity system instruction

### Antigravity → Anthropic

**Streaming Response:**
- Handles partial chunks and malformed JSON with retry/backoff
- Converts tool calls and results to Anthropic format

**Non-Streaming Response:**
- Converts response content to Anthropic Messages API output
- Normalizes stop reasons and token usage metadata
