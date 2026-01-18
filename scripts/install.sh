#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/ankurkakroo2/claudecode-antigravity-auth.git"
REPO_URL="$REPO_URL_DEFAULT"
INSTALL_MODE="remote"
RC_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --local)
      INSTALL_MODE="local"
      shift
      ;;
    --rc-path)
      RC_PATH="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: install.sh [--repo <git-url>] [--local] [--rc-path <path>]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.9+ and retry."
  exit 1
fi

install_pkg() {
  if [[ "$INSTALL_MODE" == "local" ]]; then
    python3 -m pip install -e .
    return
  fi

  if command -v pipx >/dev/null 2>&1; then
    if pipx list | grep -q "gclaude"; then
      pipx upgrade gclaude
    else
      pipx install "git+$REPO_URL"
    fi
  else
    python3 -m pip install --user "git+$REPO_URL"
  fi
}

install_pkg

if command -v gclaude >/dev/null 2>&1; then
  if [[ -n "$RC_PATH" ]]; then
    gclaude install-shell --rc-path "$RC_PATH" --force
  else
    gclaude install-shell --force
  fi
else
  if [[ -n "$RC_PATH" ]]; then
    python3 -m gclaude install-shell --rc-path "$RC_PATH" --force
  else
    python3 -m gclaude install-shell --force
  fi
fi

echo ""
echo "Install complete."
echo "- Initialize OAuth + model mappings: gclaude init"
echo "- Then run: gclaude \"your prompt\""
echo "- Manage the server with: gclaude start|stop|status"
