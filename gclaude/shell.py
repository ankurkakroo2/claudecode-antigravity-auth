"""Shell integration helpers for gclaude."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
import textwrap

from gclaude.utils import get_shell_rc_path

SHELL_BLOCK_START = "# >>> gclaude >>>"
SHELL_BLOCK_END = "# <<< gclaude <<<"


def render_shell_function() -> str:
    return textwrap.dedent(
        """
        gclaude() {
          local gclaude_cmd=()
          if command -v gclaude >/dev/null 2>&1 && type -P gclaude >/dev/null 2>&1; then
            gclaude_cmd=(command gclaude)
          else
            gclaude_cmd=(python3 -m gclaude)
          fi

          local cli_cmds=("init" "start" "stop" "restart" "status" "logs" "auth" "config" "models" "set-model" "update" "install-shell" "cli")
          local wants_cli=0
          if [ $# -gt 0 ]; then
            for cmd in "${cli_cmds[@]}"; do
              if [ "$1" = "$cmd" ]; then
                wants_cli=1
                break
              fi
            done
          fi

          if [ "$wants_cli" -eq 1 ]; then
            if [ "$1" = "cli" ]; then
              shift
            fi
            "${gclaude_cmd[@]}" "$@"
            return $?
          fi

          if ! command -v claude >/dev/null 2>&1; then
            echo "claude CLI not found. Install with: npm i -g @anthropic-ai/claude-code"
            return 1
          fi

          local config_path="$HOME/.gclaude/config.json"
          if [ ! -f "$config_path" ]; then
            echo "gclaude is not configured. Run: gclaude init"
            return 1
          fi

          local proxy_info
          proxy_info="$(
python3 - <<'PY'
import json
import pathlib
import sys

path = pathlib.Path.home() / ".gclaude" / "config.json"
try:
    data = json.loads(path.read_text())
except Exception:
    sys.exit(2)

proxy = data.get("proxy", {})
host = proxy.get("host", "127.0.0.1")
port = proxy.get("port", 8082)
auth_enabled = data.get("auth", {}).get("enabled", False)
print(f"{host}:{port}:{1 if auth_enabled else 0}")
PY
          )"

          if [ -z "$proxy_info" ]; then
            echo "Unable to read gclaude config. Run: gclaude init"
            return 1
          fi

          local proxy_host proxy_port auth_enabled
          IFS=":" read -r proxy_host proxy_port auth_enabled <<< "$proxy_info"

          if [ "$auth_enabled" != "1" ]; then
            echo "OAuth not configured. Run: gclaude init"
            return 1
          fi

          local health_url="http://${proxy_host}:${proxy_port}/health"
          if ! curl -sf "$health_url" >/dev/null 2>&1; then
            echo "Starting gclaude proxy..."
            "${gclaude_cmd[@]}" start >/dev/null 2>&1 || true
            for _ in 1 2 3 4 5; do
              if curl -sf "$health_url" >/dev/null 2>&1; then
                break
              fi
              sleep 1
            done
          fi

          if ! curl -sf "$health_url" >/dev/null 2>&1; then
            echo "Proxy failed to start. Run: ${gclaude_cmd[*]} logs -f"
            return 1
          fi

          local settings_path="$HOME/.claude/antigravity-settings.json"
          GCLAUDE_PROXY_HOST="$proxy_host" GCLAUDE_PROXY_PORT="$proxy_port" python3 - <<'PY'
import json
import os
import pathlib

host = os.environ.get("GCLAUDE_PROXY_HOST", "127.0.0.1")
port = os.environ.get("GCLAUDE_PROXY_PORT", "8082")
settings_path = pathlib.Path.home() / ".claude" / "antigravity-settings.json"
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings = {
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "dummy-key-proxy-handles-auth",
    "ANTHROPIC_BASE_URL": f"http://{host}:{port}",
    "API_TIMEOUT_MS": "3000000"
  }
}
settings_path.write_text(json.dumps(settings, indent=2))
PY

          local mcp_args=()
          if [ -f "$HOME/.claude/mcp_config.json" ]; then
            mcp_args=(--mcp-config "$HOME/.claude/mcp_config.json")
          fi

          claude --settings "$settings_path" "${mcp_args[@]}" --dangerously-skip-permissions "$@"
        }
        """
    ).strip()


def render_shell_block() -> str:
    return "\n".join([SHELL_BLOCK_START, render_shell_function(), SHELL_BLOCK_END, ""])


def _strip_existing_block(content: str) -> str:
    if SHELL_BLOCK_START in content and SHELL_BLOCK_END in content:
        pre, rest = content.split(SHELL_BLOCK_START, 1)
        _, post = rest.split(SHELL_BLOCK_END, 1)
        return pre.rstrip() + "\n\n" + post.lstrip()
    return content


def install_shell_block(
    rc_path: Optional[Path] = None,
    *,
    force: bool = False,
) -> Tuple[Path, bool]:
    rc_path = rc_path or get_shell_rc_path()
    if rc_path is None:
        raise RuntimeError("Unable to determine shell rc path")

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    content = rc_path.read_text() if rc_path.exists() else ""

    if SHELL_BLOCK_START in content and SHELL_BLOCK_END in content:
        if not force:
            return rc_path, False
        content = _strip_existing_block(content)

    block = render_shell_block()
    if content.strip():
        content = content.rstrip() + "\n\n" + block
    else:
        content = block

    rc_path.write_text(content)
    return rc_path, True
