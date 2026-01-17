"""
Main CLI interface for gclaude.

Provides commands: init, start, stop, restart, status, logs, auth, config
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint
from rich.json import JSON

from gclaude.config import Config, import_env_api_key
from gclaude.server import ProxyServer, show_status_rich
from gclaude.utils import (
    get_config_dir,
    get_config_path,
    get_shell_rc_path,
    get_available_antigravity_models,
    get_available_gemini_models,
)

console = Console()


@click.group()
@click.version_option(version="1.0.0", prog_name="gclaude")
def cli():
    """gclaude - Gemini → Claude Code Proxy with Antigravity OAuth"""
    pass


@cli.command()
def init():
    """Initialize gclaude with guided setup."""
    from rich.panel import Panel
    from rich.prompt import Confirm
    import questionary

    console.print()
    console.print(
        Panel.fit(
            """[bold cyan]🚀 Welcome to gclaude[/bold cyan]

[bold cyan]Gemini → Claude Code Proxy with Antigravity OAuth[/bold cyan]

This will guide you through:
  ✓ Authenticating with Google OAuth
  ✓ Detecting your model access
  ✓ Selecting model mappings
  ✓ Creating configuration
    """,
            border_style="cyan",
        )
    )
    console.print()

    # Check if already configured
    config = Config()
    if config.is_configured():
        if not Confirm.ask("Configuration already exists. Overwrite?", default=False):
            console.print("[dim]Setup cancelled.[/dim]")
            return

    # Import API key from existing .env if available
    if not config.fallback_api_key:
        console.print("[dim]Looking for GEMINI_API_KEY in .env file...[/dim]")
        api_key = import_env_api_key()
        if api_key:
            config.fallback_api_key = api_key
            console.print("[green]✓ Found GEMINI_API_KEY[/green]")
        else:
            console.print("[yellow]⚠ No GEMINI_API_KEY found in .env[/yellow]")
            api_key = questionary.password("Enter your Gemini API key (or skip):").ask()
            if api_key:
                config.fallback_api_key = api_key

    console.print()

    # Step 1: OAuth Authentication
    from gclaude.auth import init_auth_with_rich_output
    from antigravity_auth import AntigravityAuthManager

    auth_manager = AntigravityAuthManager()

    # Check if account already exists
    if auth_manager.account_count() > 0:
        use_existing = questionary.select(
            "OAuth account found. Use existing account or authenticate new?",
            choices=[
                {"name": "Use existing account", "value": "existing"},
                {"name": "Authenticate new account", "value": "new"},
            ],
        ).ask()

        if use_existing == "existing":
            account = auth_manager.get_available_account()
            console.print(f"[green]✓ Using existing account: {account.email}[/green]")
            config.auth_enabled = True
            config.account_email = account.email
            # Get fresh access token for model detection
            from antigravity_auth import get_valid_access_token

            access_token = asyncio.run(get_valid_access_token(auth_manager))
        else:
            account_info = asyncio.run(init_auth_with_rich_output(console, auth_manager))
            if account_info:
                config.auth_enabled = True
                config.account_email = account_info["email"]
                access_token = account_info["access_token"]
            else:
                console.print("[red]❌ Authentication failed[/red]")
                return
    else:
        do_auth = questionary.confirm(
            "Do you want to authenticate with Google OAuth for Antigravity?"
        ).ask()
        if do_auth:
            account_info = asyncio.run(init_auth_with_rich_output(console, auth_manager))
            if account_info:
                config.auth_enabled = True
                config.account_email = account_info["email"]
                access_token = account_info["access_token"]
            else:
                console.print("[red]❌ Authentication failed[/red]")
                return
        else:
            access_token = None

    console.print()

    # Step 2: Detect Model Access (if authenticated)
    access_results = {}
    if config.auth_enabled and access_token:
        from gclaude.detector import detect_with_rich_output

        console.print(
            Panel.fit(
                "[bold yellow]🔍 Step 2: Detecting your model access[/bold yellow]",
                border_style="yellow",
            )
        )
        console.print()

        # Prefer the discovered Code Assist project id, since model access can be scoped.
        account = auth_manager.get_available_account()
        project_id = getattr(account, "project_id", None) if account else None
        access_results = asyncio.run(
            detect_with_rich_output(access_token, console, project_id=project_id)
        )

        available_count = sum(1 for v in access_results.values() if v)
        console.print()
        console.print(f"[green]Found {available_count} Antigravity model(s) available[/green]")
        console.print()
    else:
        # Set all to false
        for model in get_available_antigravity_models():
            access_results[model["id"]] = False

    # Step 3: Model Mapping Selection
    from gclaude.detector import get_available_models_for_mapping

    console.print(
        Panel.fit(
            "[bold yellow]⚙️  Step 3: Configure model mappings[/bold yellow]",
            border_style="yellow",
        )
    )
    console.print()

    available_models = get_available_models_for_mapping(access_results)

    # Helper to create choices using questionary.Choice for proper default handling
    def get_model_choices(claude_model: str):
        from questionary import Choice

        choices = []
        for model in available_models:
            is_antigravity = model.get("type") == "antigravity"
            is_available = (
                access_results.get(model.get("id", ""), False) if is_antigravity else True
            )

            if not is_available:
                continue

            label = f"{model['name']}"
            if model.get("description"):
                label += f" - {model['description']}"

            if is_antigravity:
                label = "★ " + label  # Mark Antigravity models

            choices.append(Choice(title=label, value=model["id"]))

        # Add skip option (use empty string as value - it's falsy so "if result:" will skip it)
        choices.append(Choice(title="Skip - don't map " + claude_model, value=""))
        return choices

    # Configure each model
    claude_models = [
        ("haiku", "claude-3-5-haiku requests"),
        ("sonnet", "claude-sonnet requests"),
        ("opus", "claude-opus requests"),
    ]

    for name, description in claude_models:
        choices = get_model_choices(name)

        # Default recommendation based on access (use value, not index)
        default = None
        if access_results.get("antigravity-gemini-3-flash") and name == "haiku":
            default = "antigravity-gemini-3-flash"
        elif access_results.get("antigravity-claude-sonnet-4-5-thinking") and name == "sonnet":
            default = "antigravity-claude-sonnet-4-5-thinking"
        elif access_results.get("antigravity-claude-sonnet-4-5") and name == "sonnet":
            default = "antigravity-claude-sonnet-4-5"
        elif access_results.get("antigravity-gemini-3-pro-high") and name == "sonnet":
            default = "antigravity-gemini-3-pro-high"
        elif access_results.get("antigravity-gemini-3-pro-low") and name == "sonnet":
            default = "antigravity-gemini-3-pro-low"
        elif access_results.get("antigravity-claude-opus-4-5-thinking") and name == "opus":
            default = "antigravity-claude-opus-4-5-thinking"

        # With Choice objects, we can use the value directly as default
        # Verify default exists in choices, otherwise use first choice's value
        choice_values = [c.value for c in choices if c.value]  # Exclude empty/None values
        if default and default not in choice_values:
            default = choices[0].value if choices else None

        result = questionary.select(
            f"For {description}, use which model?",
            choices=choices,
            default=default,
        ).ask()

        if result:
            # Determine type
            model_type = "antigravity" if "antigravity" in result else "gemini"
            config.set_model_mapping(name, f"*{name}*", result, model_type)
            console.print(f"[green]✓ {name} → {result}[/green]")
        else:
            console.print(f"[dim]⊘ {name} skipped[/dim]")

    console.print()

    # Step 4: Configuration Summary
    console.print(
        Panel.fit(
            "[bold yellow]📋 Configuration Summary[/bold yellow]",
            border_style="yellow",
        )
    )
    console.print()

    console.print(f"[bold]Proxy Settings:[/bold]")
    console.print(f"  • Host: {config.proxy_host}")
    console.print(f"  • Port: {config.proxy_port}")
    console.print()

    console.print(f"[bold]Model Mappings:[/bold]")
    for name, mapping in config.models.items():
        target = mapping.get("target", "skipped")
        if target == "skipped":
            console.print(f"  • {name}: [dim]skipped[/dim]")
        else:
            model_type = mapping.get("type", "gemini")
            type_color = "cyan" if model_type == "antigravity" else "blue"
            console.print(f"  • {name} → [{type_color}]{target}[/{type_color}]")
    console.print()

    if config.auth_enabled:
        console.print(f"[bold]OAuth:[/bold] [green]✓ Enabled[/green]")
        console.print(f"  • Account: {config.account_email}")
    else:
        console.print(f"[bold]OAuth:[/bold] [dim]Disabled[/dim]")

    console.print()

    # Save configuration
    if Confirm.ask("Save configuration?", default=True):
        config.save()
        console.print("[green]✓ Configuration saved[/green]")

        # Create Claude Code settings file for --settings flag
        claude_settings_path = Path.home() / ".claude" / "antigravity-settings.json"
        claude_settings_path.parent.mkdir(parents=True, exist_ok=True)
        claude_settings = {
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "dummy-key-proxy-handles-auth",
                "ANTHROPIC_BASE_URL": f"http://{config.proxy_host}:{config.proxy_port}",
                "API_TIMEOUT_MS": "3000000",
            }
        }
        with open(claude_settings_path, "w") as f:
            json.dump(claude_settings, f, indent=2)
        console.print(f"[green]✓ Claude settings saved to {claude_settings_path}[/green]")
    else:
        console.print("[dim]Configuration not saved.[/dim]")
        return

    console.print()

    # Step 5: Create alias
    console.print(
        Panel.fit(
            "[bold yellow]🔧 Step 4: Creating gclaude alias[/bold yellow]",
            border_style="yellow",
        )
    )
    console.print()

    create_alias = Confirm.ask("Add gclaude alias to your shell config?", default=True)
    if create_alias:
        rc_path = get_shell_rc_path()
        alias_line = "\n# gclaude alias\nalias gclaude='python -m gclaude'\n"

        try:
            # Check if alias already exists
            existing_content = ""
            if rc_path.exists():
                with open(rc_path, "r") as f:
                    existing_content = f.read()

            if "gclaude" not in existing_content:
                with open(rc_path, "a") as f:
                    f.write(alias_line)
                console.print(f"[green]✓ Alias added to {rc_path}[/green]")
                console.print(f"[dim]Run 'source {rc_path}' to use immediately[/dim]")
            else:
                console.print(f"[dim]Alias already exists in {rc_path}[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not add alias: {e}[/yellow]")

    console.print()
    console.print(
        Panel.fit(
            """[bold green]✅ Setup complete![/bold green]

[bold]Start your proxy:[/bold]
    [cyan]gclaude start[/cyan]

[bold]Check status:[/bold]
    [cyan]gclaude status[/cyan]

[bold]View logs:[/bold]
    [cyan]gclaude logs[/cyan]

[bold]Re-authenticate:[/bold]
    [cyan]gclaude auth[/cyan]
    """,
            border_style="green",
        )
    )


@cli.command()
@click.option("--detached", "-d", is_flag=True, help="Run in background (default)")
def start(detached):
    """Start the proxy server."""
    config = Config()
    server = ProxyServer(config)

    running, pid = server.is_running()
    if running:
        console.print(f"[yellow]Proxy already running (PID: {pid})[/yellow]")
        return

    success, message = server.start()
    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print(
            f"[dim]Proxy running at: http://{config.proxy_host}:{config.proxy_port}[/dim]"
        )
        console.print(f"[dim]Logs: {server.log_path}[/dim]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        raise click.ClickException(1)


@cli.command()
def stop():
    """Stop the proxy server."""
    server = ProxyServer()

    running, pid = server.is_running()
    if not running:
        console.print("[yellow]Proxy is not running[/yellow]")
        return

    success, message = server.stop()
    if success:
        console.print(f"[green]✓ {message}[/green]")
    else:
        console.print(f"[red]✗ {message}[/red]")
        raise click.ClickException(1)


@cli.command()
def restart():
    """Restart the proxy server."""
    config = Config()
    server = ProxyServer(config)

    success, message = server.restart()
    if success:
        console.print(f"[green]✓ {message}[/green]")
        console.print(
            f"[dim]Proxy running at: http://{config.proxy_host}:{config.proxy_port}[/dim]"
        )
    else:
        console.print(f"[red]✗ {message}[/red]")
        raise click.ClickException(1)


@cli.command()
@click.option("--watch", "-w", is_flag=True, help="Watch status in real-time")
def status(watch):
    """Show proxy and auth status."""
    from rich.live import Live
    from time import sleep

    server = ProxyServer()

    def show_status():
        status_dict = server.get_status()
        show_status_rich(console, status_dict)

    if watch:
        try:
            with Live(show_status, refresh_per_second=1) as live:
                while True:
                    show_status()
                    live.update(show_status)
                    sleep(1)
        except KeyboardInterrupt:
            console.print("\n[dim]Status monitoring stopped[/dim]")
    else:
        show_status()


@cli.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--lines", "-n", default=50, help="Number of lines to show")
def logs(follow, lines):
    """Show proxy logs."""
    server = ProxyServer()

    if follow:
        try:
            import subprocess

            # Use tail -f to follow logs
            if not server.log_path.exists():
                console.print(f"[yellow]Log file not found: {server.log_path}[/yellow]")
                return

            console.print(f"[dim]Following logs: {server.log_path}[/dim]")
            console.print("[dim]Press Ctrl+C to stop[/dim]")
            console.print()

            subprocess.run(["tail", "-f", str(server.log_path)])
        except KeyboardInterrupt:
            console.print("\n[dim]Log monitoring stopped[/dim]")
    else:
        log_lines = server.tail_logs(lines)
        for line in log_lines:
            console.print(line, end="")


@cli.command()
def auth():
    """Authenticate or re-authenticate with Google OAuth."""
    from gclaude.auth import init_auth_with_rich_output, list_accounts
    from antigravity_auth import AntigravityAuthManager
    import questionary

    auth_manager = AntigravityAuthManager()

    # Show existing accounts
    console.print()
    console.print("[bold]Existing Antigravity accounts:[/bold]")
    list_accounts(console)

    action = questionary.select(
        "What would you like to do?",
        choices=[
            {"name": "Add a new account", "value": "add"},
            {"name": "List existing accounts", "value": "list"},
            {"name": "Remove an account", "value": "remove"},
            {"name": "Cancel", "value": "cancel"},
        ],
    ).ask()

    if action == "add":
        account_info = asyncio.run(init_auth_with_rich_output(console, auth_manager))
        if account_info:
            # Update config
            config = Config()
            if not config.auth_enabled:
                config.auth_enabled = True
            config.account_email = account_info["email"]
            config.save()
            console.print("[green]✓ Configuration updated[/green]")
        else:
            console.print("[red]❌ Authentication failed[/red]")

    elif action == "remove":
        accounts = auth_manager.get_all_accounts()
        if not accounts:
            console.print("[yellow]No accounts to remove[/yellow]")
            return

        choices = [{"name": acc.email, "value": acc.email} for acc in accounts]
        to_remove = questionary.select(
            "Select account to remove:",
            choices=choices,
        ).ask()

        if to_remove:
            # Find account_id
            for acc in accounts:
                if acc.email == to_remove:
                    auth_manager.remove_account(acc.account_id)
                    console.print(f"[green]✓ Removed account: {to_remove}[/green]")
                    break

    elif action == "list":
        list_accounts(console)


@cli.command()
def config():
    """View or edit configuration."""
    from rich.json import JSON

    config = Config()
    config_dict = config.to_dict()

    # Mask sensitive values
    if config_dict.get("fallback_api_key"):
        key = config_dict["fallback_api_key"]
        config_dict["fallback_api_key"] = key[:8] + "..." if len(key) > 8 else "***"

    console.print()
    console.print(
        Panel(JSON(json.dumps(config_dict, indent=2)), title="[bold]Configuration[/bold]")
    )

    console.print()
    console.print("[dim]Config file:[/dim]", get_config_path())


def _get_antigravity_model_choices(*, include_ids: bool = True):
    """Build questionary choices for Antigravity models."""
    from questionary import Choice

    choices: list[Choice] = []
    for model in get_available_antigravity_models():
        label = f"{model['name']}"
        if include_ids:
            label += f" ({model['id']})"
        if model.get("description"):
            label += f" - {model['description']}"
        choices.append(Choice(title=label, value=model["id"]))

    return choices


@cli.command("models")
@click.option("--include-ids/--no-include-ids", default=True, help="Show model ids")
def list_models(include_ids: bool):
    """List available Antigravity model ids you can map to."""
    console.print()
    console.print("[bold]Antigravity models (pick these for haiku/sonnet/opus mapping):[/bold]")
    for model in get_available_antigravity_models():
        line = f"- {model['name']}"
        if include_ids:
            line += f"  [dim]{model['id']}[/dim]"
        if model.get("description"):
            line += f"  — {model['description']}"
        console.print(line)


@cli.command("set-model")
@click.option(
    "--only",
    type=click.Choice(["haiku", "sonnet", "opus", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Which mapping(s) to update",
)
@click.option(
    "--detect/--no-detect",
    default=True,
    show_default=True,
    help="Detect which Antigravity models your account can access",
)
def set_model(only: str, detect: bool):
    """Guided update of model mappings (one-by-one)."""
    import questionary

    config = Config()

    if not config.auth_enabled:
        raise click.ClickException(
            "OAuth is not enabled. Run 'gclaude auth' or 'gclaude init' first."
        )

    claude_models = [
        ("haiku", "claude-haiku requests"),
        ("sonnet", "claude-sonnet requests"),
        ("opus", "claude-opus requests"),
    ]

    if only != "all":
        claude_models = [m for m in claude_models if m[0] == only]

    access_results = None
    if detect:
        try:
            from antigravity_auth import AntigravityAuthManager, get_valid_access_token
            from gclaude.detector import detect_with_rich_output

            auth_manager = AntigravityAuthManager()
            access_token = asyncio.run(get_valid_access_token(auth_manager))
            if access_token:
                console.print()
                console.print("[dim]Detecting available Antigravity models...[/dim]")

                # Prefer the discovered Code Assist project id, since model access can be scoped.
                account = auth_manager.get_available_account()
                project_id = getattr(account, "project_id", None) if account else None
                access_results = asyncio.run(
                    detect_with_rich_output(access_token, console, project_id=project_id)
                )
            else:
                console.print("[yellow]⚠ Could not get access token; showing all models[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠ Model detection failed; showing all models: {e}[/yellow]")
            access_results = None

    # If we detected access, filter choices to only those marked available
    if access_results is not None:
        from questionary import Choice

        choices = []
        for model in get_available_antigravity_models():
            if access_results.get(model["id"], False):
                label = f"{model['name']} ({model['id']})"
                if model.get("description"):
                    label += f" - {model['description']}"
                choices.append(Choice(title=label, value=model["id"]))
    else:
        choices = _get_antigravity_model_choices(include_ids=True)

    console.print()
    console.print("[bold]Select target models:[/bold]")

    for name, description in claude_models:
        current = config.models.get(name, {}).get("target")
        default_value = current if current in [c.value for c in choices] else None

        selected = questionary.select(
            f"For {description}, use which Antigravity model?",
            choices=choices,
            default=default_value,
        ).ask()

        if not selected:
            continue

        config.set_model_mapping(name, f"*{name}*", selected, "antigravity")
        console.print(f"[green]✓ {name} → {selected}[/green]")

    console.print()
    config.save()
    console.print("[green]✓ Configuration saved[/green]")
    console.print("[yellow]Next step:[/yellow] restart proxy to apply changes")
    console.print("  [cyan]gclaude restart[/cyan]")
    console.print("[dim]Then verify routes with: gclaude status[/dim]")


@cli.command()
@click.option("--local", is_flag=True, help="Install in editable mode")
def update(local):
    """Update gclaude to the latest version."""
    import subprocess

    console.print("[dim]Checking for updates...[/dim]")

    try:
        if local:
            console.print("[dim]Installing in editable mode...[/dim]")
            subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."])
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "gclaude"])

        console.print("[green]✓ gclaude updated![/green]")
        console.print("[dim]Run '[bold]gclaude --version[/bold]' to verify.[/dim]")
    except Exception as e:
        console.print(f"[red]✗ Update failed: {e}[/red]")
        raise click.ClickException(1)


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
