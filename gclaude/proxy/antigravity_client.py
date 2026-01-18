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
import os
import re
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
# Production quota endpoint
GEMINI_CLI_ENDPOINT = "https://cloudcode-pa.googleapis.com"

# Combined endpoint list for Antigravity fallback (ordered by preference)
# Prefer sandbox OAuth endpoints; only attempt production if available.
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
# Antigravity uses tier suffixes (-low/-high); production uses -preview
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
ANTIGRAVITY_INCLUDE_THOUGHTS = os.getenv("ANTIGRAVITY_INCLUDE_THOUGHTS", "false").lower() == "true"

# Cache tool call context so tool results can be described to the provider.
TOOL_THOUGHT_SIGNATURES: Dict[str, str] = {}
TOOL_CALL_CONTEXT: Dict[str, Dict[str, Any]] = {}
LAST_THOUGHT_SIGNATURE: Optional[str] = None
LAST_USER_TEXT: str = ""
LAST_USER_URLS: List[str] = []
LAST_USER_PATHS: List[str] = []


def _extract_urls(text: str) -> List[str]:
    if not isinstance(text, str) or not text:
        return []
    urls: List[str] = []
    for match in re.findall(r"https?://[^\s)\"']+", text):
        cleaned = match.rstrip(".,;:!?)")
        if cleaned:
            urls.append(cleaned)

    domain_matches = re.findall(r"\b([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(/[^\s\"')]+)?", text)
    for domain, path in domain_matches:
        if domain.startswith("http"):
            continue
        candidate = f"https://{domain}{path or ''}"
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _extract_paths(text: str) -> List[str]:
    if not isinstance(text, str) or not text:
        return []
    candidates: List[str] = []
    # Absolute or home-relative paths.
    for match in re.findall(r"(?:~/?|/)[A-Za-z0-9._/-]+", text):
        if match.startswith("http"):
            continue
        candidates.append(match)
    # Relative file paths with extensions.
    for match in re.findall(r"\\b[\\w./-]+\\.[A-Za-z0-9]{1,6}\\b", text):
        if match.startswith("http"):
            continue
        candidates.append(match)
    # Preserve order while de-duping.
    seen = set()
    ordered: List[str] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p).strip()
    if isinstance(content, dict) and content.get("type") == "text":
        return str(content.get("text", ""))
    return ""


def _update_last_user_context(messages: List[Dict[str, Any]]) -> None:
    global LAST_USER_TEXT, LAST_USER_URLS, LAST_USER_PATHS
    last_text = ""
    for msg in messages:
        if msg.get("role") == "user":
            text = _extract_text_from_content(msg.get("content"))
            if text:
                last_text = text
    LAST_USER_TEXT = last_text
    LAST_USER_URLS = _extract_urls(last_text)
    LAST_USER_PATHS = _extract_paths(last_text)


def _is_license_error(error_msg: str) -> bool:
    if not isinstance(error_msg, str) or not error_msg:
        return False
    msg = error_msg.lower()
    if "code assist" in msg or "codeassist" in msg:
        return True
    if "license" in msg and ("gemini" in msg or "code" in msg):
        return True
    if "not enabled" in msg and "gemini" in msg:
        return True
    return False

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
        """Check if a model can fall back to production quota.

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

                    error_msg = (
                        error_data.get("error", {}).get("message")
                        if isinstance(error_data, dict)
                        else None
                    )
                    if not error_msg:
                        error_msg = response_text or "Authentication failed"

                    if response.status == 403 and _is_license_error(error_msg):
                        raise AntigravityClientError(f"Endpoint license error: {error_msg}")

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
        Generate content using the Antigravity API.

        Args:
            model: The Antigravity model name
            messages: List of message dictionaries
            **kwargs: Additional generation parameters

        Returns:
            dict: Generation response
        """
        _update_last_user_context(messages)

        # Convert messages to Antigravity format
        contents = []
        system_texts: List[str] = []
        api_model = get_api_model_name(model)
        is_claude_thinking = is_claude_thinking_model(api_model)

        tool_responses = [m for m in messages if m.get("role") == "tool"]
        if tool_responses:
            logger.debug(
                "Tool responses available: %s",
                [r.get("tool_call_id") for r in tool_responses if r.get("tool_call_id")],
            )
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "tool":
                continue

            # Handle system instruction
            if role == "system":
                if isinstance(content, str):
                    system_texts.append(content)
                else:
                    system_texts.append(str(content))
                continue

            # Convert role to Antigravity format
            if role == "assistant":
                gemini_role = "model"
            else:
                gemini_role = "user"

            parts = []
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                if not isinstance(tool_calls, list):
                    tool_calls = [tool_calls]
                for tool_call in tool_calls:
                    function_data = {}
                    if isinstance(tool_call, dict):
                        function_data = tool_call.get("function", {})
                    name = function_data.get("name")
                    arguments_raw = function_data.get("arguments", "{}")
                    thought_signature = function_data.get("thought_signature") or function_data.get(
                        "thoughtSignature"
                    )
                    args_dict = {}
                    if isinstance(arguments_raw, str):
                        try:
                            args_dict = json.loads(arguments_raw)
                        except json.JSONDecodeError:
                            args_dict = {}
                    elif isinstance(arguments_raw, dict):
                        args_dict = arguments_raw
                    if name:
                        parts.append(
                            {
                                "functionCall": {
                                    "id": tool_call.get("id"),
                                    "name": name,
                                    "args": args_dict,
                                }
                            }
                        )
                        if thought_signature:
                            parts[-1]["thoughtSignature"] = thought_signature

            # Handle content as string or list of parts
            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_value = item.get("text", "")
                            if text_value:
                                parts.append({"text": text_value})
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

            contents.append({"role": gemini_role, "parts": parts})

            if gemini_role == "model" and tool_calls:
                function_responses = []
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    tool_id = tool_call.get("id")
                    function_data = tool_call.get("function", {})
                    tool_name = function_data.get("name")
                    if not tool_id or not tool_name:
                        continue
                    response = next(
                        (r for r in tool_responses if r.get("tool_call_id") == tool_id),
                        None,
                    )
                    if response is None:
                        logger.warning(
                            "No tool response found for tool_call_id=%s name=%s",
                            tool_id,
                            tool_name,
                        )
                        continue
                    result_content = response.get("content", "")
                    logger.debug(
                        "Tool response matched: id=%s name=%s type=%s",
                        tool_id,
                        tool_name,
                        type(result_content).__name__,
                    )
                    function_responses.append(
                        {
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"result": result_content},
                            }
                        }
                    )
                if function_responses:
                    contents.append({"role": "user", "parts": function_responses})

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
            thinking_config: Dict[str, Any] = {}
            if isinstance(thinking_budget, int) and thinking_budget > 0:
                thinking_config["thinkingBudget"] = thinking_budget
            if ANTIGRAVITY_INCLUDE_THOUGHTS:
                thinking_config["includeThoughts"] = True
            if thinking_config:
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

        tool_choice = kwargs.get("tool_choice")
        if isinstance(tool_choice, dict):
            choice_type = tool_choice.get("type")
            if choice_type == "auto":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "AUTO"}
                }
            elif choice_type == "any":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "ANY"}
                }
            elif choice_type == "none":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "NONE"}
                }
            elif choice_type == "tool":
                name = tool_choice.get("name")
                if isinstance(name, str) and name:
                    request_body["toolConfig"] = {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [name],
                        }
                    }

        request_body.setdefault("sessionId", f"session-{uuid.uuid4()}")

        # Dual-quota system with intelligent fallback
        # 1. Try Antigravity quota (daily endpoint) first
        # 2. If rate limited and model supports it, try production quota (prod endpoint)
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

        # OAuth-only: disable production fallback to avoid 401s in Claude Code.

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
                    continue

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
        Generate content with streaming using the Antigravity API.

        Args:
            model: The Antigravity model name
            messages: List of message dictionaries
            **kwargs: Additional generation parameters

        Yields:
            dict: Streaming response chunks
        """
        _update_last_user_context(messages)

        # Convert messages to Antigravity format (same as non-streaming)
        contents = []
        system_texts: List[str] = []

        api_model = get_api_model_name(model)
        is_claude_thinking = is_claude_thinking_model(api_model)

        tool_responses = [m for m in messages if m.get("role") == "tool"]
        if tool_responses:
            logger.debug(
                "Tool responses available: %s",
                [r.get("tool_call_id") for r in tool_responses if r.get("tool_call_id")],
            )
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "tool":
                continue

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

            parts = []
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                if not isinstance(tool_calls, list):
                    tool_calls = [tool_calls]
                for tool_call in tool_calls:
                    function_data = {}
                    if isinstance(tool_call, dict):
                        function_data = tool_call.get("function", {})
                    name = function_data.get("name")
                    arguments_raw = function_data.get("arguments", "{}")
                    thought_signature = function_data.get("thought_signature") or function_data.get(
                        "thoughtSignature"
                    )
                    args_dict = {}
                    if isinstance(arguments_raw, str):
                        try:
                            args_dict = json.loads(arguments_raw)
                        except json.JSONDecodeError:
                            args_dict = {}
                    elif isinstance(arguments_raw, dict):
                        args_dict = arguments_raw
                    if name:
                        parts.append(
                            {
                                "functionCall": {
                                    "id": tool_call.get("id"),
                                    "name": name,
                                    "args": args_dict,
                                }
                            }
                        )
                        if thought_signature:
                            parts[-1]["thoughtSignature"] = thought_signature

            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_value = item.get("text", "")
                            if text_value:
                                parts.append({"text": text_value})
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

            contents.append({"role": gemini_role, "parts": parts})

            if gemini_role == "model" and tool_calls:
                function_responses = []
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    tool_id = tool_call.get("id")
                    function_data = tool_call.get("function", {})
                    tool_name = function_data.get("name")
                    if not tool_id or not tool_name:
                        continue
                    response = next(
                        (r for r in tool_responses if r.get("tool_call_id") == tool_id),
                        None,
                    )
                    if response is None:
                        logger.warning(
                            "No tool response found for tool_call_id=%s name=%s",
                            tool_id,
                            tool_name,
                        )
                        continue
                    result_content = response.get("content", "")
                    logger.debug(
                        "Tool response matched: id=%s name=%s type=%s",
                        tool_id,
                        tool_name,
                        type(result_content).__name__,
                    )
                    function_responses.append(
                        {
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"result": result_content},
                            }
                        }
                    )
                if function_responses:
                    contents.append({"role": "user", "parts": function_responses})

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
            thinking_config: Dict[str, Any] = {}
            if isinstance(thinking_budget, int) and thinking_budget > 0:
                thinking_config["thinkingBudget"] = thinking_budget
            if ANTIGRAVITY_INCLUDE_THOUGHTS:
                thinking_config["includeThoughts"] = True
            if thinking_config:
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

        tool_choice = kwargs.get("tool_choice")
        if isinstance(tool_choice, dict):
            choice_type = tool_choice.get("type")
            if choice_type == "auto":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "AUTO"}
                }
            elif choice_type == "any":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "ANY"}
                }
            elif choice_type == "none":
                request_body["toolConfig"] = {
                    "functionCallingConfig": {"mode": "NONE"}
                }
            elif choice_type == "tool":
                name = tool_choice.get("name")
                if isinstance(name, str) and name:
                    request_body["toolConfig"] = {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [name],
                        }
                    }

        request_body.setdefault("sessionId", f"session-{uuid.uuid4()}")

        # Dual-quota system with intelligent fallback (streaming version)

        # Quota strategies to try
        quota_strategies = [
            (endpoint, "antigravity", api_model) for endpoint in ANTIGRAVITY_ENDPOINTS
        ]
        # OAuth-only: disable production fallback to avoid 401s in Claude Code.

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
                                error_text = await response.text()
                                error_data = {}
                                try:
                                    error_data = json.loads(error_text)
                                except json.JSONDecodeError:
                                    pass

                                error_msg = (
                                    error_data.get("error", {}).get("message")
                                    if isinstance(error_data, dict)
                                    else None
                                )
                                if not error_msg:
                                    error_msg = error_text or "Authentication failed"

                                if response.status == 403 and _is_license_error(error_msg):
                                    raise AntigravityClientError(
                                        f"Endpoint license error: {error_msg}"
                                    )

                                raise AntigravityAuthError(f"Authentication failed: {error_msg}")

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
                    continue

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


def _unwrap_proto_struct(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    fields = value.get("fields")
    if isinstance(fields, dict):
        return {k: _unwrap_proto_value(v) for k, v in fields.items()}
    return value


def _unwrap_proto_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "stringValue" in value:
            return value.get("stringValue")
        if "numberValue" in value:
            return value.get("numberValue")
        if "boolValue" in value:
            return value.get("boolValue")
        if "nullValue" in value:
            return None
        if "structValue" in value:
            return _unwrap_proto_struct(value.get("structValue"))
        if "listValue" in value:
            values = value.get("listValue", {}).get("values", [])
            if isinstance(values, list):
                return [_unwrap_proto_value(v) for v in values]
    return value


def parse_function_args(func_call: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize functionCall args into a dict for Anthropic tool_use."""
    args = None
    if isinstance(func_call, dict):
        if "args" in func_call:
            args = func_call.get("args")
        elif "arguments" in func_call:
            args = func_call.get("arguments")
        elif "argsJson" in func_call:
            args = func_call.get("argsJson")

    if isinstance(args, dict):
        if "fields" in args or "structValue" in args:
            return _unwrap_proto_value(args) if "structValue" in args else _unwrap_proto_struct(args)
        return args

    if isinstance(args, list):
        normalized: Dict[str, Any] = {}
        for item in args:
            if not isinstance(item, dict):
                continue
            raw_key = item.get("key") or item.get("name")
            key = _unwrap_proto_value(raw_key)
            if isinstance(key, dict):
                key = None
            if key:
                value = item.get("value")
                if value is None:
                    value = _unwrap_proto_value(item)
                else:
                    value = _unwrap_proto_value(value)
                normalized[str(key)] = value
        return normalized

    if isinstance(args, str):
        raw = args.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except json.JSONDecodeError:
            return {"_raw": raw}

    return {}


def extract_thought_signature(part_or_call: Dict[str, Any]) -> Optional[str]:
    if not isinstance(part_or_call, dict):
        return None
    for key in ("thoughtSignature", "thought_signature", "signature"):
        value = part_or_call.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _default_from_schema(schema: Dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return None
    if "default" in schema:
        return schema.get("default")
    if "enum" in schema and isinstance(schema.get("enum"), list):
        for value in schema["enum"]:
            if value is not None:
                return value

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((t for t in schema_type if t != "null"), None)

    if schema_type == "string":
        return ""
    if schema_type in {"number", "integer"}:
        return 0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        return []
    if schema_type == "object":
        return {}

    for union_key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(union_key)
        if isinstance(options, list) and options:
            for option in options:
                default = _default_from_schema(option)
                if default is not None:
                    return default

    return None


def _coerce_tool_args(
    args: Any, schema: Optional[Dict[str, Any]], tool_name: Optional[str] = None
) -> Dict[str, Any]:
    if isinstance(args, dict):
        coerced = dict(args)
    else:
        coerced = {}

    if not isinstance(schema, dict):
        return coerced

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(required, list) or not isinstance(properties, dict):
        return coerced

    lower_map = {
        str(k).lower(): k for k in properties.keys() if isinstance(k, str)
    }
    aliases = {
        "url": ["uri", "link", "href"],
        "query": ["q", "search", "prompt"],
        "path": ["file", "filepath", "file_path"],
        "file_path": ["path", "file", "filepath"],
        "command": ["cmd"],
    }

    for key in required:
        if key in coerced and coerced[key] not in ("", None):
            continue
        if not isinstance(key, str):
            continue
        for alias in aliases.get(key.lower(), []):
            mapped = lower_map.get(alias)
            if mapped and mapped in coerced and coerced[mapped] not in ("", None):
                coerced[key] = coerced[mapped]
                break

    raw_value = None
    if "_raw" in coerced:
        raw_value = coerced.pop("_raw")

    if raw_value is not None and isinstance(raw_value, (str, int, float, bool)):
        target_key = None
        if len(required) == 1 and required[0] in properties:
            target_key = required[0]
        elif len(properties) == 1:
            target_key = next(iter(properties.keys()), None)
        else:
            for candidate in (
                "command",
                "cmd",
                "query",
                "path",
                "file_path",
                "filepath",
                "file",
                "url",
                "pattern",
                "text",
            ):
                if candidate in properties:
                    target_key = candidate
                    break
        if target_key and target_key not in coerced:
            coerced[target_key] = raw_value

    user_text = LAST_USER_TEXT.strip() if isinstance(LAST_USER_TEXT, str) else ""
    user_urls = LAST_USER_URLS if isinstance(LAST_USER_URLS, list) else []
    user_paths = LAST_USER_PATHS if isinstance(LAST_USER_PATHS, list) else []

    for key in required:
        if key in coerced and coerced[key] not in ("", None):
            continue
        prop_schema = properties.get(key, {})
        default_value = _default_from_schema(prop_schema)
        if default_value is None:
            # Heuristic defaults for common file/path parameters.
            if isinstance(key, str):
                lower_key = key.lower()
                if lower_key in {"path", "file", "filepath", "file_path", "directory", "dir"}:
                    if user_paths:
                        default_value = user_paths[0]
                    else:
                        default_value = "."
                elif lower_key in {"paths", "files"}:
                    default_value = ["."]
                elif lower_key in {"url", "page_url", "pageurl", "link"} and user_urls:
                    default_value = user_urls[0]
                elif lower_key in {"query", "prompt", "text", "instruction"} and user_text:
                    default_value = user_text
                elif lower_key in {"todos", "todo", "items"}:
                    default_value = []
        elif isinstance(default_value, str) and not default_value:
            # Prefer user context over empty defaults for text/url fields.
            if isinstance(key, str):
                lower_key = key.lower()
                if lower_key in {"path", "file", "filepath", "file_path", "directory", "dir"}:
                    if user_paths:
                        default_value = user_paths[0]
                    else:
                        default_value = "."
                elif lower_key in {"url", "page_url", "pageurl", "link"} and user_urls:
                    default_value = user_urls[0]
                elif lower_key in {"query", "prompt", "text", "instruction"} and user_text:
                    default_value = user_text
        if default_value is not None:
            coerced[key] = default_value

    return coerced


def convert_gemini_to_anthropic_format(
    gemini_response: Dict[str, Any], tool_schemas: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Convert Antigravity API response to Anthropic API format.

    Args:
        gemini_response: Raw Antigravity API response (may be wrapped in {"response": {...}})

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

    def extract_thinking_text(part: Dict[str, Any]) -> Optional[str]:
        """Extract thinking content from a provider part, if present."""
        if "thought" in part:
            thought = part.get("thought")
            if isinstance(thought, str):
                return thought
            if isinstance(thought, dict):
                return thought.get("text") or thought.get("thought")
            if thought is True and isinstance(part.get("text"), str):
                return part["text"]
        if "thinking" in part:
            thinking = part.get("thinking")
            if isinstance(thinking, str):
                return thinking
            if isinstance(thinking, dict):
                return thinking.get("text") or thinking.get("thinking")
        if "thoughts" in part:
            thoughts = part.get("thoughts")
            if isinstance(thoughts, str):
                return thoughts
            if isinstance(thoughts, list):
                return "\n".join([t for t in thoughts if isinstance(t, str)])
            if isinstance(thoughts, dict):
                return thoughts.get("text") or thoughts.get("thoughts")
        if part.get("type") in {"thought", "thinking"} and isinstance(part.get("text"), str):
            return part["text"]
        return None

    def split_thought_and_text(text: str) -> tuple[Optional[str], Optional[str]]:
        """Heuristically split blended thought+answer text into separate parts."""
        if not isinstance(text, str):
            return None, None
        cleaned = text.strip()
        if not cleaned:
            return None, None

        if "\n\n" in cleaned:
            before, after = cleaned.split("\n\n", 1)
            if before.strip() and after.strip():
                return before.strip(), after.strip()

        thought_markers = (
            "The user",
            "User is",
            "I should",
            "I'll ",
            "I will",
            "Let's ",
            "We should",
            "My task",
            "The question",
        )
        answer_markers = (
            "I'm ",
            "I am ",
            "Here is",
            "Here's",
            "The answer",
            "Yes",
            "No",
            "It is",
            "It's ",
        )
        if not any(marker in cleaned for marker in thought_markers):
            return None, None

        split_at = None
        for marker in answer_markers:
            idx = cleaned.find(marker)
            if idx > 8:
                split_at = idx if split_at is None else min(split_at, idx)

        if split_at is None:
            return None, None

        thought = cleaned[:split_at].strip()
        answer = cleaned[split_at:].strip()
        if len(thought) < 10 or len(answer) < 3:
            return None, None
        return thought, answer

    saw_thinking = False

    pending_thought_signature: Optional[str] = None

    # Extract thinking, text content, and tool calls in order
    for part in candidate.get("content", {}).get("parts", []):
        part_signature = extract_thought_signature(part)
        if part_signature:
            pending_thought_signature = part_signature
        thinking_text = extract_thinking_text(part)
        if thinking_text:
            saw_thinking = True
            thought, answer = split_thought_and_text(thinking_text)
            if thought and answer:
                content.append({"type": "thinking", "thinking": thought})
                content.append({"type": "text", "text": answer})
            else:
                content.append({"type": "thinking", "thinking": thinking_text})
        elif "text" in part:
            # Add text content immediately to preserve order
            content.append({"type": "text", "text": part["text"]})
        elif "functionCall" in part:
            func_call = part["functionCall"]
            func_name = func_call.get("name", "")
            thought_signature = (
                extract_thought_signature(part)
                or extract_thought_signature(func_call)
                or pending_thought_signature
            )
            if thought_signature and thought_signature == pending_thought_signature:
                pending_thought_signature = None
            raw_tool_id = func_call.get("id")
            tool_id = (
                raw_tool_id
                if isinstance(raw_tool_id, str) and raw_tool_id
                else f"toolu_{uuid.uuid4().hex[:24]}"
            )
            if thought_signature:
                TOOL_THOUGHT_SIGNATURES[tool_id] = thought_signature
            TOOL_CALL_CONTEXT[tool_id] = {"name": func_name, "args": parse_function_args(func_call)}
            if isinstance(tool_schemas, dict) and func_name not in tool_schemas:
                continue
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": func_name,
                    "input": _coerce_tool_args(
                        parse_function_args(func_call),
                        tool_schemas.get(func_name) if isinstance(tool_schemas, dict) else None,
                        func_name,
                    ),
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
    if any(block.get("type") == "tool_use" for block in content) and finish_reason == "end_turn":
        finish_reason = "tool_use"

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
    stream_generator: AsyncIterator[Dict[str, Any]],
    original_model: str,
    tool_schemas: Optional[Dict[str, Dict[str, Any]]] = None,
) -> AsyncIterator[str]:
    """
    Convert Antigravity SSE stream to Anthropic SSE format.

    Args:
        stream_generator: Antigravity SSE stream
        original_model: Original requested model name

    Yields:
        str: SSE-formatted events in Anthropic format
    """
    import uuid

    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    text_buffer = ""
    tool_calls: List[Dict[str, Any]] = []
    current_block_type: Optional[str] = None
    current_block_index = -1
    input_tokens = 0
    output_tokens = 0
    pending_thought_signature: Optional[str] = None

    # Send message_start event
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'content': [], 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"

    has_content = False
    first_delta = True

    candidates: List[Dict[str, Any]] = []
    had_error = False

    try:
        def extract_thinking_text(part: Dict[str, Any]) -> Optional[str]:
            """Extract thinking content from a provider part, if present."""
            if "thought" in part:
                thought = part.get("thought")
                if isinstance(thought, str):
                    return thought
                if isinstance(thought, dict):
                    return thought.get("text") or thought.get("thought")
                if thought is True and isinstance(part.get("text"), str):
                    return part["text"]
            if "thinking" in part:
                thinking = part.get("thinking")
                if isinstance(thinking, str):
                    return thinking
                if isinstance(thinking, dict):
                    return thinking.get("text") or thinking.get("thinking")
            if "thoughts" in part:
                thoughts = part.get("thoughts")
                if isinstance(thoughts, str):
                    return thoughts
                if isinstance(thoughts, list):
                    return "\n".join([t for t in thoughts if isinstance(t, str)])
                if isinstance(thoughts, dict):
                    return thoughts.get("text") or thoughts.get("thoughts")
            if part.get("type") in {"thought", "thinking"} and isinstance(part.get("text"), str):
                return part["text"]
            return None

        def split_thought_and_text(text: str) -> tuple[Optional[str], Optional[str]]:
            """Heuristically split blended thought+answer text into separate parts."""
            if not isinstance(text, str):
                return None, None
            cleaned = text.strip()
            if not cleaned:
                return None, None

            if "\n\n" in cleaned:
                before, after = cleaned.split("\n\n", 1)
                if before.strip() and after.strip():
                    return before.strip(), after.strip()

            thought_markers = (
                "The user",
                "User is",
                "I should",
                "I'll ",
                "I will",
                "Let's ",
                "We should",
                "My task",
                "The question",
            )
            answer_markers = (
                "I'm ",
                "I am ",
                "Here is",
                "Here's",
                "The answer",
                "Yes",
                "No",
                "It is",
                "It's ",
            )
            if not any(marker in cleaned for marker in thought_markers):
                return None, None

            split_at = None
            for marker in answer_markers:
                idx = cleaned.find(marker)
                if idx > 8:
                    split_at = idx if split_at is None else min(split_at, idx)

            if split_at is None:
                return None, None

            thought = cleaned[:split_at].strip()
            answer = cleaned[split_at:].strip()
            if len(thought) < 10 or len(answer) < 3:
                return None, None
            return thought, answer

        def start_block(block_type: str) -> Optional[str]:
            nonlocal current_block_type, current_block_index
            if current_block_type == block_type:
                return None
            if current_block_type is not None:
                stop_event = f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"
            else:
                stop_event = None
            current_block_index += 1
            current_block_type = block_type
            if block_type == "thinking":
                content_block = {"type": "thinking", "thinking": ""}
            else:
                content_block = {"type": "text", "text": ""}
            start_event = f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': current_block_index, 'content_block': content_block})}\n\n"
            return (stop_event or "") + start_event

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
                part_signature = extract_thought_signature(part)
                if part_signature:
                    pending_thought_signature = part_signature
                thinking_text = extract_thinking_text(part)
                if thinking_text:
                    if not str(thinking_text).strip():
                        continue
                    has_content = True
                    if first_delta:
                        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
                        first_delta = False

                    thought, answer = split_thought_and_text(thinking_text)
                    if thought and answer:
                        if not thought.strip():
                            thought = None
                        if not answer.strip():
                            answer = None
                    if thought and answer:
                        maybe_events = start_block("thinking")
                        if maybe_events:
                            yield maybe_events
                        text_buffer += thought
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'thinking_delta', 'thinking': thought}})}\n\n"

                        maybe_events = start_block("text")
                        if maybe_events:
                            yield maybe_events
                        text_buffer += answer
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'text_delta', 'text': answer}})}\n\n"
                    else:
                        maybe_events = start_block("thinking")
                        if maybe_events:
                            yield maybe_events
                        text_buffer += thinking_text
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'thinking_delta', 'thinking': thinking_text}})}\n\n"

                elif "text" in part:
                    if not str(part.get("text", "")).strip():
                        continue
                    has_content = True
                    if first_delta:
                        yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"
                        first_delta = False

                    text = part["text"]
                    text_buffer += text
                    thought, answer = split_thought_and_text(text)
                    if thought and answer:
                        if not thought.strip():
                            thought = None
                        if not answer.strip():
                            answer = None
                    if thought and answer:
                        maybe_events = start_block("thinking")
                        if maybe_events:
                            yield maybe_events
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'thinking_delta', 'thinking': thought}})}\n\n"

                        maybe_events = start_block("text")
                        if maybe_events:
                            yield maybe_events
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'text_delta', 'text': answer}})}\n\n"
                    else:
                        maybe_events = start_block("text")
                        if maybe_events:
                            yield maybe_events
                        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': current_block_index, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"

                elif "functionCall" in part:
                    func_call = part["functionCall"]
                    func_name = func_call.get("name", "")
                    thought_signature = (
                        extract_thought_signature(part)
                        or extract_thought_signature(func_call)
                        or pending_thought_signature
                    )
                    if thought_signature and thought_signature == pending_thought_signature:
                        pending_thought_signature = None
                    logger.info(
                        "Antigravity functionCall keys: %s",
                        sorted(func_call.keys()) if isinstance(func_call, dict) else [],
                    )
                    func_args = _coerce_tool_args(
                        parse_function_args(func_call),
                        tool_schemas.get(func_name) if isinstance(tool_schemas, dict) else None,
                        func_name,
                    )
                    if isinstance(tool_schemas, dict) and func_name not in tool_schemas:
                        continue
                    raw_tool_id = func_call.get("id")
                    tool_id = (
                        raw_tool_id
                        if isinstance(raw_tool_id, str) and raw_tool_id
                        else f"toolu_{uuid.uuid4().hex[:24]}"
                    )
                    if func_name:
                        logger.info(
                            "Antigravity stream tool_call: %s (id=%s args: %s)",
                            func_name,
                            tool_id,
                            json.dumps(func_args)[:300] if isinstance(func_args, dict) else "",
                        )
                    existing = next(
                        (tc for tc in tool_calls if tc.get("id") == tool_id),
                        None,
                    )
                    if existing:
                        if func_args:
                            existing["args"] = func_args
                        if thought_signature and not existing.get("thought_signature"):
                            existing["thought_signature"] = thought_signature
                    elif (
                        tool_calls
                        and tool_calls[-1]["name"] == func_name
                        and not tool_calls[-1]["args"]
                        and func_args
                    ):
                        tool_calls[-1]["args"] = func_args
                    else:
                        tool_calls.append(
                            {
                                "id": tool_id,
                                "name": func_name,
                                "args": func_args,
                                "thought_signature": thought_signature,
                            }
                        )
                    if tool_calls:
                        TOOL_CALL_CONTEXT[tool_calls[-1]["id"]] = {
                            "name": tool_calls[-1]["name"],
                            "args": tool_calls[-1]["args"],
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

    # Close any open content block
    if current_block_type is not None:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_block_index})}\n\n"

    # Send any tool calls (stream input JSON via input_json_delta)
    for tool_call in tool_calls:
        tool_index = current_block_index + 1
        thought_signature = tool_call.get("thought_signature")
        if thought_signature:
            TOOL_THOUGHT_SIGNATURES[tool_call["id"]] = thought_signature
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': tool_index, 'content_block': {'type': 'tool_use', 'id': tool_call['id'], 'name': tool_call['name'], 'input': {}}})}\n\n"
        tool_args = tool_call.get("args", {})
        partial_json = json.dumps(tool_args if isinstance(tool_args, dict) else tool_args)
        yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': tool_index, 'delta': {'type': 'input_json_delta', 'partial_json': partial_json}})}\n\n"
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tool_index})}\n\n"
        current_block_index = tool_index

    # Map finish reason
    final_stop = "error" if had_error else "end_turn"
    if candidates:
        finish_status = candidates[0].get("finishReason", "STOP")
        if finish_status == "MAX_TOKENS":
            final_stop = "max_tokens"
        elif finish_status == "SAFETY":
            final_stop = "error"
    if tool_calls and final_stop == "end_turn":
        final_stop = "tool_use"
    logger.info(
        "Antigravity stream completed (tool_calls=%s, stop_reason=%s)",
        len(tool_calls),
        final_stop,
    )

    # Send message_delta
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': final_stop, 'stop_sequence': None}, 'usage': {'input_tokens': input_tokens, 'output_tokens': output_tokens}})}\n\n"

    # Send message_stop
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
