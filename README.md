# Antigravity OAuth Proxy for Claude Code

---

## Install (No Repo Clone)

One-line install that adds the `anticlaude` helper to your shell and sets up the proxy runner:

```bash
curl -fsSL https://raw.githubusercontent.com/ankurkakroo2/claudecode-antigravity-auth/main/scripts/install.sh | bash
```

After install:
- Initialize OAuth + model mappings: `gclaude init`
- If needed: `gcloud init`
- Run Claude Code with auto-starting proxy: `anticlaude "your prompt"`

You can also install the helper manually with:

```bash
gclaude install-shell
```

## Quick Start (OAuth / Google AI Pro)

This proxy is **Antigravity-only** (Google OAuth). No Gemini API key is supported or required.

1. **Clone and enter the repo**
   ```bash
   git clone <your-repo-url>
   cd <repo-directory>
   ```
2. **Create a virtual environment and install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```
3. **Run OAuth setup + model detection**
   ```bash
   python -m gclaude init
   ```
4. **Install the shell helper (auto-starts proxy)**
   ```bash
   gclaude install-shell
   source ~/.zshrc   # or ~/.bashrc
   ```
5. **Run Claude Code via the helper**
   ```bash
   anticlaude "ping"
   ```
6. **Verify**
   ```bash
   opencode run -m google/antigravity-claude-sonnet-4-5-thinking "ping"
   opencode run -m google/antigravity-claude-opus-4-5-thinking "ping"
   anticlaude -p --model sonnet "ping"
   anticlaude -p --model opus "ping"
   ```

## Docs

Project docs live in `docs/`:
- `docs/LLD.md` (low-level design / architecture)
- `docs/IMPLEMENTATION_PLAN.md` (current plan)
- `docs/RUNNING_NOTES.md` (live progress + fixes + remaining issues)

Older notes were moved to `.archived/`.

### gclaude at a glance

`gclaude` provides:
- OAuth authentication (PKCE) for Antigravity
- Model detection and interactive mapping
- Start/stop/status/logs for the proxy

See the [gclaude CLI](#gclaude-cli) section for full commands and config paths.

---

This server bridges **Claude Code** with **Antigravity (Google OAuth)**. It translates requests from Anthropic's Messages API format into the Antigravity API and converts responses back so Claude Code can work seamlessly.
## Features

- **Antigravity OAuth (Google AI Pro)**: Use Claude Sonnet/Opus via Google OAuth.
- **Claude Code Compatibility**: Works with Claude Code CLI and its tool-call format.
- **Model Mapping**: Maps Claude Code aliases (`haiku`, `sonnet`, `opus`) to Antigravity model IDs.
- **Streaming Support**: Handles streaming responses with retries for malformed chunks.
- **Tool Use Translation**: Converts Claude tool calls to Antigravity function schemas.
- **Token Counting**: `/v1/messages/count_tokens` endpoint compatible with Claude Code.
- **Diagnostics**: `/health` and `/antigravity-status` for troubleshooting.

## Prerequisites

- Python 3.8+.
- Claude Code CLI installed (e.g., `npm install -g @anthropic-ai/claude-code`).
- Google AI Pro subscription (OAuth / Antigravity).
- Optional: OpenCode CLI (`opencode`) for quick verification.

## Usage with Claude Code

1. **Use the shell helper (recommended)**: `anticlaude` auto-starts the proxy, writes
   `~/.claude/antigravity-settings.json`, and uses `~/.claude/mcp_config.json` if present.
   ```bash
   anticlaude "summarize my repo"
   ```
   If Claude Code asks for a token, set `ANTHROPIC_AUTH_TOKEN` to any dummy value.

2. **Manual mode (optional)**:
   ```bash
   claude --settings ~/.claude/antigravity-settings.json
   ```
   `gclaude init` generates `~/.claude/antigravity-settings.json` automatically.

3. **Quick non-interactive test**
   ```bash
   anticlaude -p --model sonnet "ping"
   anticlaude -p --model opus "ping"
   ```

## How It Works

1. Claude Code sends Anthropic-format requests to the proxy (`http://localhost:8082`).
2. The proxy maps Claude model aliases to Antigravity model IDs.
3. Requests are translated to the Antigravity API format and sent with OAuth.
4. Responses are converted back to Anthropic format and returned to Claude Code.

## Model Mapping for Claude Code

Model aliases map to Antigravity models:
- `ANTIGRAVITY_HAIKU_MODEL` (default: `antigravity-gemini-3-flash`)
- `ANTIGRAVITY_SONNET_MODEL` (default: `antigravity-claude-sonnet-4-5-thinking`)
- `ANTIGRAVITY_OPUS_MODEL` (default: `antigravity-claude-opus-4-5-thinking`)

If Claude Code requests a full `antigravity-*` model ID, the proxy will use it directly.

## Endpoints

- `POST /v1/messages`: Claude Code messages endpoint.
- `POST /v1/messages/count_tokens`: Token count estimation using local model metadata.
- `GET /health`: Health status, streaming settings, and Antigravity status.
- `GET /antigravity-status`: OAuth account + quota status.
- `GET /`: Root endpoint with configuration summary.

## Error Handling & Troubleshooting

**Streaming Errors (malformed chunks):**
- The proxy retries malformed chunk parsing automatically.
- Set `FORCE_DISABLE_STREAMING=true` if you need a temporary fallback.

**Connection Timeouts:**
- Increase `REQUEST_TIMEOUT` if you see frequent timeouts.
- Check network connectivity and firewall settings.

**Rate Limiting:**
- Check `python -m gclaude status` or `/antigravity-status` for quota info.

**Antigravity OAuth Issues:**
- Re-run `python -m gclaude init` if you see auth or token errors.

## Logging

Logs show request routing, retries, and conversion details. Adjust verbosity with `LOG_LEVEL`:
- `DEBUG`: Detailed request/response logging
- `INFO`: General operation logging
- `WARNING`: Error recovery notifications (recommended)
- `ERROR`: Only errors and failures

## Performance Tips

- Use `ANTIGRAVITY_*` model IDs that match your access.
- Keep streaming enabled for interactive output; the proxy handles retries.
- Increase `REQUEST_TIMEOUT` for large requests.
- Adjust `MAX_STREAMING_RETRIES` for unstable networks.

## Contributing

Contributions, issues, and feature requests are welcome.

Areas where contributions are especially valuable:
- Antigravity model routing improvements
- Error recovery strategies
- Documentation improvements

---

## gclaude CLI

### Installation

```bash
pip install -e .
```

### Usage

```bash
# Initialize with guided setup
python -m gclaude init

# Start the proxy
python -m gclaude start

# Check status
python -m gclaude status

# View logs
python -m gclaude logs

# Follow logs live
python -m gclaude logs -f
```

### Features

**Model Detection:** Automatically detects which Antigravity models are available to your account.

**Interactive Mapping:** Select which models to use for haiku/sonnet/opus requests based on your access.

**OAuth Management:** Add, remove, and list Antigravity OAuth accounts.

**Status Dashboard:** Terminal UI showing proxy status, auth state, and model routes.

### Configuration Files

| File | Location |
|------|----------|
| Config | `~/.gclaude/config.json` |
| OAuth Tokens | `~/.config/gclaude/antigravity-accounts.json` |
| Logs | `~/.gclaude/logs/proxy.log` |

### Model Routes

| Claude Code Pattern | Antigravity Model | Description |
|---------------------|-------------------|-------------|
| `*haiku*` | `antigravity-gemini-3-flash` | Fast & efficient - Best for haiku requests |
| `*sonnet*` | `antigravity-claude-sonnet-4-5-thinking` | Extended reasoning - For complex tasks |
| `*opus*` | `antigravity-claude-opus-4-5-thinking` | Advanced reasoning - Best for opus requests |

**Full list of available Antigravity models:**
| Model ID | Name | Description |
|----------|------|-------------|
| `antigravity-gemini-3-flash` | Gemini 3 Flash | Fast & efficient - Best for haiku requests |
| `antigravity-gemini-3-pro-low` | Gemini 3 Pro Low | Faster responses with less thinking |
| `antigravity-gemini-3-pro-high` | Gemini 3 Pro High | Deeper reasoning with more thinking |
| `antigravity-claude-sonnet-4-5` | Claude Sonnet 4.5 | Balanced capability - Good for general coding |
| `antigravity-claude-sonnet-4-5-thinking` | Claude Sonnet 4.5 (Thinking) | Extended reasoning - For complex tasks |
| `antigravity-claude-opus-4-5-thinking` | Claude Opus 4.5 (Thinking) | Advanced reasoning - Best for opus requests |
| `antigravity-gpt-oss-120b-medium` | GPT-OSS 120B Medium | Open source alternative - Medium capability |

### Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  Claude Code    │────▶│  gclaude Proxy   │────▶│  Antigravity API        │
│  (claude cli)   │     │  (localhost:8082)│     │  (Google OAuth)         │
└─────────────────┘     └──────────────────┘     └─────────────────────────┘
```

**Request Flow:**
1. Claude Code sends Anthropic-format requests to `http://localhost:8082`
2. Proxy translates to Antigravity format and routes via OAuth
3. Responses are translated back to Anthropic format for Claude Code
