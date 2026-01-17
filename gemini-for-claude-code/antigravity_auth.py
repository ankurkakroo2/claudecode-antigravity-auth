"""
Antigravity Authentication Module

Implements OAuth 2.0 with PKCE for Google authentication to access
Antigravity's Google AI subscription models.

Token storage: ~/.config/gclaude/antigravity-accounts.json
"""

import os
import json
import base64
import hashlib
import secrets
import webbrowser
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import http.server
import socketserver
import threading
from urllib.parse import urlencode

# Google OAuth configuration
GOOGLE_OAUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Client ID and secret - can be set via environment variable
# Default is from opencode-antigravity-auth project
# To get your own: https://console.cloud.google.com/apis/credentials
ANTIGRAVITY_CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_CLIENT_ID",
    "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
)
ANTIGRAVITY_CLIENT_SECRET = os.environ.get(
    "ANTIGRAVITY_CLIENT_SECRET",
    "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"
)
ANTIGRAVITY_REDIRECT_URI = "http://localhost:51121/oauth-callback"

# OAuth scopes required for Antigravity
ANTIGRAVITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

# Antigravity endpoints for project ID discovery (prefer prod for managed project resolution)
ANTIGRAVITY_LOAD_ENDPOINTS = [
    "https://cloudcode-pa.googleapis.com",
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
    "https://autopush-cloudcode-pa.sandbox.googleapis.com",
]

# Default project ID (fallback)
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

# Token storage path
ACCOUNTS_PATH = Path.home() / ".config" / "gclaude" / "antigravity-accounts.json"


class OAuthCallbackHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler to capture OAuth callback."""

    def __init__(self, *args, auth_code_holder: List[str], **kwargs):
        self.auth_code_holder = auth_code_holder
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path.startswith("/oauth-callback"):
            # Extract authorization code from URL
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            params = dict(param.split("=") for param in query.split("&") if "=" in param)
            code = params.get("code")

            if code:
                self.auth_code_holder[0] = code
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Authentication successful!</h1><p>You can close this window and return to the terminal.</p></body></html>")
            else:
                error = params.get("error", "unknown")
                self.send_response(400)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(f"<html><body><h1>Authentication failed</h1><p>Error: {error}</p></body></html>".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs


def generate_pkce_verifier_and_challenge() -> tuple[str, str]:
    """
    Generate PKCE code verifier and challenge.

    Returns:
        tuple: (code_verifier, code_challenge)
    """
    # Generate a random code verifier (43-128 chars)
    code_verifier = secrets.token_urlsafe(32)

    # Create code challenge by SHA256 hashing and base64url encoding
    challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode().rstrip("=")

    return code_verifier, code_challenge


def build_authorization_url(code_challenge: str, state: Optional[str] = None, client_id: Optional[str] = None) -> str:
    """
    Build the Google OAuth authorization URL with PKCE.

    Args:
        code_challenge: PKCE code challenge
        state: Optional state parameter for CSRF protection
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        str: The authorization URL

    Raises:
        ValueError: If no client_id is available
    """
    # Use the provided client_id, otherwise fall back to environment variable
    effective_client_id = client_id or ANTIGRAVITY_CLIENT_ID

    if not effective_client_id:
        raise ValueError(
            "No OAuth client_id configured. Please set the ANTIGRAVITY_CLIENT_ID environment variable "
            "or pass a client_id parameter. Create one at: "
            "https://console.cloud.google.com/apis/credentials"
        )

    if state is None:
        state = secrets.token_urlsafe(16)

    params = {
        "client_id": effective_client_id,
        "redirect_uri": ANTIGRAVITY_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(ANTIGRAVITY_SCOPES),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",  # Request refresh token
        "prompt": "consent",  # Force consent to get refresh token
    }

    param_str = urlencode(params)
    return f"{GOOGLE_OAUTH_ENDPOINT}?{param_str}"


async def exchange_code_for_tokens(authorization_code: str, code_verifier: str,
                                   client_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        authorization_code: The authorization code from the callback
        code_verifier: The PKCE code verifier
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        dict: Token response containing access_token, refresh_token, expiry, etc.

    Raises:
        ValueError: If no client_id is available
    """
    import aiohttp

    effective_client_id = client_id or ANTIGRAVITY_CLIENT_ID

    if not effective_client_id:
        raise ValueError(
            "No OAuth client_id configured. Please set the ANTIGRAVITY_CLIENT_ID environment variable "
            "or pass a client_id parameter. Create one at: "
            "https://console.cloud.google.com/apis/credentials"
        )

    data = {
        "client_id": effective_client_id,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
        "code": authorization_code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": ANTIGRAVITY_REDIRECT_URI,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(GOOGLE_TOKEN_ENDPOINT, data=data) as response:
            response.raise_for_status()
            tokens = await response.json()

    # Add expiry calculation
    if "expires_in" in tokens:
        expiry_time = datetime.now() + timedelta(seconds=tokens["expires_in"])
        tokens["expires_at"] = expiry_time.isoformat()

    return tokens


async def refresh_access_token(refresh_token: str,
                               client_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Refresh an expired access token using the refresh token.

    Args:
        refresh_token: The refresh token
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        dict: New token response

    Raises:
        ValueError: If no client_id is available
    """
    import aiohttp

    effective_client_id = client_id or ANTIGRAVITY_CLIENT_ID

    if not effective_client_id:
        raise ValueError(
            "No OAuth client_id configured. Please set the ANTIGRAVITY_CLIENT_ID environment variable "
            "or pass a client_id parameter. Create one at: "
            "https://console.cloud.google.com/apis/credentials"
        )

    data = {
        "client_id": effective_client_id,
        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(GOOGLE_TOKEN_ENDPOINT, data=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Token refresh failed: {error_text}")
            tokens = await response.json()

    # Add expiry calculation
    if "expires_in" in tokens:
        expiry_time = datetime.now() + timedelta(seconds=tokens["expires_in"])
        tokens["expires_at"] = expiry_time.isoformat()

    # Preserve refresh token if not returned (Google sometimes doesn't return it)
    if "refresh_token" not in tokens:
        tokens["refresh_token"] = refresh_token

    return tokens


def _extract_managed_project_id(payload: Dict[str, Any]) -> Optional[str]:
    """Extract managed project ID from loadCodeAssist/onboard responses."""
    companion = payload.get("cloudaicompanionProject")
    if isinstance(companion, str):
        return companion
    if isinstance(companion, dict):
        for key in ("id", "projectId"):
            value = companion.get(key)
            if isinstance(value, str) and value:
                return value

    response = payload.get("response")
    if isinstance(response, dict):
        response_companion = response.get("cloudaicompanionProject")
        if isinstance(response_companion, dict):
            for key in ("id", "projectId"):
                value = response_companion.get(key)
                if isinstance(value, str) and value:
                    return value

    return None


async def discover_project_id(access_token: str, project_id_hint: Optional[str] = None) -> Optional[str]:
    """
    Discover the Google Cloud project ID using the loadCodeAssist endpoint.
    Prefers managed project IDs returned by Antigravity when available.

    Args:
        access_token: Valid OAuth access token
        project_id_hint: Optional existing project id to include as duetProject metadata

    Returns:
        Project ID or None if discovery fails
    """
    import aiohttp

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "google-api-nodejs-client/9.15.1",
        "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
        "Client-Metadata": '{"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}',
    }

    metadata = {
        "ideType": "IDE_UNSPECIFIED",
        "platform": "PLATFORM_UNSPECIFIED",
        "pluginType": "GEMINI",
    }
    if project_id_hint:
        metadata["duetProject"] = project_id_hint

    body = {"metadata": metadata}

    # Try each endpoint in order
    for endpoint in ANTIGRAVITY_LOAD_ENDPOINTS:
        try:
            url = f"{endpoint}/v1internal:loadCodeAssist"

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()

                        managed_project_id = _extract_managed_project_id(data)
                        if managed_project_id:
                            return managed_project_id

                        # Alternative: check in other fields
                        if "project" in data:
                            return data["project"]

                        # Check in nested structures
                        if "config" in data and "project" in data["config"]:
                            return data["config"]["project"]

        except Exception as e:
            # Try next endpoint
            continue

    # If all endpoints fail, return None (will use default)
    return None


class AntigravityAccount:
    """Represents a single Antigravity account with OAuth credentials."""

    def __init__(self, email: str, access_token: str, refresh_token: str,
                 expires_at: str, account_id: Optional[str] = None,
                 project_id: Optional[str] = None):
        self.email = email
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.account_id = account_id or email
        self.project_id = project_id or DEFAULT_PROJECT_ID

    @property
    def is_expired(self) -> bool:
        """Check if the access token is expired."""
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            # Add 5 minute buffer
            return datetime.now() >= expiry - timedelta(minutes=5)
        except (ValueError, TypeError):
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "account_id": self.account_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AntigravityAccount":
        return cls(
            email=data.get("email", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=data.get("expires_at", ""),
            account_id=data.get("account_id"),
            project_id=data.get("project_id"),
        )


class AntigravityAuthManager:
    """
    Manages Antigravity OAuth authentication and account storage.
    """

    def __init__(self, accounts_path: Optional[Path] = None):
        self.accounts_path = accounts_path or ACCOUNTS_PATH
        self.accounts: Dict[str, AntigravityAccount] = {}
        self._load_accounts()

    def _load_accounts(self):
        """Load accounts from the JSON storage file."""
        if not self.accounts_path.exists():
            return

        try:
            with open(self.accounts_path, "r") as f:
                data = json.load(f)

            for account_data in data.get("accounts", []):
                account = AntigravityAccount.from_dict(account_data)
                self.accounts[account.account_id] = account

        except (json.JSONDecodeError, KeyError, IOError) as e:
            print(f"Warning: Failed to load accounts: {e}")

    def _save_accounts(self):
        """Save accounts to the JSON storage file."""
        self.accounts_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": "1.0",
            "accounts": [acc.to_dict() for acc in self.accounts.values()],
        }

        with open(self.accounts_path, "w") as f:
            json.dump(data, f, indent=2)

    def add_account(self, account: AntigravityAccount):
        """Add or update an account."""
        self.accounts[account.account_id] = account
        self._save_accounts()

    def remove_account(self, account_id: str) -> bool:
        """Remove an account by ID."""
        if account_id in self.accounts:
            del self.accounts[account_id]
            self._save_accounts()
            return True
        return False

    def get_account(self, account_id: str) -> Optional[AntigravityAccount]:
        """Get an account by ID."""
        return self.accounts.get(account_id)

    def get_all_accounts(self) -> List[AntigravityAccount]:
        """Get all accounts."""
        return list(self.accounts.values())

    def get_available_account(self) -> Optional[AntigravityAccount]:
        """
        Get an available account with a valid (or refreshable) token.
        Returns the first account that can be used.
        """
        for account in self.accounts.values():
            # Account is usable if token is valid or can be refreshed
            if account.refresh_token:
                return account
        return None

    def account_count(self) -> int:
        """Return the number of configured accounts."""
        return len(self.accounts)


async def get_valid_access_token(auth_manager: AntigravityAuthManager,
                                 account_id: Optional[str] = None) -> Optional[str]:
    """
    Get a valid access token, refreshing if necessary.

    Args:
        auth_manager: The auth manager instance
        account_id: Optional specific account ID to use

    Returns:
        str: A valid access token, or None if no accounts available
    """
    account = None

    if account_id:
        account = auth_manager.get_account(account_id)
    else:
        account = auth_manager.get_available_account()

    if not account:
        return None

    # Refresh token if expired
    if account.is_expired:
        try:
            new_tokens = await refresh_access_token(account.refresh_token)
            account.access_token = new_tokens.get("access_token", account.access_token)
            account.expires_at = new_tokens.get("expires_at", account.expires_at)

            # Update refresh token if a new one was provided
            if "refresh_token" in new_tokens:
                account.refresh_token = new_tokens["refresh_token"]

            auth_manager.add_account(account)
            print(f"Refreshed access token for {account.email}")
        except Exception as e:
            print(f"Failed to refresh token for {account.email}: {e}")
            return None

    return account.access_token


def perform_oauth_flow(client_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform the full OAuth flow interactively.

    This function:
    1. Generates PKCE verifier/challenge
    2. Opens browser for user authorization
    3. Starts a local callback server
    4. Exchanges code for tokens
    5. Returns the token response

    Args:
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        dict: Token response or None if failed
    """
    print("Starting Antigravity OAuth authentication flow...")

    # Generate PKCE verifier and challenge
    code_verifier, code_challenge = generate_pkce_verifier_and_challenge()

    # Build authorization URL
    auth_url = build_authorization_url(code_challenge, client_id=client_id)

    # Start callback server in a thread
    auth_code_holder: List[str] = [None]

    class ThreadedHTTPServer(socketserver.TCPServer):
        allow_reuse_address = True

    handler_factory = lambda *args, **kwargs: OAuthCallbackHandler(
        *args, auth_code_holder=auth_code_holder, **kwargs
    )

    with ThreadedHTTPServer(("localhost", 51121), handler_factory) as httpd:
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        # Open browser for authorization
        print(f"\nOpening browser for authentication...")
        print(f"If browser doesn't open, visit this URL manually:")
        print(f"\n{auth_url}\n")

        try:
            webbrowser.open(auth_url)
        except Exception:
            print("Warning: Could not open browser automatically.")

        print("Waiting for authentication callback...")

        # Wait for callback (with timeout)
        for i in range(120):  # 2 minute timeout
            if auth_code_holder[0]:
                break
            import time
            time.sleep(1)
        else:
            print("Timeout waiting for authentication callback.")
            httpd.shutdown()
            return None

        httpd.shutdown()

    authorization_code = auth_code_holder[0]

    if not authorization_code:
        print("Failed to receive authorization code.")
        return None

    # Exchange code for tokens (this needs to be async, caller should handle it)
    return {
        "authorization_code": authorization_code,
        "code_verifier": code_verifier,
    }


async def authenticate_and_store(auth_manager: AntigravityAuthManager,
                                  client_id: Optional[str] = None) -> Optional[AntigravityAccount]:
    """
    Perform OAuth flow and store the resulting account.

    Args:
        auth_manager: The auth manager to store the account in
        client_id: Custom client ID (optional, uses env var if not provided)

    Returns:
        AntigravityAccount: The authenticated account, or None if failed
    """
    import aiohttp

    # Perform OAuth flow
    oauth_result = perform_oauth_flow(client_id=client_id)

    if not oauth_result:
        return None

    # Exchange code for tokens
    try:
        tokens = await exchange_code_for_tokens(
            oauth_result["authorization_code"],
            oauth_result["code_verifier"],
            client_id=client_id
        )
    except Exception as e:
        print(f"Failed to exchange authorization code for tokens: {e}")
        return None

    # Get user email to identify account
    access_token = tokens.get("access_token")
    email = "unknown@antigravity.google.com"

    if access_token:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Authorization": f"Bearer {access_token}"}
                async with session.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                      headers=headers) as response:
                    if response.status == 200:
                        user_info = await response.json()
                        email = user_info.get("email", email)
        except Exception:
            pass  # Use default email if userinfo fetch fails

    # Discover project ID for this account
    project_id = None
    if access_token:
        try:
            print("Discovering Google Cloud project ID...")
            project_id = await discover_project_id(access_token)
            if project_id:
                print(f"✓ Discovered project ID: {project_id}")
            else:
                print(f"⚠ Could not discover project ID, using default: {DEFAULT_PROJECT_ID}")
        except Exception as e:
            print(f"⚠ Project ID discovery failed: {e}")
            print(f"Using default project ID: {DEFAULT_PROJECT_ID}")

    # Create and store account
    account = AntigravityAccount(
        email=email,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
        expires_at=tokens.get("expires_at", ""),
        project_id=project_id,
    )

    auth_manager.add_account(account)

    print(f"\nSuccessfully authenticated account: {email}")
    print(f"Access token expires: {tokens.get('expires_at', 'unknown')}")
    print(f"Account stored to: {auth_manager.accounts_path}")

    return account
