"""
OAuth authentication with rich terminal output.

Provides a guided OAuth flow for Antigravity authentication.
"""

import asyncio
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from gclaude.utils import get_config_dir

try:
    from gclaude.proxy.antigravity_auth import (
        perform_oauth_flow,
        exchange_code_for_tokens,
        AntigravityAuthManager,
        authenticate_and_store,
        ACCOUNTS_PATH,
    )
except ImportError:
    ACCOUNTS_PATH = Path.home() / ".config" / "gclaude" / "antigravity-accounts.json"


async def authenticate_with_rich_output(console: Console, client_id: Optional[str] = None) -> Optional[dict]:
    """
    Perform OAuth authentication with rich terminal output.

    Args:
        console: Rich console instance
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        Token dict or None if failed
    """
    from gclaude.proxy.antigravity_auth import perform_oauth_flow, exchange_code_for_tokens
    import aiohttp

    console.print()
    console.print(Panel.fit(
        "[bold yellow]🔐 Step 1: Authenticate with Google[/bold yellow]",
        border_style="yellow",
    ))
    console.print()

    console.print("[dim]Opening browser for authentication...[/dim]")
    console.print("[dim]If browser doesn't open, visit the URL manually.[/dim]")
    console.print()

    # Perform OAuth flow
    oauth_result = perform_oauth_flow(client_id=client_id)

    if not oauth_result:
        console.print("[red]❌ Authentication failed - no authorization code received[/red]")
        return None

    # Exchange code for tokens
    with console.status("[bold yellow]Exchanging authorization code for tokens...[/bold yellow]"):
        try:
            tokens = await exchange_code_for_tokens(
                oauth_result["authorization_code"],
                oauth_result["code_verifier"],
                client_id=client_id
            )
        except aiohttp.ClientResponseError as e:
            console.print(f"[red]❌ Token exchange failed: {e}[/red]")
            return None
        except Exception as e:
            console.print(f"[red]❌ Unexpected error: {e}[/red]")
            return None

    # Get user email
    access_token = tokens.get("access_token")
    email = "unknown@antigravity.google.com"

    if access_token:
        with console.status("[bold yellow]Fetching account information...[/bold yellow]"):
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {"Authorization": f"Bearer {access_token}"}
                    async with session.get(
                        "https://www.googleapis.com/oauth2/v2/userinfo",
                        headers=headers
                    ) as response:
                        if response.status == 200:
                            user_info = await response.json()
                            email = user_info.get("email", email)
            except Exception:
                pass

    console.print()
    console.print(f"[green]✅ Authenticated as: {email}[/green]")
    expiry = tokens.get("expires_at", "unknown")
    console.print(f"[dim]Access token expires: {expiry}[/dim]")
    console.print(f"[dim]Tokens stored to: {ACCOUNTS_PATH}[/dim]")

    return {
        "email": email,
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": tokens.get("expires_at", ""),
    }


async def init_auth_with_rich_output(console: Console, auth_manager,
                                    client_id: Optional[str] = None) -> Optional[dict]:
    """
    Initialize authentication and store account.

    Args:
        console: Rich console instance
        auth_manager: AntigravityAuthManager instance
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        Account info dict or None if failed
    """
    from gclaude.proxy.antigravity_auth import AntigravityAccount

    token_data = await authenticate_with_rich_output(console, client_id=client_id)
    if not token_data:
        return None

    # Create and store account
    account = AntigravityAccount(
        email=token_data["email"],
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
    )

    auth_manager.add_account(account)

    console.print(f"[green]✅ Account stored: {token_data['email']}[/green]")
    console.print()

    return {
        "email": token_data["email"],
        "access_token": token_data["access_token"],
    }


def list_accounts(console: Console) -> None:
    """List stored Antigravity accounts."""
    from gclaude.proxy.antigravity_auth import AntigravityAuthManager

    auth_manager = AntigravityAuthManager()
    accounts = auth_manager.get_all_accounts()

    console.print()
    if not accounts:
        console.print("[yellow]No Antigravity accounts found.[/yellow]")
        console.print("[dim]Run '[bold]gclaude auth[/bold]' to authenticate.[/dim]")
        return

    console.print(f"[green]Found {len(accounts)} Antigravity account(s):[/green]")
    console.print()

    for i, account in enumerate(accounts, 1):
        is_expired = " [red](expired)[/red]" if account.is_expired else " [green](valid)[/green]"
        console.print(f"  {i}. {account.email}{is_expired}")

    console.print()


async def refresh_tokens(console: Console, auth_manager) -> bool:
    """
    Refresh tokens for all accounts.

    Args:
        console: Rich console instance
        auth_manager: AntigravityAuthManager instance

    Returns:
        True if successful, False otherwise
    """
    from gclaude.proxy.antigravity_auth import get_valid_access_token, AntigravityAccount

    console.print("[dim]Refreshing access tokens...[/dim]")

    accounts = auth_manager.get_all_accounts()
    refreshed = 0

    for account in accounts:
        if account.is_expired:
            from gclaude.proxy.antigravity_auth import refresh_access_token
            try:
                new_tokens = await refresh_access_token(account.refresh_token)
                account.access_token = new_tokens.get("access_token", account.access_token)
                account.expires_at = new_tokens.get("expires_at", account.expires_at)

                if "refresh_token" in new_tokens:
                    account.refresh_token = new_tokens["refresh_token"]

                auth_manager.add_account(account)
                refreshed += 1
            except Exception as e:
                console.print(f"[red]Failed to refresh token for {account.email}: {e}[/red]")

    if refreshed > 0:
        console.print(f"[green]✅ Refreshed {refreshed} token(s)[/green]")
        return True
    else:
        console.print("[dim]All tokens are valid.[/dim]")
        return True
