#!/bin/bash
# Wrapper script to set the process name for the Gemini proxy
# This makes it identifiable in Activity Monitor and process lists

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Set process title using exec -a (argv[0] becomes the process name)
exec -a "gemini-claude-proxy" "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/server.py"
