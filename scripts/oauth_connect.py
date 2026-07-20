#!/usr/bin/env python3
"""
OAuth 2.0 connection script for LinkedIn Company Page (org scopes).

Usage:
    1. LinkedIn app with Community Management / org social products approved
    2. Set LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET
    3. python scripts/oauth_connect.py
    4. Use token.json as credentials_path for MCP tools

Uses loopback redirect http://127.0.0.1:8766/callback (8766 avoids clash with linkedin-mcp).
"""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import requests
except ImportError:
    print("Error: pip install requests")
    sys.exit(1)

DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "r_organization_social",
    "w_organization_social",
    "rw_organization_admin",
]
TOKEN_FILE = ROOT / "token.json"
CREDENTIALS_FILE = ROOT / "credentials.json"
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8766
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"

_auth_code: dict = {}


def _load_client() -> tuple[str, str]:
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "").strip()
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip()
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            data = json.load(f)
        client = data.get("web") or data.get("installed") or data
        client_id = client_id or client.get("client_id", "")
        client_secret = client_secret or client.get("client_secret", "")
    return client_id, client_secret


def _scopes() -> list[str]:
    raw = os.environ.get("LINKEDIN_CORP_OAUTH_SCOPES", "").strip()
    if not raw:
        raw = os.environ.get("LINKEDIN_OAUTH_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_SCOPES)
    return [s for s in raw.replace(",", " ").split() if s]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        if "error" in qs:
            _auth_code["error"] = qs["error"][0]
        elif "code" in qs:
            _auth_code["code"] = qs["code"][0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><p>LinkedIn Corp OAuth complete. Close this tab.</p></body></html>")

    def log_message(self, format, *args):  # noqa: A003
        return


def main() -> None:
    client_id, client_secret = _load_client()
    if not client_id or not client_secret:
        print("Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET (or credentials.json)")
        sys.exit(1)

    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(_scopes()),
    }
    auth_url = AUTH_URL + "?" + urlencode(params)
    print(f"Redirect URI (add to LinkedIn app): {REDIRECT_URI}")
    print(f"Scopes: {' '.join(_scopes())}")
    print("Opening browser...")
    webbrowser.open(auth_url)

    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _Handler)
    while "code" not in _auth_code and "error" not in _auth_code:
        server.handle_request()

    if _auth_code.get("error"):
        print(f"OAuth error: {_auth_code['error']}")
        sys.exit(1)

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _auth_code["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    token_data = resp.json()

    payload = {
        "type": "oauth",
        "access_token": token_data.get("access_token"),
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": TOKEN_URL,
        "client_id": client_id,
        "scopes": _scopes(),
        "expires_at": int(__import__("time").time()) + int(token_data.get("expires_in", 0))
        if token_data.get("expires_in")
        else None,
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {TOKEN_FILE}")


if __name__ == "__main__":
    main()
