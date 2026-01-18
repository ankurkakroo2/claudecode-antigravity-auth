# gclaude Architecture

This document describes the architecture and file structure of the gclaude package.

## Purpose

**gclaude** is a Python package that provides a CLI tool for running a proxy server that translates Claude Code API requests to Antigravity models (OAuth).

## File Structure

```
gclaude/
├── __init__.py           # Package constants (paths, version)
├── cli.py                # CLI commands (init, start, stop, status, logs, auth)
├── config.py             # Configuration management
├── server.py             # ProxyServer class (process wrapper)
├── detector.py           # Model access detection
├── auth.py               # Rich UI for OAuth authentication
├── shell.py              # Shell helper installer (gclaude)
├── utils.py              # Utility functions
└── proxy/                # Proxy implementation modules
    ├── server.py         # FastAPI app (Claude ↔ Antigravity)
    ├── antigravity_client.py # Antigravity API client
    ├── antigravity_auth.py   # OAuth 2.0 with PKCE implementation
    └── quota_manager.py      # Quota/rate-limit management
```

## Component Overview

### `__init__.py`

Defines package-level constants:

- `CONFIG_DIR`: `~/.gclaude`
- `CONFIG_FILE`: `~/.gclaude/config.json`
- `PID_FILE`: `~/.gclaude/proxy.pid`
- `LOG_FILE`: `~/.gclaude/logs/proxy.log`

### `cli.py` - CLI Entry Point

Provides the `gclaude` command with subcommands:

| Command | Function |
|---------|----------|
| `init` | Guided setup wizard |
| `start` | Start proxy server |
| `stop` | Stop proxy server |
| `restart` | Restart proxy server |
| `status` | Show status dashboard |
| `logs` | Show/follow logs |
| `auth` | Manage OAuth accounts |
| `config` | View configuration |

**Dependencies**:
- `click` - CLI framework
- `rich` - Terminal UI
- `questionary` - Interactive prompts
- `config.py` - Config management
- `gclaude/server.py` - ProxyServer
- `detector.py` - Model detection
- `auth.py` - OAuth UI

### `config.py` - Configuration Management

Manages the gclaude configuration file.

**Key classes**:
- `Config` - Load/save/configure gclaude settings

**Configuration structure**:
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
    "haiku": {"pattern": "*haiku*", "target": "...", "type": "antigravity"},
    "sonnet": {"pattern": "*sonnet*", "target": "...", "type": "antigravity"},
    "opus": {"pattern": "*opus*", "target": "...", "type": "antigravity"}
  }
}
```

### `gclaude/server.py` - ProxyServer Wrapper

Manages the proxy server process (start/stop/status).

**Key classes**:
- `ProxyServer` - Manages the proxy server lifecycle

### `gclaude/proxy/server.py` - Proxy Server

Implements the FastAPI server that translates between Claude Code and Antigravity APIs.

**Endpoints**:
- `POST /v1/messages` - Main Claude Code API endpoint
- `POST /v1/messages/count_tokens` - Token counting endpoint
- `GET /health` - Health check
- `GET /antigravity-status` - OAuth status + quota
- `GET /` - Root/info endpoint

**Request flow**:
1. Receive Anthropic-format request from Claude Code
2. Match model pattern to configured target
3. Translate to Antigravity format
4. Call backend API
5. Translate response back to Anthropic format
6. Return to Claude Code

### `detector.py` - Model Access Detection

Tests which Antigravity models are available to the authenticated user.

**Key functions**:
- `test_model_access()` - Test single model availability
- `detect_model_access()` - Test all models
- `detect_with_rich_output()` - Rich UI for detection
- `get_available_models_for_mapping()` - Get available models for setup

**Detection logic**:
- Sends minimal test request to each Antigravity model
- Returns `True` if 200 or 429 (quota exhausted but exists)
- Returns `False` if 401/403/404 or error

### `auth.py` - OAuth UI

Provides rich terminal UI for OAuth authentication flow.

**Key functions**:
- `init_auth_with_rich_output()` - Guided OAuth authentication
- `list_accounts()` - Display authenticated accounts
- `get_valid_access_token()` - Get fresh access token

**Dependencies**:
- `proxy/antigravity_auth.py` - OAuth implementation
- `rich` - Terminal UI

### `proxy/antigravity_auth.py` - OAuth Implementation

Implements OAuth 2.0 with PKCE for Google authentication.

**Key classes**:
- `AntigravityAuthManager` - Manage OAuth accounts and tokens

### `proxy/antigravity_client.py` - API Client

Client for calling the Antigravity API.

**Key classes**:
- `AntigravityClient` - API client with authentication

**Key functions**:
- `get_api_model_name()` - Strip `antigravity-` prefix for API calls
- `get_headers()` - Build request headers with auth
- `call_model()` - Call Antigravity model

**API endpoints tried**:
1. `https://daily-cloudcode-pa.sandbox.googleapis.com`
2. `https://autopush-cloudcode-pa.sandbox.googleapis.com`
3. `https://cloudcode-pa.googleapis.com`

### `shell.py` - Shell Helper Installer

Installs the `gclaude` shell function into `.zshrc`/`.bashrc` with auto-start
and configuration checks.

### `utils.py` - Utilities

General utility functions.

**Key functions**:
- `get_config_dir()` - Get/create config directory
- `get_config_path()` - Get config file path
- `get_pid_path()` - Get PID file path
- `get_log_path()` - Get/create log file path
- `load_config()` - Load configuration from file
- `save_config()` - Save configuration to file
- `get_shell_rc_path()` - Detect shell RC file (.zshrc, .bashrc, etc.)
- `is_proxy_running()` - Check if proxy is running
- `get_default_models()` - Get default model mappings
- `get_available_antigravity_models()` - List all Antigravity models

## Request Flow Diagram

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│ Claude Code │────▶│ ProxyServer  │────▶│ Pattern Match    │
│             │     │ (FastAPI)    │     │ *haiku*/*sonnet* │
└─────────────┘     └───────────────────┘     └────────┬─────────┘
                                                    │
                                    ┌───────────────┼───────────────┐
                                    ▼               ▼               ▼
                             ┌──────────┐   ┌──────────┐   ┌──────────┐
                             │ haiku    │   │ sonnet   │   │ opus     │
                             │ mapping  │   │ mapping  │   │ mapping  │
                             └────┬─────┘   └────┬─────┘   └────┬─────┘
                                  │              │              │
                                  └──────────────┼──────────────┘
                                                 ▼
                                    ┌───────────────────────┐
                                    │ Antigravity OAuth     │
                                    │ (access_token valid?) │
                                    └───────────┬───────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │ Translate Response    │
                                    │ Antigravity → Anthropic│
                                    └───────────┬───────────┘
                                                ▼
                                    ┌───────────────────────┐
                                    │ Return to Claude Code │
                                    └───────────────────────┘
```

## Dependencies

```
click>=8.0.0          # CLI framework
questionary>=2.0.0    # Interactive prompts
rich>=13.0.0          # Terminal UI
aiohttp>=3.9.0        # Async HTTP client
google-auth-oauthlib  # Google OAuth
google-auth>=2.20.0   # Google Auth
fastapi>=0.115.0      # Web framework
uvicorn>=0.34.0       # ASGI server
litellm>=1.40.0       # LLM abstraction
python-dotenv>=1.0.0  # Environment variables
psutil>=5.9.0         # Process utilities
```
