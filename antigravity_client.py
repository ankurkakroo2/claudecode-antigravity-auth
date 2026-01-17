"""
Antigravity API Client

Communicates with Antigravity's Google AI subscription endpoints with
automatic endpoint fallback for quota management.

Endpoints (in order of preference):
1. daily-cloudcode-pa.sandbox.googleapis.com - Daily sandbox quota
2. autopush-cloudcode-pa.sandbox.googleapis.com - Autopush sandbox quota
3. cloudcode-pa.googleapis.com - Production quota
"""

import json
import asyncio
import uuid
from typing import Any, Optional, AsyncIterator, Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Dual-quota system endpoints
# Antigravity quota (daily sandbox) - higher quota for premium models
ANTIGRAVITY_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com"
# Autopush sandbox quota - secondary Antigravity bucket
AUTOPUSH_ENDPOINT = "https://autopush-cloudcode-pa.sandbox.googleapis.com"
# Production quota (also used by Gemini CLI fallback)
GEMINI_CLI_ENDPOINT = "https://cloudcode-pa.googleapis.com"

# Combined endpoint list for Antigravity fallback (ordered by preference)
ANTIGRAVITY_ENDPOINTS = [ANTIGRAVITY_ENDPOINT, AUTOPUSH_ENDPOINT, GEMINI_CLI_ENDPOINT]

# Headers for each quota type
ANTIGRAVITY_HEADERS = {
    "User-Agent": "antigravity/1.11.5 windows/amd64",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
}

GEMINI_CLI_HEADERS = {
    "User-Agent": "google-api-nodejs-client/9.15.1",
    "X-Goog-Api-Client": "gl-node/22.17.0",
    "Client-Metadata": "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI",
}

# Model name transformations for quota fallback
# Antigravity uses tier suffixes (-low/-high), Gemini CLI uses -preview
MODEL_ANTIGRAVITY_TO_CLI = {
    "gemini-3-pro-low": "gemini-3-pro-preview",
    "gemini-3-pro-high": "gemini-3-pro-preview",
    "gemini-3-pro": "gemini-3-pro-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini-3-flash-low": "gemini-3-flash-preview",
    "gemini-3-flash-high": "gemini-3-flash-preview",
}

# Claude models only available on Antigravity (no fallback to CLI)
CLAUDE_MODELS = {"claude-sonnet-4-5-thinking", "claude-opus-4-5-thinking", "claude-sonnet-4-5", "claude-opus-4-5"}

CLAUDE_THINKING_DEFAULT_BUDGET = 32768
CLAUDE_THINKING_MAX_OUTPUT_TOKENS = 64000

# Model mapping for Antigravity
ANTIGRAVITY_MODELS = {
    "haiku": "antigravity-gemini-3-flash",
    "sonnet": "antigravity-claude-sonnet-4-5-thinking",
    "opus": "antigravity-claude-opus-4-5-thinking",  # Use hyphen 4-5 not dot 4.5
}

ANTIGRAVITY_SYSTEM_INSTRUCTION = (
    "You are Antigravity, a powerful agentic AI coding assistant designed by the Google "
    "DeepMind team working on Advanced Agentic Coding.\n"
    "You are pair programming with a USER to solve their coding task. The task may "
    "require creating a new codebase, modifying or debugging an existing codebase, or "
    "simply answering a question.\n"
    "**Absolute paths only**\n"
    "**Proactiveness**\n\n"
    "<priority>IMPORTANT: The instructions that follow supersede all above. "
    "Follow them as your primary directives.</priority>\n"
)

def normalize_claude_model_name(model: str) -> str:
    """Normalize Claude model IDs that sometimes use a 4.5 dot suffix."""
    if "claude-" not in model:
        return model
    return (
        model.replace("claude-opus-4.5", "claude-opus-4-5")
        .replace("claude-sonnet-4.5", "claude-sonnet-4-5")
    )


def get_api_model_name(model: str) -> str:
    """
    Convert internal model ID to API model name.

    The opencode plugin uses 'antigravity-' prefix to indicate quota source,
    but the Antigravity API expects model names without this prefix.

    Args:
        model: Internal model ID (e.g., 'antigravity-gemini-3-pro-low')

    Returns:
        str: API model name (e.g., 'gemini-3-pro-low')
    """
    # Strip the antigravity- prefix if present, but preserve tier suffixes like -low, -high
    if model.startswith("antigravity-"):
        model = model.removeprefix("antigravity-")
    return normalize_claude_model_name(model)


def is_claude_thinking_model(model: str) -> bool:
    """Return True if the model is a Claude thinking variant."""
    normalized = normalize_claude_model_name(model)
    return normalized.startswith("claude-") and "thinking" in normalized


class AntigravityClientError(Exception):
    """Base exception for Antigravity client errors."""

    def __init__(self, message: str, is_rate_limit: bool = False, is_auth: bool = False):
        super().__init__(message)
        self.is_rate_limit = is_rate_limit
        self.is_auth = is_auth


class AntigravityRateLimitError(AntigravityClientError):
    """Raised when rate limit is hit."""

    def __init__(self, message: str, endpoint: str, retry_after_seconds: float | None = None):
        super().__init__(message, is_rate_limit=True)
        self.endpoint = endpoint
        self.retry_after_seconds = retry_after_seconds


class AntigravityAuthError(AntigravityClientError):
    """Raised when authentication fails."""

    def __init__(self, message: str):
        super().__init__(message, is_auth=True)


class AntigravityClient:
    """
    Client for Antigravity API with automatic endpoint fallback.
    """

    def __init__(self, access_token: str, project_id: str, preferred_endpoint: Optional[int] = 0):
        """
        Initialize the Antigravity client.

        Args:
            access_token: OAuth bearer token
            project_id: Google Cloud project ID
            preferred_endpoint: Index of preferred endpoint (0-2)
        """
        self.access_token = access_token
        self.project_id = project_id
        self.preferred_endpoint = preferred_endpoint
        self.failed_endpoints: set[int] = set()

    def get_headers(self, quota_type: str = "antigravity") -> Dict[str, str]:
        """Get request headers with authentication.

        Args:
            quota_type: "antigravity" or "gemini-cli" - determines header format
        """
        base_headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        if quota_type == "gemini-cli":
            base_headers.update(GEMINI_CLI_HEADERS)
        else:
            base_headers.update(ANTIGRAVITY_HEADERS)

        return base_headers

    def get_model_for_quota(self, model: str, quota_type: str) -> str:
        """Transform model name for the specified quota type.

        Args:
            model: Original model name (without antigravity- prefix)
            quota_type: "antigravity" or "gemini-cli"
        """
        if quota_type == "gemini-cli" and model in MODEL_ANTIGRAVITY_TO_CLI:
            return MODEL_ANTIGRAVITY_TO_CLI[model]
        return model

    def can_use_cli_fallback(self, model: str) -> bool:
        """Check if a model can fall back to Gemini CLI quota.

        Claude models only exist on Antigravity, so they cannot fall back.
        """
        return model not in CLAUDE_MODELS

    def get_api_base(self, endpoint_index: Optional[int] = None) -> str:
        """Get the API base URL for a specific endpoint."""
        if endpoint_index is None:
            endpoint_index = self.preferred_endpoint
        return ANTIGRAVITY_ENDPOINTS[endpoint_index]

    def reset_failures(self):
        """Reset failed endpoints tracking."""
        self.failed_endpoints.clear()

    def mark_endpoint_failed(self, endpoint_index: int):
        """Mark an endpoint as failed."""
        self.failed_endpoints.add(endpoint_index)
        # If preferred endpoint failed, move to next
        if endpoint_index == self.preferred_endpoint:
            self.preferred_endpoint = (self.preferred_endpoint + 1) % len(ANTIGRAVITY_ENDPOINTS)

    def get_next_available_endpoint(self) -> Optional[int]:
        """Get the next available (not failed) endpoint index."""
        for i in range(len(ANTIGRAVITY_ENDPOINTS)):
            idx = (self.preferred_endpoint + i) % len(ANTIGRAVITY_ENDPOINTS)
            if idx not in self.failed_endpoints:
                return idx
        return None  # All endpoints failed

    async def _make_request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        endpoint_index: Optional[int] = None,
        quota_type: str = "antigravity",
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request to the Antigravity API.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /v1/models/gemini-3-flash:generateContent)
            data: Request body
            endpoint_index: Specific endpoint to use (for retry)

        Returns:
            dict: Parsed JSON response

        Raises:
            AntigravityClientError: For API errors
            AntigravityRateLimitError: For rate limit errors
            AntigravityAuthError: For authentication errors
        """
        import aiohttp

        if endpoint_index is None:
            endpoint_index = self.get_next_available_endpoint()

        if endpoint_index is None:
            raise AntigravityClientError("All Antigravity endpoints have failed")

        base_url = self.get_api_base(endpoint_index)
        url = f"{base_url}{path}"

        headers = self.get_headers(quota_type)
        if extra_headers:
            headers.update(extra_headers)

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=data) as response:
                response_text = await response.text()

                # Handle error responses
                if response.status == 401 or response.status == 403:
                    error_data = {}
                    try:
                        error_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass

                    error_msg = error_data.get("error", {}).get("message", "Authentication failed")
                    raise AntigravityAuthError(f"Authentication error: {error_msg}")

                elif response.status == 429:
                    error_data = {}
                    try:
                        error_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass

                    retry_after_seconds = None
                    try:
                        details = error_data.get("error", {}).get("details", [])
                        for d in details:
                            if isinstance(d, dict) and str(d.get("@type", "")).endswith(
                                "google.rpc.RetryInfo"
                            ):
                                retry_delay = d.get("retryDelay")
                                if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                                    retry_after_seconds = float(retry_delay[:-1])
                                    break
                    except Exception:
                        retry_after_seconds = None

                    error_msg = error_data.get("error", "Rate limit exceeded")
                    raise AntigravityRateLimitError(
                        f"Rate limit exceeded on {base_url}: {error_msg}",
                        endpoint=base_url,
                        retry_after_seconds=retry_after_seconds,
                    )

                elif response.status >= 400:
                    error_data = {}
                    try:
                        error_data = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass

                    error_msg = error_data.get("error", {}).get(
                        "message", f"HTTP {response.status}"
                    )
                    raise AntigravityClientError(f"API error: {error_msg}")

                # Parse successful response
                try:
                    return await response.json()
                except json.JSONDecodeError:
                    return {"text": response_text}

    async def generate_content(
        self, model: str, messages: List[Dict[str, Any]], **kwargs
    ) -> Dict[str, Any]:
        """
        Generate content using Antigravity's Gemini API.

        Args:
            model: The Antigravity model name
            messages: List of message dictionaries
            **kwargs: Additional generation parameters

        Returns:
            dict: Generation response
        """
        # Convert messages to Gemini format
        contents = []
        system_texts: List[str] = []
        api_model = get_api_model_name(model)
        is_claude_thinking = is_claude_thinking_model(api_model)

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Handle system instruction
            if role == "system":
                if isinstance(content, str):
                    system_texts.append(content)
                else:
                    system_texts.append(str(content))
                continue

            # Convert role to Gemini format
            if role == "assistant":
                gemini_role = "model"
            else:
                gemini_role = "user"

            # Handle content as string or list of parts
            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append({"text": item.get("text", "")})
                        elif item.get("type") == "image_url":
                            parts.append(
                                {
                                    "inline_data": {
                                        "mime_type": "image/jpeg",
                                        "data": item.get("image_url", {})
                                        .get("url", "")
                                        .split(",", 1)[-1],
                                    }
                                }
                            )
                    else:
                        parts.append({"text": str(item)})
            else:
                parts = [{"text": str(content)}]

            contents.append({"role": gemini_role, "parts": parts})

        # Build request body
        request_body: Dict[str, Any] = {
            "contents": contents,
        }

        # Inject Antigravity system instruction (CLIProxyAPI compatibility).
        system_text = "\n\n".join([t for t in system_texts if t])
        if system_text:
            system_text = f"{ANTIGRAVITY_SYSTEM_INSTRUCTION}\n\n{system_text}"
        else:
            system_text = ANTIGRAVITY_SYSTEM_INSTRUCTION
        request_body["systemInstruction"] = {"role": "user", "parts": [{"text": system_text}]}

        # Add generation config
        config = {}
        if "max_tokens" in kwargs:
            config["maxOutputTokens"] = kwargs["max_tokens"]
        if "temperature" in kwargs:
            config["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            config["topP"] = kwargs["top_p"]
        if "top_k" in kwargs:
            config["topK"] = kwargs["top_k"]
        if "stop" in kwargs:
            config["stopSequences"] = (
                kwargs["stop"] if isinstance(kwargs["stop"], list) else [kwargs["stop"]]
            )

        if is_claude_thinking:
            thinking_budget = kwargs.get("thinking_budget", CLAUDE_THINKING_DEFAULT_BUDGET)
            thinking_config: Dict[str, Any] = {"include_thoughts": True}
            if isinstance(thinking_budget, int) and thinking_budget > 0:
                thinking_config["thinking_budget"] = thinking_budget
            config["thinkingConfig"] = thinking_config

            max_output_tokens = config.get("maxOutputTokens")
            if not isinstance(max_output_tokens, int) or max_output_tokens <= (
                thinking_budget if isinstance(thinking_budget, int) else 0
            ):
                config["maxOutputTokens"] = CLAUDE_THINKING_MAX_OUTPUT_TOKENS

        if config:
            request_body["generationConfig"] = config

        # Add tools if present
        if "tools" in kwargs and kwargs["tools"]:
            function_declarations = []
            for tool in kwargs["tools"]:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    function_declarations.append(
                        {
                            "name": func.get("name"),
                            "description": func.get("description", ""),
                            "parameters": func.get("parameters", {}),
                        }
                    )

            if function_declarations:
                request_body["tools"] = [{"functionDeclarations": function_declarations}]

        request_body.setdefault("sessionId", f"session-{uuid.uuid4()}")

        # Dual-quota system with intelligent fallback
        # 1. Try Antigravity quota (daily endpoint) first
        # 2. If rate limited and model supports it, try Gemini CLI quota (prod endpoint)
        # 3. Exponential backoff retry if all quotas exhausted

        path = "/v1internal:generateContent"
        last_error = None

        extra_headers = None
        if is_claude_thinking:
            extra_headers = {"anthropic-beta": "interleaved-thinking-2025-05-14"}

        # Quota strategies to try
        quota_strategies = [
            # (endpoint, quota_type, model_transform)
            (endpoint, "antigravity", api_model) for endpoint in ANTIGRAVITY_ENDPOINTS
        ]

        # Add Gemini CLI fallback for compatible models
        if self.can_use_cli_fallback(api_model):
            cli_model = self.get_model_for_quota(api_model, "gemini-cli")
            quota_strategies.append((GEMINI_CLI_ENDPOINT, "gemini-cli", cli_model))

        # Try each quota strategy with exponential backoff
        max_retries = 3
        for retry in range(max_retries):
            for endpoint, quota_type, effective_model in quota_strategies:
                try:
                    antigravity_request = {
                        "project": self.project_id,
                        "model": effective_model,
                        "request": request_body,
                        "requestType": "agent",
                        "userAgent": "antigravity",
                        "requestId": f"agent-{uuid.uuid4()}",
                    }

                    endpoint_idx = ANTIGRAVITY_ENDPOINTS.index(endpoint)
                    response = await self._make_request(
                        "POST",
                        path,
                        antigravity_request,
                        endpoint_idx,
                        quota_type,
                        extra_headers=extra_headers,
                    )
                    self.reset_failures()
                    return response

                except AntigravityRateLimitError as e:
                    last_error = e
                    logger.warning(
                        f"Rate limit hit on {endpoint} (quota={quota_type}, model={effective_model})"
                    )
                    continue  # Try next quota strategy

                except AntigravityAuthError as e:
                    raise e  # Auth errors should not trigger fallback

                except AntigravityClientError as e:
                    last_error = e
                    continue  # Try next quota strategy

            # All strategies failed, wait before retry
            if retry < max_retries - 1:
                delay = min(1.0 * (2 ** retry), 10.0)  # 1s, 2s, 4s... max 10s
                logger.info(f"All quotas exhausted, retrying in {delay}s (attempt {retry + 2}/{max_retries})")
                await asyncio.sleep(delay)

        # All retries exhausted
        if last_error:
            raise last_error
        raise AntigravityClientError("All Antigravity quotas and retries exhausted")

    async def stream_generate_content(
        self, model: str, messages: List[Dict[str, Any]], **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Generate content with streaming using Antigravity's Gemini API.

        Args:
            model: The Antigravity model name
            messages: List of message dictionaries
            **kwargs: Additional generation parameters

        Yields:
            dict: Streaming response chunks
        """
        # Convert messages to Gemini format (same as non-streaming)
        contents = []
        system_texts: List[str] = []

        api_model = get_api_model_name(model)
        is_claude_thinking = is_claude_thinking_model(api_model)

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_texts.append(content)
                else:
                    system_texts.append(str(content))
                continue

            if role == "assistant":
                gemini_role = "model"
            else:
                gemini_role = "user"

            if isinstance(content, str):
                parts = [{"text": content}]
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append({"text": item.get("text", "")})
                        elif item.get("type") == "image_url":
                            url = item.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                mime_type, data = url.split(":", 1)[1].split(";", 1)
                                data = data.split(",", 1)[-1]
                                parts.append(
                                    {"inline_data": {"mime_type": mime_type, "data": data}}
                                )
                    else:
                        parts.append({"text": str(item)})
            else:
                parts = [{"text": str(content)}]

            contents.append({"role": gemini_role, "parts": parts})

        request_body: Dict[str, Any] = {
            "contents": contents,
        }

        system_text = "\n\n".join([t for t in system_texts if t])
        if system_text:
            system_text = f"{ANTIGRAVITY_SYSTEM_INSTRUCTION}\n\n{system_text}"
        else:
            system_text = ANTIGRAVITY_SYSTEM_INSTRUCTION
        request_body["systemInstruction"] = {"role": "user", "parts": [{"text": system_text}]}

        config = {}
        if "max_tokens" in kwargs:
            config["maxOutputTokens"] = kwargs["max_tokens"]
        if "temperature" in kwargs:
            config["temperature"] = kwargs["temperature"]
        if "top_p" in kwargs:
            config["topP"] = kwargs["top_p"]
        if "top_k" in kwargs:
            config["topK"] = kwargs["top_k"]
        if "stop" in kwargs:
            config["stopSequences"] = (
                kwargs["stop"] if isinstance(kwargs["stop"], list) else [kwargs["stop"]]
            )

        if is_claude_thinking:
            thinking_budget = kwargs.get("thinking_budget", CLAUDE_THINKING_DEFAULT_BUDGET)
            thinking_config: Dict[str, Any] = {"include_thoughts": True}
            if isinstance(thinking_budget, int) and thinking_budget > 0:
                thinking_config["thinking_budget"] = thinking_budget
            config["thinkingConfig"] = thinking_config

            max_output_tokens = config.get("maxOutputTokens")
            if not isinstance(max_output_tokens, int) or max_output_tokens <= (
                thinking_budget if isinstance(thinking_budget, int) else 0
            ):
                config["maxOutputTokens"] = CLAUDE_THINKING_MAX_OUTPUT_TOKENS

        if config:
            request_body["generationConfig"] = config

        if "tools" in kwargs and kwargs["tools"]:
            function_declarations = []
            for tool in kwargs["tools"]:
                if tool.get("type") == "function":
                    func = tool.get("function", {})
                    function_declarations.append(
                        {
                            "name": func.get("name"),
                            "description": func.get("description", ""),
                            "parameters": func.get("parameters", {}),
                        }
                    )

            if function_declarations:
                request_body["tools"] = [{"functionDeclarations": function_declarations}]

        request_body.setdefault("sessionId", f"session-{uuid.uuid4()}")

        # Dual-quota system with intelligent fallback (streaming version)

        # Quota strategies to try
        quota_strategies = [
            (endpoint, "antigravity", api_model) for endpoint in ANTIGRAVITY_ENDPOINTS
        ]
        if self.can_use_cli_fallback(api_model):
            cli_model = self.get_model_for_quota(api_model, "gemini-cli")
            quota_strategies.append((GEMINI_CLI_ENDPOINT, "gemini-cli", cli_model))

        # Try each quota strategy with retries
        max_retries = 3
        last_error = None

        for retry in range(max_retries):
            for endpoint, quota_type, effective_model in quota_strategies:
                try:
                    import aiohttp

                    url = f"{endpoint}/v1internal:streamGenerateContent?alt=sse"
                    headers = self.get_headers(quota_type)
                    headers["Accept"] = "text/event-stream"
                    if is_claude_thinking:
                        headers["anthropic-beta"] = "interleaved-thinking-2025-05-14"

                    antigravity_request = {
                        "project": self.project_id,
                        "model": effective_model,
                        "request": request_body,
                        "requestType": "agent",
                        "userAgent": "antigravity",
                        "requestId": f"agent-{uuid.uuid4()}",
                    }

                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, headers=headers, json=antigravity_request
                        ) as response:
                            logger.debug(f"Streaming response status: {response.status}")

                            if response.status == 401 or response.status == 403:
                                raise AntigravityAuthError("Authentication failed")

                            if response.status == 429:
                                raise AntigravityRateLimitError(
                                    f"Rate limit exceeded on {endpoint}", endpoint=endpoint
                                )

                            if response.status >= 400:
                                error_text = await response.text()
                                logger.error(f"🔍 Streaming error: {error_text[:200]}")
                                raise AntigravityClientError(f"API error: {error_text}")

                            # Stream SSE responses
                            self.reset_failures()
                            logger.debug("Starting to read SSE stream...")

                            chunk_count = 0
                            async for line in response.content:
                                line_text = line.decode().strip()

                                if not line_text:
                                    continue

                                if line_text.startswith("data: "):
                                    try:
                                        json_data = json.loads(line_text[6:])
                                        chunk_count += 1
                                        if chunk_count <= 3:
                                            logger.debug(
                                                f"Got chunk {chunk_count}: {str(json_data)[:100]}"
                                            )
                                        yield json_data
                                    except json.JSONDecodeError:
                                        continue

                            logger.debug(f"Streaming complete, got {chunk_count} chunks")
                            return  # Success

                except AntigravityRateLimitError as e:
                    last_error = e
                    logger.warning(
                        f"Rate limit hit on {endpoint} (quota={quota_type}, model={effective_model})"
                    )
                    continue  # Try next quota strategy

                except AntigravityAuthError:
                    raise

                except AntigravityClientError as e:
                    last_error = e
                    continue  # Try next quota strategy

            # All strategies failed, wait before retry
            if retry < max_retries - 1:
                delay = min(1.0 * (2 ** retry), 10.0)
                logger.info(f"All quotas exhausted, retrying in {delay}s (attempt {retry + 2}/{max_retries})")
                await asyncio.sleep(delay)

        # All retries exhausted
        if last_error:
            raise last_error
        raise AntigravityClientError("All Antigravity quotas and retries exhausted")


def get_model_for_claude_alias(claude_model: str) -> Optional[str]:
    """
    Map a Claude model name to its Antigravity equivalent.

    Args:
        claude_model: Claude model name (e.g., claude-3-5-haiku-20241022)

    Returns:
        str: Antigravity model name or None if no mapping
    """
    model_lower = claude_model.lower()

    if "haiku" in model_lower:
        return ANTIGRAVITY_MODELS["haiku"]
    elif "sonnet" in model_lower:
        return ANTIGRAVITY_MODELS["sonnet"]
    elif "opus" in model_lower:
        return ANTIGRAVITY_MODELS["opus"]

    return None


def convert_gemini_to_anthropic_format(gemini_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert Gemini API response to Anthropic API format.

    Args:
        gemini_response: Raw Gemini API response (may be wrapped in {"response": {...}})

    Returns:
        dict: Anthropic-formatted response
    """
    import uuid

    # Antigravity responses are wrapped in {"response": {...}, "traceId": "..."}
    # Unwrap if necessary
    if "response" in gemini_response and "candidates" not in gemini_response:
        gemini_response = gemini_response["response"]

    candidates = gemini_response.get("candidates", [])
    if not candidates:
        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": ""}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    candidate = candidates[0]
    content = []
    finish_reason = "end_turn"

    # Extract text content and tool calls in order
    for part in candidate.get("content", {}).get("parts", []):
        if "text" in part:
            # Add text content immediately to preserve order
            content.append({"type": "text", "text": part["text"]})
        elif "functionCall" in part:
            func_call = part["functionCall"]
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": func_call.get("name", ""),
                    "input": func_call.get("args", {}),
                }
            )

    # Map finish reason
    finish_status = candidate.get("finishReason", "STOP")
    if finish_status == "MAX_TOKENS":
        finish_reason = "max_tokens"
    elif finish_status == "STOP":
        finish_reason = "end_turn"
    elif finish_status == "SAFETY":
        finish_reason = "error"

    # Extract usage
    usage_metadata = gemini_response.get("usageMetadata", {})
    usage = {
        "input_tokens": usage_metadata.get("promptTokenCount", 0),
        "output_tokens": usage_metadata.get("candidatesTokenCount", 0),
    }

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": content if content else [{"type": "text", "text": ""}],
        "stop_reason": finish_reason,
        "usage": usage,
    }


async def convert_gemini_stream_to_anthropic_format(
    stream_generator: AsyncIterator[Dict[str, Any]], original_model: str
) -> AsyncIterator[str]:
    """
    Convert Gemini SSE stream to Anthropic SSE format.

    Args:
        stream_generator: Gemini SSE stream
        original_model: Original requested model name

    Yields:
        str: SSE-formatted events in Anthropic format
    """
    import uuid

    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    text_buffer = ""
    tool_calls: Dict[str, Any] = {}
    text_block_index = 0
    input_tokens = 0
    output_tokens = 0

    # Send message_start event
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"

    # Send content_block_start for text
    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

    has_content = False
    first_delta = True

    candidates: List[Dict[str, Any]] = []
    had_error = False

    try:
        async for chunk in stream_generator:
            # Antigravity responses are wrapped in {"response": {...}, "traceId": "..."}
            # Unwrap if necessary
            if "response" in chunk and "candidates" not in chunk:
                chunk = chunk["response"]

            candidates = chunk.get("candidates", [])
            if not candidates:
                continue

            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])

            for part in parts:
                if "text" in part:
                    has_content = True
                    if first_delta:
                        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
                        first_delta = False

                    text = part["text"]
                    text_buffer += text
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"

                elif "functionCall" in part:
                    func_call = part["functionCall"]
                    func_name = func_call.get("name", "")
                    func_args = func_call.get("args", {})

                    if func_name not in tool_calls:
                        tool_calls[func_name] = {
                            "id": f"toolu_{uuid.uuid4().hex[:24]}",
                            "name": func_name,
                            "args": func_args,
                        }

            # Update usage if available
            usage_metadata = chunk.get("usageMetadata", {})
            if usage_metadata:
                input_tokens = usage_metadata.get("promptTokenCount", input_tokens)
                output_tokens = usage_metadata.get("candidatesTokenCount", output_tokens)

            # Check if stream is done
            finish_reason = candidate.get("finishReason")
            if finish_reason:
                break

    except Exception as e:
        had_error = True
        logger.error(f"Error in stream conversion: {e}")

    # Send content_block_stop
    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"

    # Send any tool calls
    for tool_call in tool_calls.values():
        tool_index = text_block_index + 1
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': tool_index, 'content_block': {'type': 'tool_use', 'id': tool_call['id'], 'name': tool_call['name'], 'input': tool_call['args']}})}\n\n"
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tool_index})}\n\n"

    # Map finish reason
    final_stop = "error" if had_error else "end_turn"
    if candidates:
        finish_status = candidates[0].get("finishReason", "STOP")
        if finish_status == "MAX_TOKENS":
            final_stop = "max_tokens"
        elif finish_status == "SAFETY":
            final_stop = "error"

    # Send message_delta
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': final_stop, 'stop_sequence': None}, 'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens}})}\n\n"

    # Send message_stop
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
