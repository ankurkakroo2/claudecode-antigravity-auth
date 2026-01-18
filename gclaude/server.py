"""
Server wrapper for starting/stopping the proxy as a background process.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

from gclaude.config import Config
from gclaude.utils import (
    get_pid_path,
    get_log_path,
    get_config_dir,
    is_proxy_running,
    load_config,
)


class ProxyServer:
    """Manages the proxy server as a background process."""

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.pid_path = get_pid_path()
        self.log_path = get_log_path()

    def is_running(self) -> tuple[bool, int | None]:
        """Check if the proxy server is running."""
        return is_proxy_running()

    def get_server_script_path(self) -> Path:
        """Get the path to the server script."""
        # Prefer the packaged proxy server module.
        current_dir = Path(__file__).parent
        server_path = current_dir / "proxy" / "server.py"

        if server_path.exists():
            return server_path

        return Path(__file__)

    def get_project_root(self) -> Path:
        """Get the project root for module execution."""
        return Path(__file__).resolve().parent.parent

    def start(self) -> tuple[bool, str]:
        """
        Start the proxy server in the background.

        Returns:
            tuple: (success, message)
        """
        running, pid = self.is_running()
        if running:
            return False, f"Proxy already running (PID: {pid})"

        # Ensure log directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare environment
        env = os.environ.copy()

        # Set environment variables from config
        env["HOST"] = self.config.proxy_host
        env["PORT"] = str(self.config.proxy_port)
        env["LOG_LEVEL"] = self.config.log_level

        # Set Antigravity model mappings from config
        if self.config.auth_enabled:
            for name in ["haiku", "sonnet", "opus"]:
                model_config = self.config.models.get(name, {})
                target_model = model_config.get("target", "")
                if target_model and model_config.get("type") == "antigravity":
                    env[f"ANTIGRAVITY_{name.upper()}_MODEL"] = target_model

        # Start the server
        try:
            # Open log file for appending
            log_file = open(self.log_path, "a")

            process = subprocess.Popen(
                [sys.executable, "-m", "gclaude.proxy.server"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                cwd=str(self.get_project_root()),
                start_new_session=True,
            )

            # Write PID to file
            with open(self.pid_path, "w") as f:
                f.write(str(process.pid))

            # Give it a moment to start
            time.sleep(1)

            # Check if it's still running
            if process.poll() is None:
                return True, f"Proxy started (PID: {process.pid})"
            else:
                # Failed to start
                self.pid_path.unlink(missing_ok=True)
                return False, "Proxy failed to start - check logs"

        except Exception as e:
            return False, f"Failed to start proxy: {e}"

    def stop(self) -> tuple[bool, str]:
        """
        Stop the proxy server.

        Returns:
            tuple: (success, message)
        """
        running, pid = self.is_running()
        if not running:
            return False, "Proxy is not running"

        try:
            process = psutil.Process(pid)

            # Try graceful shutdown first
            process.terminate()

            # Wait up to 5 seconds
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                # Force kill if doesn't stop
                process.kill()

            # Clean up PID file
            self.pid_path.unlink(missing_ok=True)

            return True, "Proxy stopped"
        except psutil.NoSuchProcess:
            self.pid_path.unlink(missing_ok=True)
            return False, "Proxy process not found (already stopped?)"
        except Exception as e:
            return False, f"Failed to stop proxy: {e}"

    def restart(self) -> tuple[bool, str]:
        """
        Restart the proxy server.

        Returns:
            tuple: (success, message)
        """
        # Stop if running
        running, pid = self.is_running()
        if running:
            self.stop()
            time.sleep(1)

        # Start again
        return self.start()

    def get_status(self) -> dict:
        """
        Get detailed status of the proxy server.

        Returns:
            dict with status information
        """
        running, pid = self.is_running()

        status = {
            "running": running,
            "pid": pid,
            "host": self.config.proxy_host,
            "port": self.config.proxy_port,
            "url": f"http://{self.config.proxy_host}:{self.config.proxy_port}",
            "log_file": str(self.log_path),
        }

        if running and pid:
            try:
                process = psutil.Process(pid)
                status["uptime"] = time.time() - process.create_time()
                status["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
                status["cpu_percent"] = round(process.cpu_percent(), 1)
            except psutil.NoSuchProcess:
                status["running"] = False
                status["pid"] = None

        # Add auth status
        status["auth"] = {
            "enabled": self.config.auth_enabled,
            "account_email": self.config.account_email,
        }

        # Add model routes
        status["models"] = {}
        for name, config in self.config.models.items():
            status["models"][name] = {
                "pattern": config.get("pattern"),
                "target": config.get("target"),
                "type": config.get("type"),
            }

        return status

    def tail_logs(self, lines: int = 50) -> list[str]:
        """
        Get the last N lines from the log file.

        Args:
            lines: Number of lines to return

        Returns:
            list of log lines
        """
        if not self.log_path.exists():
            return ["No log file found."]

        try:
            with open(self.log_path, "r") as f:
                all_lines = f.readlines()
                return all_lines[-lines:] if len(all_lines) > lines else all_lines
        except Exception as e:
            return [f"Error reading log file: {e}"]


def show_status_rich(console, status: dict) -> None:
    """Display status using rich formatting."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text

    # Build status table
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column()

    # Proxy status
    if status["running"]:
        status_text = "[green]● Running[/green]"
        if status.get("uptime"):
            import datetime

            uptime_sec = int(status["uptime"])
            uptime = str(datetime.timedelta(seconds=uptime_sec))
            status_text += f" [dim](up {uptime})[/dim]"
        table.add_row("Proxy:", status_text)
        table.add_row("PID:", str(status["pid"]))
        table.add_row("Endpoint:", f"[link={status['url']}]{status['url']}[/link]")
        if status.get("memory_mb"):
            table.add_row("Memory:", f"{status['memory_mb']} MB")
        if status.get("cpu_percent") is not None:
            table.add_row("CPU:", f"{status['cpu_percent']}%")
    else:
        table.add_row("Proxy:", "[red]○ Stopped[/red]")

    table.add_row("")

    # Auth status
    auth = status.get("auth", {})
    if auth.get("enabled"):
        table.add_row("OAuth:", "[green]✓ Enabled[/green]")
        if auth.get("account_email"):
            table.add_row("Account:", auth["account_email"])
    else:
        table.add_row("OAuth:", "[dim]Disabled[/dim]")

    table.add_row("")

    # Model routes
    table.add_row("[bold]Model Routes:[/bold]")
    models = status.get("models", {})
    for name, config in models.items():
        target = config.get("target", "")
        model_type = config.get("type", "")
        type_color = "cyan" if model_type == "antigravity" else "blue"
        table.add_row(
            f"  • {name}:", f"[{type_color}]{target}[/{type_color}] [dim]({model_type})[/dim]"
        )

    # Display in panel
    panel = Panel(
        table,
        title="[bold]gclaude Status[/bold]",
        border_style="blue",
        padding=(1, 1),
    )

    console.print(panel)
