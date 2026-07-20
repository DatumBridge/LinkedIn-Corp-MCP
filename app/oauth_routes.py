"""
OAuth 2.0 routes for web-based connection to LinkedIn (Company Page / org scopes).

Local-dev / operator connect flow. Disable by default
(LINKEDIN_CORP_ENABLE_OAUTH_UI=0). Prefer scripts/oauth_connect.py
or Studio-managed credentials when UI is off.
"""

import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

_oauth_tokens: dict[str, dict] = {}
_OAUTH_TTL_SECONDS = 600
_OAUTH_MAX_PENDING = 128

DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "r_organization_social",
    "w_organization_social",
    "rw_organization_admin",
]
ALLOWED_SCOPES = frozenset(DEFAULT_SCOPES)


def _env(name: str, default: str = "") -> str:
    corp = os.environ.get(f"LINKEDIN_CORP_{name}", "").strip()
    if corp:
        return corp
    return os.environ.get(f"LINKEDIN_{name}", default).strip()


def _oauth_ui_enabled() -> bool:
    raw = _env("ENABLE_OAUTH_UI", "0").lower()
    return raw in ("1", "true", "yes", "on")


def _oauth_disabled_response():
    return JSONResponse(
        {
            "error_code": "OAUTH_UI_DISABLED",
            "error_message": (
                "OAuth/test UI disabled. Set LINKEDIN_CORP_ENABLE_OAUTH_UI=1 for local "
                "connect, or use scripts/oauth_connect.py."
            ),
            "retryable": False,
        },
        status_code=404,
    )


def _purge_oauth_state() -> None:
    now = time.time()
    expired = [
        k
        for k, v in _oauth_tokens.items()
        if now - float(v.get("_created_at", now)) > _OAUTH_TTL_SECONDS
    ]
    for k in expired:
        _oauth_tokens.pop(k, None)
    if len(_oauth_tokens) > _OAUTH_MAX_PENDING:
        oldest = sorted(
            _oauth_tokens.items(), key=lambda kv: float(kv[1].get("_created_at", 0))
        )
        for k, _ in oldest[: len(_oauth_tokens) - _OAUTH_MAX_PENDING]:
            _oauth_tokens.pop(k, None)


def _scopes() -> list[str]:
    raw = _env("OAUTH_SCOPES")
    if not raw:
        return list(DEFAULT_SCOPES)
    requested = [s for s in raw.replace(",", " ").split() if s]
    unknown = [s for s in requested if s not in ALLOWED_SCOPES]
    if unknown:
        return list(DEFAULT_SCOPES)
    return requested


def _get_oauth_config() -> tuple[str, str]:
    creds_path = _env("OAUTH_CREDENTIALS") or str(
        Path(__file__).resolve().parent.parent / "credentials.json"
    )
    if os.path.exists(creds_path):
        with open(creds_path) as f:
            data = json.load(f)
        client = data.get("web") or data.get("installed") or data
        client_id = client.get("client_id") or _env("CLIENT_ID")
        client_secret = client.get("client_secret") or _env("CLIENT_SECRET")
        return client_id or "", client_secret or ""
    return _env("CLIENT_ID"), _env("CLIENT_SECRET")


def _get_redirect_uri(request: Request) -> str:
    configured = _env("OAUTH_REDIRECT_URI") or os.environ.get(
        "OAUTH_REDIRECT_URI", ""
    ).strip()
    if configured:
        return configured.rstrip("/")
    raise RuntimeError("OAUTH_REDIRECT_URI is required when OAuth UI is enabled")


def _get_base_url_from_redirect(redirect_uri: str) -> str:
    uri = redirect_uri.rstrip("/")
    return uri.replace("/oauth/callback", "") if "/oauth/callback" in uri else uri


def _secure_cookie(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or "").lower()
    return proto == "https" or request.url.scheme == "https"


async def oauth_start(request: Request):
    if not _oauth_ui_enabled():
        return _oauth_disabled_response()
    _purge_oauth_state()
    client_id, client_secret = _get_oauth_config()
    if not client_id or not client_secret:
        return JSONResponse(
            {
                "error": "OAuth not configured. Add credentials.json "
                "or LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET."
            },
            status_code=500,
        )
    try:
        redirect_uri = _get_redirect_uri(request)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    state = secrets.token_urlsafe(32)
    _oauth_tokens[state] = {
        "status": "pending",
        "_created_at": time.time(),
        "_client_secret": client_secret,
        "_client_id": client_id,
    }
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(_scopes()),
    }
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params)
    response = RedirectResponse(url)
    response.set_cookie(
        "linkedin_corp_oauth_state",
        state,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(request),
        max_age=_OAUTH_TTL_SECONDS,
        path="/oauth",
    )
    return response


async def oauth_callback(request: Request):
    if not _oauth_ui_enabled():
        return _oauth_disabled_response()
    _purge_oauth_state()
    try:
        redirect_uri = _get_redirect_uri(request)
    except RuntimeError:
        return JSONResponse({"error": "OAUTH_REDIRECT_URI required"}, status_code=500)
    base_url = _get_base_url_from_redirect(redirect_uri)
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    cookie_state = request.cookies.get("linkedin_corp_oauth_state")

    if error:
        return RedirectResponse(f"{base_url}/test?oauth_error={error}")
    if not state or not code:
        return RedirectResponse(f"{base_url}/test?oauth_error=missing_params")
    if not cookie_state or cookie_state != state:
        return RedirectResponse(f"{base_url}/test?oauth_error=state_mismatch")
    if state not in _oauth_tokens:
        return RedirectResponse(f"{base_url}/test?oauth_error=invalid_state")

    pending = _oauth_tokens.get(state) or {}
    client_id = pending.get("_client_id") or _get_oauth_config()[0]
    client_secret = pending.get("_client_secret") or _get_oauth_config()[1]
    if not client_id or not client_secret:
        return RedirectResponse(f"{base_url}/test?oauth_error=config")

    try:
        import requests

        body = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except Exception:
        return RedirectResponse(f"{base_url}/test?oauth_error=exchange")

    expires_in = token_data.get("expires_in")
    oauth_creds = {
        "type": "oauth",
        "access_token": token_data.get("access_token"),
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": "https://www.linkedin.com/oauth/v2/accessToken",
        "client_id": client_id,
        "scopes": _scopes(),
        "expires_at": int(time.time()) + int(expires_in) if expires_in else None,
        "_created_at": time.time(),
    }
    _oauth_tokens[state] = oauth_creds
    return RedirectResponse(f"{base_url}/test?oauth={state}")


async def oauth_token(request: Request):
    """One-shot token redeem. Requires matching httpOnly state cookie."""
    if not _oauth_ui_enabled():
        return _oauth_disabled_response()
    _purge_oauth_state()
    state = request.query_params.get("state")
    cookie_state = request.cookies.get("linkedin_corp_oauth_state")
    if not state or state not in _oauth_tokens:
        return JSONResponse({"error": "Invalid or expired state"}, status_code=400)
    if not cookie_state or cookie_state != state:
        return JSONResponse({"error": "OAuth state cookie required"}, status_code=403)
    data = _oauth_tokens.pop(state)
    if data.get("status") == "pending":
        return JSONResponse({"error": "OAuth not complete"}, status_code=400)
    payload = {
        k: v
        for k, v in data.items()
        if not k.startswith("_") and k != "client_secret"
    }
    response = JSONResponse(payload)
    response.delete_cookie("linkedin_corp_oauth_state", path="/oauth")
    return response


async def oauth_info(request: Request):
    if not _oauth_ui_enabled():
        return _oauth_disabled_response()
    try:
        redirect_uri = _get_redirect_uri(request)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(
        {
            "redirect_uri": redirect_uri,
            "scopes": _scopes(),
            "instruction": (
                "Add this EXACT URL to LinkedIn Developer Portal → Auth → "
                "Authorized redirect URLs. Enable products: Sign In with LinkedIn "
                "(OpenID Connect) and Community Management / Marketing Developer "
                "Platform (org social). Set LINKEDIN_CORP_ENABLE_OAUTH_UI=1 only "
                "for local connect."
            ),
        }
    )
