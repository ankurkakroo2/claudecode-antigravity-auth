"""
Model access detection for Antigravity.

Tests which Antigravity models are accessible to the user's OAuth account.
"""

import asyncio
from typing import Dict

import aiohttp

from gclaude.utils import get_available_antigravity_models


# Keep aligned with gclaude.proxy.antigravity_client.ANTIGRAVITY_ENDPOINTS
ANTIGRAVITY_ENDPOINTS = [
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
    "https://autopush-cloudcode-pa.sandbox.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]

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


async def test_model_access(
    access_token: str,
    model_id: str,
    timeout: int = 10,
    *,
    project_id: str | None = None,
) -> bool:
    """Test if a specific model is accessible using Antigravity API.

    Note: access can be scoped to the user's Code Assist / AI Companion project.
    Using the wrong project id can yield misleading "license" errors or make paid
    models appear unavailable.

    Args:
        access_token: OAuth access token
        model_id: Model ID to test
        timeout: Request timeout in seconds
        project_id: Project id to test against (preferred; falls back to a legacy default)

    Returns:
        True if model is accessible, False otherwise
    """
    # Prefer the discovered project id; keep the legacy default as a fallback.
    project_id = project_id or "rising-fact-p41fc"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
        "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
    }

    # Antigravity API format according to API spec
    # Path is /v1internal:generateContent, NOT /v1/models/{model}:generateContent
    request_body = {
        "project": project_id,
        "model": get_api_model_name(model_id),
        "request": {
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        },
        "userAgent": "antigravity",
    }

    saw_rate_limit = False

    for endpoint in ANTIGRAVITY_ENDPOINTS:
        url = f"{endpoint}/v1internal:generateContent"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=request_body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status == 200:
                        return True

                    if response.status == 429:
                        # Quota exhausted on this endpoint; keep checking other endpoints.
                        saw_rate_limit = True
                        continue

                    if response.status in (401, 403):
                        # Treat as not accessible.
                        return False

                    # Other errors - try next endpoint
        except (asyncio.TimeoutError, aiohttp.ClientError):
            # Network error - try next endpoint
            continue

    # If every endpoint was rate-limited, treat as accessible but currently exhausted.
    return saw_rate_limit


async def detect_model_access(
    access_token: str,
    models: list[str] | None = None,
    progress_callback=None,
    *,
    project_id: str | None = None,
) -> Dict[str, bool]:
    """
    Detect which Antigravity models are accessible.

    Args:
        access_token: OAuth access token
        models: List of model IDs to test (defaults to all Antigravity models)
        progress_callback: Optional callback for progress updates

    Returns:
        Dictionary mapping model_id -> accessible (True/False)
    """
    if models is None:
        models = [m["id"] for m in get_available_antigravity_models()]

    results = {}

    for i, model_id in enumerate(models):
        if progress_callback:
            progress_callback(i + 1, len(models), model_id)

        try:
            accessible = await test_model_access(access_token, model_id, project_id=project_id)
            results[model_id] = accessible
        except Exception:
            results[model_id] = False

    return results


async def detect_with_rich_output(
    access_token: str,
    console,
    *,
    project_id: str | None = None,
) -> Dict[str, bool]:
    """
    Detect model access with rich console output.

    Args:
        access_token: OAuth access token
        console: Rich console instance

    Returns:
        Dictionary mapping model_id -> accessible (True/False)
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskID
    from rich.live import Live

    models = [m["id"] for m in get_available_antigravity_models()]
    results = {}

    with console.status("[bold yellow]Detecting your model access...") as status:
        for model_id in models:
            try:
                accessible = await test_model_access(access_token, model_id, project_id=project_id)
                results[model_id] = accessible

                if accessible:
                    console.print(f"  [green]✓[/green] {model_id}")
                else:
                    console.print(f"  [red]✗[/red] {model_id} [dim](not available)[/dim]")
            except Exception:
                results[model_id] = False
                console.print(f"  [red]✗[/red] {model_id} [dim](error)[/dim]")

    return results


def get_available_models_for_mapping(access_results: dict[str, bool]) -> list[dict]:
    """
    Get list of available models based on access results.

    Args:
        access_results: Dictionary from detect_model_access

    Returns:
        List of available model dicts (Antigravity-only)
    """
    from gclaude.utils import get_available_antigravity_models

    available = []

    # Add available Antigravity models
    for model in get_available_antigravity_models():
        if access_results.get(model["id"], True):
            available.append(model)

    return available


def get_recommended_mapping(access_results: Dict[str, bool]) -> Dict[str, Dict]:
    """
    Get recommended model mappings based on access.

    Args:
        access_results: Dictionary from detect_model_access

    Returns:
        Dictionary with recommended mappings for haiku, sonnet, opus
    """
    def pick_first_available(candidates: list[str]) -> str:
        for candidate in candidates:
            if access_results.get(candidate, False):
                return candidate
        return candidates[0]

    mapping = {}

    haiku_candidates = [
        "antigravity-gemini-3-flash",
        "antigravity-gemini-3-pro-low",
        "antigravity-gemini-3-pro-high",
    ]
    sonnet_candidates = [
        "antigravity-claude-sonnet-4-5-thinking",
        "antigravity-claude-sonnet-4-5",
        "antigravity-gemini-3-pro-high",
        "antigravity-gemini-3-pro-low",
    ]
    opus_candidates = [
        "antigravity-claude-opus-4-5-thinking",
        "antigravity-claude-sonnet-4-5-thinking",
        "antigravity-gemini-3-pro-high",
    ]

    mapping["haiku"] = {
        "target": pick_first_available(haiku_candidates),
        "type": "antigravity",
        "recommended": True,
    }
    mapping["sonnet"] = {
        "target": pick_first_available(sonnet_candidates),
        "type": "antigravity",
        "recommended": True,
    }
    mapping["opus"] = {
        "target": pick_first_available(opus_candidates),
        "type": "antigravity",
        "recommended": True,
    }

    return mapping
