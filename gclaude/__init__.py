"""
gclaude - Antigravity OAuth proxy for Claude Code

A CLI tool for setting up and running a proxy server that translates
Claude Code API requests to Antigravity-backed models.
"""

__version__ = "1.0.0"

# Configuration directory
CONFIG_DIR = "~/.gclaude"
CONFIG_FILE = "~/.gclaude/config.json"
PID_FILE = "~/.gclaude/proxy.pid"
LOG_FILE = "~/.gclaude/logs/proxy.log"
