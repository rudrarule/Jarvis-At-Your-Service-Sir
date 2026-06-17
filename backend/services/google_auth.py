"""Google OAuth for J.A.R.V.I.S — supplies a bearer token for the official
Google MCP servers (Gmail / Calendar / Drive at *.mcp.googleapis.com).

Unlike the local stdio MCP servers, the Google servers are remote HTTP endpoints
authenticated with a Google OAuth2 access token in the Authorization header.

Design (matches mcp_client's philosophy):
  * FAIL-OPEN — any error returns None and logs; the caller simply omits the
    Google servers. Startup never breaks.
  * Personal "installed app" flow — on first use, a browser window opens for
    consent; the resulting credentials (incl. a long-lived refresh token) are
    cached to a token file and silently refreshed thereafter.

Setup the user must do once:
  1. Create an OAuth 2.0 Client ID (type: Desktop app) in Google Cloud Console.
  2. Enable the Gmail, Google Calendar, and Google Drive APIs on that project.
  3. Download the client secrets JSON and point GOOGLE_OAUTH_CLIENT_SECRETS at it.

Token-lifetime caveat: Google access tokens last ~1 hour. get_access_token()
refreshes automatically using the stored refresh token, so call it at the moment
you build the MCP client config (mcp_client._server_config). For a process that
stays up for many hours, rebuild the MCP client (or restart) to pick up a fresh
token — the headers passed to MultiServerMCPClient are captured at build time.
"""
from __future__ import annotations

import os

# Scopes must cover the tools the Google MCP servers expose:
#   Gmail:    search/read threads + create drafts        -> gmail.modify
#   Calendar: list/create/update/delete events           -> calendar.events
#   Drive:    search/read/create files                   -> drive
# Override with GOOGLE_OAUTH_SCOPES (space-separated) to tighten/loosen.
_DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive",
]


def _scopes() -> list[str]:
    raw = os.getenv("GOOGLE_OAUTH_SCOPES", "").strip()
    return raw.split() if raw else list(_DEFAULT_SCOPES)


def _client_secrets_path() -> str:
    return os.getenv(
        "GOOGLE_OAUTH_CLIENT_SECRETS",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "google_client_secret.json"),
    )


def _token_path() -> str:
    return os.getenv(
        "GOOGLE_OAUTH_TOKEN_PATH",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "google_token.json"),
    )


def google_configured() -> bool:
    """True if we either have a cached token or client secrets to mint one, or a
    raw token was injected via env. Cheap check — no I/O beyond existence."""
    if os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN"):
        return True
    return os.path.exists(_token_path()) or os.path.exists(_client_secrets_path())


def get_access_token(*, allow_interactive: bool = True) -> str | None:
    """Return a valid Google OAuth2 access token, or None (fail-open).

    Resolution order:
      1. GOOGLE_OAUTH_ACCESS_TOKEN env (escape hatch — bring-your-own token).
      2. Cached credentials in the token file, auto-refreshed if expired.
      3. Interactive consent flow via client secrets (only if allow_interactive).
    """
    # 1. Explicit token override — no library needed.
    raw = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN")
    if raw:
        return raw.strip()

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("[GoogleAuth] google-auth / google-auth-oauthlib not installed; "
              "skipping Google MCP. Add them to requirements.txt.")
        return None

    scopes = _scopes()
    token_path = _token_path()
    creds = None

    # 2. Load cached credentials.
    try:
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, scopes)
    except Exception as exc:
        print(f"[GoogleAuth] Failed to load cached token ({exc}); will re-auth.")
        creds = None

    # Refresh if expired but we hold a refresh token.
    try:
        if creds and not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save(creds, token_path)
    except Exception as exc:
        print(f"[GoogleAuth] Token refresh failed ({exc}); will re-auth if possible.")
        creds = None

    # 3. Interactive consent if we still have nothing usable.
    if not creds or not creds.valid:
        secrets = _client_secrets_path()
        if not os.path.exists(secrets):
            print(f"[GoogleAuth] No valid token and no client secrets at {secrets}; "
                  "skipping Google MCP (fail-open).")
            return None
        if not allow_interactive:
            print("[GoogleAuth] Token invalid and interactive auth disabled; skipping.")
            return None
        try:
            flow = InstalledAppFlow.from_client_secrets_file(secrets, scopes)
            # port=0 lets the OS pick a free port for the local redirect listener.
            creds = flow.run_local_server(port=0)
            _save(creds, token_path)
        except Exception as exc:
            print(f"[GoogleAuth] Interactive OAuth flow failed ({exc}); skipping Google MCP.")
            return None

    return getattr(creds, "token", None)


def _save(creds, token_path: str) -> None:
    try:
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    except Exception as exc:
        print(f"[GoogleAuth] Could not persist token to {token_path}: {exc}")
