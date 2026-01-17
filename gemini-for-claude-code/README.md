# FOR OFFICIAL GOOGLE AI CLI TOOL SEE https://github.com/google-gemini/gemini-cli

# Gemini for Claude Code: An Anthropic-Compatible Proxy

---

## Quick Start (OAuth / Google AI Pro)

This path uses Google OAuth (Antigravity) and is the recommended way to get **Claude Sonnet/Opus** via a Google AI Pro subscription. No Gemini API key needed.

1. **Create a virtual environment and install dependencies**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```
2. **Run OAuth setup + model detection**
   ```bash
   python -m gclaude init
   ```
3. **Start the proxy**
   ```bash
   python -m gclaude start
   ```
4. **Create Claude Code settings**
   ```bash
   cat > ~/.claude/antigravity-settings.json <<'JSON'
   {
     "env": {
       "ANTHROPIC_AUTH_TOKEN": "dummy-key-proxy-handles-auth",
       "ANTHROPIC_BASE_URL": "http://127.0.0.1:8082"
     }
   }
   JSON
   ```
5. **Optional: add a shell helper**
   ```bash
   anticlaude() {
     claude --settings ~/.claude/antigravity-settings.json --dangerously-skip-permissions "$@"
   }
   ```
6. **Verify**
   ```bash
   opencode run -m google/antigravity-claude-sonnet-4-5-thinking "ping"
   opencode run -m google/antigravity-claude-opus-4-5-thinking "ping"
   anticlaude -p --model sonnet "ping"
   anticlaude -p --model opus "ping"
   ```

### gclaude at a glance

`gclaude` provides:
- OAuth authentication (PKCE) for Antigravity
- Model detection and interactive mapping
- Start/stop/status/logs for the proxy

See the [gclaude CLI](#gclaude-cli) section for full commands and config paths.

---

This server acts as a bridge, enabling you to use **Claude Code** with Google's powerful **Gemini models**. It translates API requests and responses between the Anthropic format (used by Claude Code) and the Gemini format (via LiteLLM), allowing seamless integration.

![Claude Code with Gemini Proxy](image.png)

## Features

- **Antigravity OAuth (Google AI Pro)**: Use Claude Sonnet/Opus via Google OAuth (no API key required).
- **Claude Code Compatibility with Gemini**: Directly use the Claude Code CLI with Google Gemini models.
- **Seamless Model Mapping**: Intelligently maps Claude Code model requests (e.g., `haiku`, `sonnet`, `opus` aliases) to your chosen Gemini models.
- **LiteLLM Integration**: Leverages LiteLLM for robust and flexible interaction with the Gemini API.
- **Enhanced Streaming Support**: Handles streaming responses from Gemini with robust error recovery for malformed chunks and API errors.
- **Complete Tool Use for Claude Code**: Translates Claude Code's tool usage (function calling) to and from Gemini's format, with robust handling of tool results.
- **Advanced Error Handling**: Provides specific and actionable error messages for common Gemini API issues with automatic fallback strategies.
- **Resilient Architecture**: Gracefully handles Gemini API instability with smart retry logic and fallback to non-streaming modes.
- **Diagnostic Endpoints**: Includes `/health` and `/test-connection` for easier troubleshooting of your setup.
- **Token Counting**: Offers a `/v1/messages/count_tokens` endpoint compatible with Claude Code.

## Recent Improvements (v2.5.0)

### 🛡️ Enhanced Error Resilience
- **Malformed Chunk Recovery**: Automatically detects and handles malformed JSON chunks from Gemini streaming
- **Smart Retry Logic**: Exponential backoff with configurable retry limits for streaming errors
- **Graceful Fallback**: Seamlessly switches to non-streaming mode when streaming fails
- **Buffer Management**: Intelligent chunk buffering and reconstruction for incomplete JSON
- **Connection Stability**: Handles Gemini 500 Internal Server Errors with automatic retry

### 📊 Improved Monitoring
- **Detailed Error Classification**: Specific guidance for different types of Gemini API errors
- **Enhanced Logging**: Comprehensive error tracking with malformed chunk statistics
- **Real-time Status**: Better health checks and connection testing

## Prerequisites

- Python 3.8+.
- Claude Code CLI installed (e.g., `npm install -g @anthropic-ai/claude-code`).
- One of:
  - Google AI Pro subscription (OAuth / Antigravity) for Claude Sonnet/Opus.
  - Gemini API key (AI Studio) for the API-key path.
- Optional: OpenCode CLI (`opencode`) for quick Antigravity verification.

## Setup (API Key / Gemini AI Studio)

If you are using the OAuth Quick Start above, you can skip this section.

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/coffeegrind123/gemini-code.git # Or your fork
    cd gemini-code
    ```

2.  **Create and activate a virtual environment** (recommended):
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**:
    Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
    Edit `.env` and add your Gemini API key. You can also customize model mappings and server settings:
    ```dotenv
    # Required: Your Google AI Studio API key
    GEMINI_API_KEY="your-google-ai-studio-key"

    # Optional: Model mappings for Claude Code aliases
    BIG_MODEL="gemini-1.5-pro-latest"    # For 'sonnet' or 'opus' requests
    SMALL_MODEL="gemini-1.5-flash-latest" # For 'haiku' requests
    
    # Optional: Server settings
    HOST="0.0.0.0"
    PORT="8082"
    LOG_LEVEL="WARNING"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    
    # Optional: Performance and reliability settings
    MAX_TOKENS_LIMIT="8192"           # Max tokens for Gemini responses
    REQUEST_TIMEOUT="90"              # Request timeout in seconds
    MAX_RETRIES="2"                   # LiteLLM retries to Gemini
    MAX_STREAMING_RETRIES="12"         # Streaming-specific retry attempts
    
    # Optional: Streaming control (use if experiencing issues)
    FORCE_DISABLE_STREAMING="false"     # Disable streaming globally
    EMERGENCY_DISABLE_STREAMING="false" # Emergency streaming disable

    # Optional: OAuth / Antigravity (only if running server.py directly)
    USE_ANTIGRAVITY="true"
    ANTIGRAVITY_HAIKU_MODEL="antigravity-gemini-3-flash"
    ANTIGRAVITY_SONNET_MODEL="antigravity-claude-sonnet-4-5-thinking"
    ANTIGRAVITY_OPUS_MODEL="antigravity-claude-opus-4-5-thinking"
    ```

5.  **Run the server**:
    The `server.py` script includes a `main()` function that starts the Uvicorn server:
    ```bash
    python server.py
    ```
    For development with auto-reload (restarts when you save changes to `server.py`):
    ```bash
    uvicorn server:app --host 0.0.0.0 --port 8082 --reload
    ```
    You can view all startup options, including configurable environment variables, by running:
    ```bash
    python server.py --help
    ```

## Usage with Claude Code

1.  **Start the Proxy Server**: Ensure the Gemini proxy server (this application) is running (see step 5 above).

2.  **Configure Claude Code to Use the Proxy**:
    Choose one of the following:

    **OAuth (Antigravity)**
    ```bash
    claude --settings ~/.claude/antigravity-settings.json
    # or:
    anticlaude
    ```

    **API key path**
    ```bash
    ANTHROPIC_BASE_URL=http://localhost:8082 claude
    ```
    Replace `localhost:8082` if your proxy is running on a different host or port.

    **Quick non-interactive test**
    ```bash
    anticlaude -p --model sonnet "ping"
    anticlaude -p --model opus "ping"
    ```

3.  **Utilize `CLAUDE.md` for Optimal Gemini Performance (Crucial)**:
    - This repository includes a `CLAUDE.md` file. This file contains specific instructions and best practices tailored to help **Gemini** effectively understand and respond to **Claude Code's** unique command structure, tool usage patterns, and desired output formats.
    - **Copy `CLAUDE.md` into your project directory**:
      ```bash
      cp /path/to/gemini-code/CLAUDE.md /your/project/directory/
      ```
    - When starting a new conversation with Claude Code in that directory, begin with:
      ```
      First read and process CLAUDE.md with intent. After understanding and agreeing to use the policies and practices outlined in the document, respond with YES
      ```
    - This ensures Gemini receives important context and instructions for better assistance.
  
    - If Gemini still struggles, ask it to re-read `CLAUDE.md` and restart the session.

## How It Works: Powering Claude Code with Gemini

1.  **Claude Code Request**: You issue a command or prompt in the Claude Code CLI.
2.  **Anthropic Format**: Claude Code sends an API request (in Anthropic's Messages API format) to the proxy server's address (`http://localhost:8082`).
3.  **Proxy Translation (Anthropic to Gemini)**: The proxy server:
    *   Receives the Anthropic-formatted request.
    *   Validates it and maps any Claude model aliases (like `claude-3-sonnet...`) to the corresponding Gemini model specified in your `.env` (e.g., `gemini-1.5-pro-latest`).
    *   Translates the message structure, content blocks, and tool definitions into a format LiteLLM can use with the Gemini API.
4.  **Antigravity or Gemini**: The proxy sends the request to:
    - **Antigravity (OAuth)** for Google AI Pro / Claude Sonnet/Opus, or
    - **Gemini (API key)** for standard Gemini models.
5.  **Model Response**: The model processes the request and returns its response to the proxy.
6.  **Proxy Translation (Gemini to Anthropic)**: The proxy server:
    *   Receives the Gemini response from LiteLLM (this can be a stream of events or a complete JSON object).
    *   Handles streaming errors and malformed chunks with intelligent recovery.
    *   Converts Gemini's output (text, tool calls, stop reasons) back into the Anthropic Messages API format that Claude Code expects.
7.  **Response to Claude Code**: The proxy sends the Anthropic-formatted response back to your Claude Code client, which then displays the result or performs the requested action.

## Model Mapping for Claude Code

To ensure Claude Code's model requests are handled correctly by Gemini:

- **OAuth (Antigravity)**: When `USE_ANTIGRAVITY=true`, model aliases map to:
  - `ANTIGRAVITY_HAIKU_MODEL` (default: `antigravity-gemini-3-flash`)
  - `ANTIGRAVITY_SONNET_MODEL` (default: `antigravity-claude-sonnet-4-5-thinking`)
  - `ANTIGRAVITY_OPUS_MODEL` (default: `antigravity-claude-opus-4-5-thinking`)

- Requests from Claude Code for model names containing **"haiku"** (e.g., `claude-3-haiku-20240307`) are mapped to the Gemini model specified by your `SMALL_MODEL` environment variable (default: `gemini-1.5-flash-latest`).
- Requests from Claude Code for model names containing **"sonnet"** or **"opus"** (e.g., `claude-3-sonnet-20240229`, `claude-3-opus-20240229`) are mapped to the Gemini model specified by your `BIG_MODEL` environment variable (default: `gemini-1.5-pro-latest`).
- If Claude Code requests a full Gemini model name (e.g., `gemini/gemini-1.5-pro-latest`), the proxy will use that directly.

The server maintains a list of known Gemini models. If a recognized Gemini model is requested by the client without the `gemini/` prefix, the proxy will add it.

## Endpoints

- `POST /v1/messages`: The primary endpoint for Claude Code to send messages to Gemini. It's fully compatible with the Anthropic Messages API specification that Claude Code uses.
- `POST /v1/messages/count_tokens`: Allows Claude Code to estimate the token count for a set of messages, using Gemini's tokenization.
- `GET /health`: Returns the health status of the proxy, including API key configuration, streaming settings, and basic API key validation.
- `GET /test-connection`: Performs a quick API call to Gemini to verify connectivity and that your `GEMINI_API_KEY` is working.
- `GET /`: Root endpoint providing a welcome message, current configuration summary (models, limits), and available endpoints.

## Error Handling & Troubleshooting

### Common Issues and Solutions

**Streaming Errors (malformed chunks):**
- The proxy automatically handles malformed JSON chunks from Gemini
- If streaming becomes unstable, set `FORCE_DISABLE_STREAMING=true` as a temporary fix
- Increase `MAX_STREAMING_RETRIES` for more resilient streaming

**Gemini 500 Internal Server Errors:**
- The proxy automatically retries with exponential backoff
- These are temporary Gemini API issues that resolve automatically
- Check `/health` endpoint to monitor API status

**Connection Timeouts:**
- Increase `REQUEST_TIMEOUT` if experiencing frequent timeouts
- Check your internet connection and firewall settings
- Use `/test-connection` endpoint to verify API connectivity

**Rate Limiting:**
- Monitor your Google AI Studio quota in the Google Cloud Console
- The proxy will provide specific rate limit guidance in error messages

### Emergency Mode

If you experience persistent issues:
```bash
# Disable streaming temporarily
export EMERGENCY_DISABLE_STREAMING=true

# Or force disable all streaming
export FORCE_DISABLE_STREAMING=true
```

## Logging

The server provides detailed logs, which are especially useful for understanding how Claude Code requests are translated for Gemini and for monitoring error recovery. Logs are colorized in TTY environments for easier reading. Adjust verbosity with the `LOG_LEVEL` environment variable:

- `DEBUG`: Detailed request/response logging and error recovery steps
- `INFO`: General operation logging
- `WARNING`: Error recovery and fallback notifications (recommended)
- `ERROR`: Only errors and failures
- `CRITICAL`: Only critical failures

## The `CLAUDE.MD` File: Guiding Gemini for Claude Code

The `CLAUDE.MD` file included in this repository is critical for achieving the best experience when using this proxy with Claude Code and Gemini.

**Purpose:**

- **Tailors Gemini to Claude Code's Needs**: Claude Code has specific ways it expects an LLM to behave, especially regarding tool use, file operations, and output formatting. `CLAUDE.MD` provides Gemini with explicit instructions on these expectations.
- **Improves Tool Reliability**: By outlining how tools should be called and results interpreted, it helps Gemini make more effective use of Claude Code's capabilities.
- **Enhances Code Generation & Understanding**: Gives Gemini context about the development environment and coding standards, leading to better code suggestions within Claude Code.
- **Reduces Misinterpretations**: Helps bridge any gaps between how Anthropic models might interpret Claude Code directives versus how Gemini might.

**How Claude Code Uses It:**

When you run `claude` in a project directory, the Claude Code CLI automatically looks for a `CLAUDE.MD` file in that directory. If found, its contents are prepended to the system prompt for every request sent to the LLM (in this case, your Gemini proxy).

**Recommendation:** Always copy the `CLAUDE.MD` from this proxy's repository into the root of any project where you intend to use Claude Code with this Gemini proxy. This ensures Gemini receives these vital instructions for every session.

## Performance Tips

- **Model Selection**: Use `gemini-1.5-flash-latest` for faster responses, `gemini-1.5-pro-latest` for more complex tasks
- **Streaming**: Keep streaming enabled for better interactivity; the proxy handles errors automatically
- **Timeouts**: Increase `REQUEST_TIMEOUT` for complex requests that need more processing time
- **Retries**: Adjust `MAX_STREAMING_RETRIES` based on your network stability

## Contributing

Contributions, issues, and feature requests are welcome! Please submit them on the GitHub repository.

Areas where contributions are especially valuable:
- Additional Gemini model support
- Performance optimizations
- Enhanced error recovery strategies
- Documentation improvements

## Additional Documentation

- **[ANTIGRAVITY.md](ANTIGRAVITY.md)** - Detailed guide to Antigravity OAuth setup and configuration
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Architecture overview and file structure
- **[CLAUDE.md](CLAUDE.md)** - Best practices for Claude Code with Gemini

## Thanks

This project was heavily inspired by and builds upon the foundational work of the [claude-code-proxy by @1rgs](https://github.com/1rgs/claude-code-proxy). Their original proxy was instrumental in demonstrating the viability of such a bridge.

Special thanks to the community for testing and feedback on error handling improvements.

---

## gclaude CLI

### Installation

After installing the package dependencies:

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

**Status Dashboard:** Beautiful terminal UI showing proxy status, auth state, and model routes.

### Configuration Files

| File | Location |
|------|----------|
| Config | `~/.gclaude/config.json` |
| OAuth Tokens | `~/.config/gclaude/antigravity-accounts.json` |
| Logs | `~/.gclaude/logs/proxy.log` |

### Model Routes

#### Antigravity Models (Google OAuth, Higher Quota)

When authenticated with Antigravity, gclaude routes requests to higher-quota endpoints:

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

#### Gemini Fallback Models (API Key, Standard Quota)

When not authenticated with Antigravity, or when Antigravity models are unavailable, the proxy falls back to standard Gemini models via API key:

| Model ID | Name | Description |
|----------|------|-------------|
| `gemini-2.0-flash-exp` | Gemini 2.0 Flash Exp | Experimental - Very Fast |
| `gemini-2.5-flash-preview-04-17` | Gemini 2.5 Flash Preview | Latest Flash Model |
| `gemini-2.5-pro-preview` | Gemini 2.5 Pro Preview | Latest Pro Model |
| `gemini-1.5-flash-latest` | Gemini 1.5 Flash | Stable Fast Model |
| `gemini-1.5-pro-latest` | Gemini 1.5 Pro | Stable Capable Model |

### Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  Claude Code    │────▶│  gclaude Proxy   │────▶│  Antigravity API        │
│  (claude cli)   │     │  (localhost:8082)│     │  (Google OAuth)         │
└─────────────────┘     └──────────────────┘     └─────────────────────────┘
                                │                            │
                                │                            ▼
                                │                   ┌─────────────────┐
                                │                   │ Gemini 3 Flash  │
                                │                   │ Gemini 3 Pro    │
                                │                   │ Claude Sonnet   │
                                │                   │ Claude Opus     │
                                │                   └─────────────────┘
                                │
                                ▼ (fallback)
                       ┌──────────────────┐     ┌─────────────────────────┐
                       │  Gemini API      │────▶│  Gemini 1.5/2.0 Models  │
                       │  (API Key)       │     └─────────────────────────┘
                       └──────────────────┘
```

**Request Flow:**
1. Claude Code sends Anthropic-format request to `http://localhost:8082`
2. Proxy translates to Antigravity/Gemini format
3. If authenticated with OAuth: routes to Antigravity API (higher quota)
4. If OAuth fails or quota exhausted: falls back to Gemini API key
5. Response translated back to Anthropic format for Claude Code
