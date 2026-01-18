"""
Configuration management for gclaude.
"""

import json
from pathlib import Path
from typing import Any, Optional

from gclaude.utils import (
    get_config_dir,
    get_config_path,
    load_config,
    save_config,
    get_default_models,
    get_shell_rc_path,
)


class Config:
    """Configuration manager for gclaude."""

    def __init__(self):
        self._config = load_config()
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Ensure default values exist."""
        defaults = {
            "version": "1.0.0",
            "proxy": {
                "host": "127.0.0.1",
                "port": 8082,
                "log_level": "INFO",
            },
            "auth": {
                "enabled": False,
                "account_email": None,
            },
            "models": get_default_models(),
        }

        for key, value in defaults.items():
            if key not in self._config:
                self._config[key] = value
            elif isinstance(value, dict) and isinstance(self._config[key], dict):
                for subkey, subvalue in value.items():
                    if subkey not in self._config[key]:
                        self._config[key][subkey] = subvalue

    def save(self) -> None:
        """Save configuration to file."""
        save_config(self._config)

    @property
    def proxy_host(self) -> str:
        return self._config.get("proxy", {}).get("host", "127.0.0.1")

    @proxy_host.setter
    def proxy_host(self, value: str) -> None:
        if "proxy" not in self._config:
            self._config["proxy"] = {}
        self._config["proxy"]["host"] = value

    @property
    def proxy_port(self) -> int:
        return self._config.get("proxy", {}).get("port", 8082)

    @proxy_port.setter
    def proxy_port(self, value: int) -> None:
        if "proxy" not in self._config:
            self._config["proxy"] = {}
        self._config["proxy"]["port"] = value

    @property
    def log_level(self) -> str:
        return self._config.get("proxy", {}).get("log_level", "INFO")

    @log_level.setter
    def log_level(self, value: str) -> None:
        if "proxy" not in self._config:
            self._config["proxy"] = {}
        self._config["proxy"]["log_level"] = value

    @property
    def auth_enabled(self) -> bool:
        return self._config.get("auth", {}).get("enabled", False)

    @auth_enabled.setter
    def auth_enabled(self, value: bool) -> None:
        if "auth" not in self._config:
            self._config["auth"] = {}
        self._config["auth"]["enabled"] = value

    @property
    def account_email(self) -> Optional[str]:
        return self._config.get("auth", {}).get("account_email")

    @account_email.setter
    def account_email(self, value: Optional[str]) -> None:
        if "auth" not in self._config:
            self._config["auth"] = {}
        self._config["auth"]["account_email"] = value

    @property
    def models(self) -> dict[str, dict[str, str]]:
        return self._config.get("models", get_default_models())

    @models.setter
    def models(self, value: dict[str, dict[str, str]]) -> None:
        self._config["models"] = value

    def set_model_mapping(self, name: str, pattern: str, target: str, type: str) -> None:
        """Set a model mapping."""
        if "models" not in self._config:
            self._config["models"] = {}
        self._config["models"][name] = {
            "pattern": pattern,
            "target": target,
            "type": type,
        }

    def is_configured(self) -> bool:
        """Check if the proxy is configured."""
        return self._config.get("models") is not None

    def get_model_target(self, model_name: str) -> Optional[tuple[str, str]]:
        """
        Get the target model and type for a given model name.

        Args:
            model_name: The model name to look up

        Returns:
            tuple of (target_model, type) or None
        """
        import fnmatch

        models = self.models
        for name, config in models.items():
            pattern = config.get("pattern", "")
            target = config.get("target")
            model_type = config.get("type", "antigravity")
            if fnmatch.fnmatch(model_name.lower(), pattern.lower()):
                return target, model_type
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return config as dictionary."""
        return self._config.copy()

