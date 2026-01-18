"""
Utility functions for gclaude.
"""

import os
import json
from pathlib import Path
from typing import Any

from gclaude import CONFIG_DIR, CONFIG_FILE, PID_FILE, LOG_FILE


def get_config_dir() -> Path:
    """Get and create the config directory."""
    config_dir = Path(CONFIG_DIR).expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Get the config file path."""
    return Path(CONFIG_FILE).expanduser()


def get_pid_path() -> Path:
    """Get the PID file path."""
    return Path(PID_FILE).expanduser()


def get_log_path() -> Path:
    """Get the log file path."""
    log_path = Path(LOG_FILE).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def load_config() -> dict[str, Any]:
    """Load configuration from file."""
    config_path = get_config_path()
    if config_path.exists():
        with open(config_path, "r") as f:
            return json.load(f)
    return {"version": "1.0.0"}


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to file."""
    config_path = get_config_path()
    get_config_dir()  # Ensure directory exists
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def get_shell_rc_path() -> Path | None:
    """Detect and return the appropriate shell RC file path."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()

    if "zsh" in shell:
        rc_file = home / ".zshrc"
    elif "bash" in shell:
        rc_file = home / ".bashrc"
    elif "fish" in shell:
        rc_file = home / ".config/fish/config.fish"
    else:
        # Default to zshrc on macOS
        rc_file = home / ".zshrc" if os.name == "darwin" else home / ".bashrc"

    if rc_file.exists():
        return rc_file
    return rc_file  # Return even if doesn't exist - we'll create it


def is_proxy_running() -> tuple[bool, int | None]:
    """Check if the proxy server is running.

    Returns:
        tuple: (is_running, pid)
    """
    pid_path = get_pid_path()
    if not pid_path.exists():
        return False, None

    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())

        # Check if process is actually running
        import psutil
        if psutil.pid_exists(pid):
            try:
                process = psutil.Process(pid)
                if "gclaude" in process.name().lower() or "python" in process.name().lower():
                    return True, pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Stale PID file
        pid_path.unlink()
        return False, None
    except (ValueError, IOError):
        return False, None


def get_default_models() -> dict[str, dict[str, str]]:
    """Get default model mappings."""
    return {
        "haiku": {
            "pattern": "*haiku*",
            "target": "antigravity-gemini-3-flash",
            "type": "antigravity",
        },
        "sonnet": {
            "pattern": "*sonnet*",
            "target": "antigravity-claude-sonnet-4-5-thinking",
            "type": "antigravity",
        },
        "opus": {
            "pattern": "*opus*",
            "target": "antigravity-claude-opus-4-5-thinking",
            "type": "antigravity",
        },
    }


def get_available_antigravity_models() -> list[dict]:
    """Get list of antigravity models with descriptions (uses Google OAuth with Claude Code API)."""
    return [
        {
            "id": "antigravity-gemini-3-flash",
            "name": "Gemini 3 Flash",
            "description": "Fast & efficient - Best for haiku requests",
            "type": "antigravity",
        },
        {
            "id": "antigravity-gemini-3-pro-low",
            "name": "Gemini 3 Pro Low",
            "description": "Faster responses with less thinking",
            "type": "antigravity",
        },
        {
            "id": "antigravity-gemini-3-pro-high",
            "name": "Gemini 3 Pro High",
            "description": "Deeper reasoning with more thinking",
            "type": "antigravity",
        },
        {
            "id": "antigravity-claude-sonnet-4-5",
            "name": "Claude Sonnet 4.5",
            "description": "Balanced capability - Good for general coding",
            "type": "antigravity",
        },
        {
            "id": "antigravity-claude-sonnet-4-5-thinking",
            "name": "Claude Sonnet 4.5 (Thinking)",
            "description": "Extended reasoning - For complex tasks",
            "type": "antigravity",
        },
        {
            "id": "antigravity-claude-opus-4-5-thinking",
            "name": "Claude Opus 4.5 (Thinking)",
            "description": "Advanced reasoning - Best for opus requests",
            "type": "antigravity",
        },
        {
            "id": "antigravity-gpt-oss-120b-medium",
            "name": "GPT-OSS 120B Medium",
            "description": "Open source alternative - Medium capability",
            "type": "antigravity",
        },
    ]

