"""
LinkedIn Company Page API wrapper layer.

Organization-scoped operations (Community Management / org social APIs).
Credentials are passed as input — not from environment defaults.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote, urlparse

import requests

from app.core.exceptions import (
    LinkedInError,
    LinkedInValidationError,
    normalize_linkedin_error,
)

DEFAULT_SCOPES = (
    "openid",
    "profile",
    "email",
    "r_organization_social",
    "w_organization_social",
    "rw_organization_admin",
)
ALLOWED_SCOPES = frozenset(DEFAULT_SCOPES)
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com/v2"
USERINFO_URL = f"{API_BASE}/userinfo"
UGC_POSTS_URL = f"{API_BASE}/ugcPosts"
ASSETS_URL = f"{API_BASE}/assets"
ORG_ACLS_URL = f"{API_BASE}/organizationAcls"
ORGANIZATIONS_URL = f"{API_BASE}/organizations"
DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TEXT_CHARS = 3000
DEFAULT_TIMEOUT_SEC = 30
ALLOWED_IMAGE_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)
UPLOAD_HOST_SUFFIXES = (".linkedin.com", ".licdn.com")

_create_events: Dict[str, list] = {}
_admin_org_cache: Dict[str, Set[str]] = {}


def _env(name: str, default: str = "") -> str:
    """Read LINKEDIN_CORP_* with fallback to LINKEDIN_*."""
    corp = os.environ.get(f"LINKEDIN_CORP_{name}", "").strip()
    if corp:
        return corp
    return os.environ.get(f"LINKEDIN_{name}", default).strip()


def _max_image_bytes() -> int:
    raw = _env("MAX_IMAGE_BYTES")
    if not raw:
        return DEFAULT_MAX_IMAGE_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_IMAGE_BYTES


def _max_text_chars() -> int:
    raw = _env("MAX_TEXT_CHARS")
    if not raw:
        return DEFAULT_MAX_TEXT_CHARS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_TEXT_CHARS


def _request_timeout() -> int:
    raw = _env("HTTP_TIMEOUT_SEC")
    if not raw:
        return DEFAULT_TIMEOUT_SEC
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SEC


def _create_rate_limit() -> int:
    raw = _env("CREATE_RATE_LIMIT", "10")
    try:
        return max(0, int(raw))
    except ValueError:
        return 10


def _create_rate_window_sec() -> int:
    raw = _env("CREATE_RATE_WINDOW_SEC", "3600")
    try:
        return max(60, int(raw))
    except ValueError:
        return 3600


def _credentials_dir() -> Path:
    raw = _env("CREDENTIALS_DIR")
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parent.parent.parent


def _is_oauth_creds(creds_dict: dict) -> bool:
    has_access = bool(creds_dict.get("access_token") or creds_dict.get("token"))
    has_refresh = bool(creds_dict.get("refresh_token"))
    return creds_dict.get("type") == "oauth" or has_access or has_refresh


def _resolve_credentials_path(credentials_path: str) -> Path:
    base = _credentials_dir()
    candidate = Path(credentials_path)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise LinkedInError(
            "credentials_path must be under LINKEDIN_CORP_CREDENTIALS_DIR",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
            original_error=e,
        ) from e
    return candidate


def load_credentials_dict(
    credentials_path: Optional[str] = None,
    credentials_json: Optional[str] = None,
) -> dict:
    """Load and validate OAuth credential dict from path or JSON string."""
    creds_dict = None
    try:
        if credentials_json:
            creds_dict = json.loads(credentials_json)
        elif credentials_path:
            path = _resolve_credentials_path(credentials_path)
            if not path.exists():
                raise LinkedInError(
                    f"Credentials file not found: {credentials_path}",
                    error_code="CREDENTIALS_REQUIRED",
                    retryable=False,
                )
            with open(path) as f:
                creds_dict = json.load(f)
    except LinkedInError:
        raise
    except json.JSONDecodeError as e:
        raise LinkedInError(
            "Invalid credentials JSON",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
            original_error=e,
        ) from e
    except OSError as e:
        raise LinkedInError(
            "Unable to read credentials file",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
            original_error=e,
        ) from e

    if not creds_dict or not isinstance(creds_dict, dict):
        raise LinkedInError(
            "Credentials required: provide credentials_path or credentials_json (OAuth token)",
            error_code="CREDENTIALS_REQUIRED",
            retryable=False,
        )

    if not _is_oauth_creds(creds_dict):
        raise LinkedInError(
            "OAuth credentials required. Use Connect with LinkedIn in the test UI "
            "or run scripts/oauth_connect.py to get a token with org scopes.",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
        )

    access = creds_dict.get("access_token") or creds_dict.get("token")
    refresh = creds_dict.get("refresh_token")
    if not access and not refresh:
        raise LinkedInError(
            "OAuth credentials must include access_token (or token), or refresh_token",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
        )

    return creds_dict


def organization_urn_from_id(org_id: str) -> str:
    oid = (org_id or "").strip()
    if not oid:
        raise LinkedInValidationError("organization_id is required")
    if oid.startswith("urn:li:organization:"):
        return oid
    if oid.startswith("urn:li:"):
        raise LinkedInValidationError(
            "organization_id must be a numeric org id or urn:li:organization:..."
        )
    if not oid.isdigit():
        raise LinkedInValidationError("organization_id must be numeric")
    return f"urn:li:organization:{oid}"


def validate_organization_urn(organization_urn: str) -> str:
    urn = (organization_urn or "").strip()
    if not urn.startswith("urn:li:organization:") or urn == "urn:li:organization:":
        raise LinkedInValidationError(
            "organization_urn must be urn:li:organization:<id>"
        )
    suffix = urn.split(":")[-1]
    if not suffix.isdigit():
        raise LinkedInValidationError(
            "organization_urn must end with a numeric organization id"
        )
    return urn


def validate_post_urn(post_urn: str) -> str:
    urn = (post_urn or "").strip()
    if not urn:
        raise LinkedInValidationError("post_urn is required")
    if not (
        urn.startswith("urn:li:ugcPost:")
        or urn.startswith("urn:li:share:")
    ):
        raise LinkedInValidationError(
            "post_urn must be urn:li:ugcPost:... or urn:li:share:..."
        )
    return urn


def encode_urn(urn: str) -> str:
    return quote(urn, safe="")


def normalize_visibility(visibility: Optional[str]) -> str:
    raw = "" if visibility is None else str(visibility).strip()
    if not raw:
        return "PUBLIC"
    value = raw.upper()
    if value not in ("PUBLIC", "CONNECTIONS"):
        raise LinkedInValidationError(
            "visibility must be PUBLIC or CONNECTIONS"
        )
    return value


def validate_article_url(article_url: str) -> str:
    url = (article_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise LinkedInValidationError("article_url must be an https:// URL")
    return url


def validate_upload_url(upload_url: str) -> str:
    parsed = urlparse((upload_url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise LinkedInValidationError("uploadUrl must be https with a host")
    host = parsed.hostname.lower()
    if not any(host == s[1:] or host.endswith(s) for s in UPLOAD_HOST_SUFFIXES):
        if host not in ("linkedin.com", "licdn.com"):
            raise LinkedInValidationError(
                "uploadUrl host is not an allowed LinkedIn media host"
            )
    return upload_url


def validate_oauth_scopes(scopes: Optional[list]) -> list:
    if not scopes:
        return list(DEFAULT_SCOPES)
    normalized = [str(s).strip() for s in scopes if str(s).strip()]
    unknown = [s for s in normalized if s not in ALLOWED_SCOPES]
    if unknown:
        raise LinkedInValidationError(
            f"Unsupported OAuth scopes for linkedin-corp-mcp: {', '.join(unknown)}. "
            f"Allowed: {' '.join(DEFAULT_SCOPES)}"
        )
    return normalized


def _parse_expires_at(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        exp = float(value)
        return exp / 1000.0 if exp >= 1e12 else exp
    text = str(value).strip()
    try:
        exp = float(text)
        return exp / 1000.0 if exp >= 1e12 else exp
    except ValueError:
        pass
    try:
        from datetime import datetime

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception as e:
        raise LinkedInError(
            "expires_at/expiry is not a parseable timestamp",
            error_code="INVALID_CREDENTIALS",
            retryable=False,
            original_error=e,
        ) from e


def _extract_org_record(raw: Any) -> Optional[Dict[str, Any]]:
    """Normalize organizationAcls element or organizations lookup hit."""
    if not isinstance(raw, dict):
        return None

    org_urn = None
    org_data: Dict[str, Any] = {}

    if "organization~" in raw:
        expanded = raw.get("organization~") or {}
        org_data = expanded if isinstance(expanded, dict) else {}
        org_id = org_data.get("id")
        if org_id is not None:
            org_urn = organization_urn_from_id(str(org_id))
    elif "organization" in raw:
        org_ref = raw.get("organization")
        if isinstance(org_ref, str):
            org_urn = validate_organization_urn(org_ref)
        elif isinstance(org_ref, dict):
            org_data = org_ref
            org_id = org_data.get("id")
            if org_id is not None:
                org_urn = organization_urn_from_id(str(org_id))
    elif raw.get("id") is not None:
        org_data = raw
        org_urn = organization_urn_from_id(str(raw["id"]))

    if not org_urn:
        return None

    localized = org_data.get("localizedName") or org_data.get("name")
    if isinstance(localized, dict):
        localized = localized.get("localized") or next(iter(localized.values()), None)

    return {
        "organization_urn": org_urn,
        "organization_id": org_urn.split(":")[-1],
        "name": localized,
        "vanity_name": org_data.get("vanityName"),
        "role": raw.get("role"),
        "state": raw.get("state"),
        "content_trust": "untrusted",
    }


class LinkedInCorpService:
    """LinkedIn REST client for Company Page / organization social APIs."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        credentials_json: Optional[str] = None,
    ):
        self._creds = load_credentials_dict(credentials_path, credentials_json)
        self._access_token = self._ensure_access_token()
        self._token_fp = hashlib.sha256(self._access_token.encode("utf-8")).hexdigest()[
            :16
        ]

    def _client_id_secret(self) -> tuple[str, str]:
        client_id = (self._creds.get("client_id") or _env("CLIENT_ID")).strip()
        client_secret = (
            self._creds.get("client_secret") or _env("CLIENT_SECRET")
        ).strip()
        return client_id, client_secret

    def _ensure_access_token(self) -> str:
        token = self._creds.get("access_token") or self._creds.get("token")
        expires_at = _parse_expires_at(
            self._creds.get("expires_at") or self._creds.get("expiry")
        )
        needs_refresh = False
        if not token:
            needs_refresh = True
        elif expires_at is not None:
            needs_refresh = time.time() >= (expires_at - 60)

        if needs_refresh:
            token = self._refresh_access_token()
        if not token:
            raise LinkedInError(
                "No usable access token",
                error_code="AUTH_ERROR",
                retryable=True,
            )
        return token

    def _refresh_access_token(self) -> str:
        refresh = self._creds.get("refresh_token")
        client_id, client_secret = self._client_id_secret()
        if not (refresh and client_id and client_secret):
            raise LinkedInError(
                "Access token expired and refresh_token/client credentials missing",
                error_code="AUTH_ERROR",
                retryable=True,
            )
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_request_timeout(),
            )
            if resp.status_code >= 400:
                raise LinkedInError(
                    "Token refresh failed",
                    error_code="AUTH_ERROR",
                    retryable=True,
                    original_error=f"HTTP {resp.status_code}",
                )
            data = resp.json()
        except LinkedInError:
            raise
        except Exception as e:
            raise normalize_linkedin_error(e) from e

        access = data.get("access_token")
        if not access:
            raise LinkedInError(
                "Token refresh returned no access_token",
                error_code="AUTH_ERROR",
                retryable=True,
            )
        self._creds["access_token"] = access
        self._creds["token"] = access
        if data.get("refresh_token"):
            self._creds["refresh_token"] = data["refresh_token"]
        expires_in = data.get("expires_in")
        if expires_in:
            self._creds["expires_at"] = int(time.time()) + int(expires_in)
        return access

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        version = _env("API_VERSION")
        if version:
            headers["LinkedIn-Version"] = version
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(headers),
                json=json_body,
                data=data,
                timeout=_request_timeout(),
            )
        except Exception as e:
            raise normalize_linkedin_error(e) from e

        if resp.status_code >= 400:
            raise normalize_linkedin_error(
                Exception(f"HTTP {resp.status_code}"),
                status_code=resp.status_code,
            )

        restli_id = (
            resp.headers.get("x-restli-id")
            or resp.headers.get("X-RestLi-Id")
            or resp.headers.get("x-linkedin-id")
        )

        if resp.status_code == 204 or not resp.content:
            return {"id": restli_id} if restli_id else {}

        content_type = (resp.headers.get("Content-Type") or "").lower()
        payload: Any
        if "application/json" in content_type:
            payload = resp.json()
        else:
            text = resp.text.strip()
            if text.startswith("{"):
                payload = resp.json()
            elif text:
                payload = {"id": text}
            else:
                payload = {}

        if isinstance(payload, dict) and restli_id and not payload.get("id"):
            payload["id"] = restli_id
        return payload

    def _throttle_create(self) -> None:
        limit = _create_rate_limit()
        if limit <= 0:
            return
        window = _create_rate_window_sec()
        now = time.time()
        events = _create_events.setdefault(self._token_fp, [])
        events[:] = [t for t in events if now - t < window]
        if len(events) >= limit:
            raise LinkedInError(
                f"Local create rate limit exceeded ({limit}/{window}s). "
                "Set LINKEDIN_CORP_CREATE_RATE_LIMIT=0 to disable (not recommended).",
                error_code="RATE_LIMIT",
                retryable=True,
            )
        events.append(now)

    def get_me(self) -> Dict[str, Any]:
        """Return OpenID userinfo for the authenticated member (operator context)."""
        data = self._request("GET", USERINFO_URL)
        sub = data.get("sub") or data.get("id")
        return {
            "sub": sub,
            "person_urn": f"urn:li:person:{sub}" if sub else None,
            "name": data.get("name"),
            "given_name": data.get("given_name"),
            "family_name": data.get("family_name"),
            "email": data.get("email"),
            "email_verified": data.get("email_verified"),
            "picture": data.get("picture"),
            "locale": data.get("locale"),
            "content_trust": "untrusted",
        }

    def list_my_organizations(self) -> List[Dict[str, Any]]:
        """List Company Pages the member can administer."""
        projection = quote(
            "(elements*(organization~(id,localizedName,vanityName),role,state))"
        )
        url = (
            f"{ORG_ACLS_URL}?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED"
            f"&projection={projection}"
        )
        data = self._request("GET", url)
        elements = data.get("elements") if isinstance(data, dict) else []
        if not isinstance(elements, list):
            elements = []

        orgs: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        for element in elements:
            record = _extract_org_record(element)
            if not record:
                continue
            urn = record["organization_urn"]
            if urn in seen:
                continue
            seen.add(urn)
            orgs.append(record)

        _admin_org_cache[self._token_fp] = seen
        return orgs

    def _admin_organization_urns(self) -> Set[str]:
        cached = _admin_org_cache.get(self._token_fp)
        if cached is not None:
            return cached
        orgs = self.list_my_organizations()
        return {o["organization_urn"] for o in orgs}

    def _resolve_organization_author(self, organization_urn: str) -> str:
        urn = validate_organization_urn(organization_urn)
        administered = self._admin_organization_urns()
        if urn not in administered:
            raise LinkedInValidationError(
                "organization_urn must be a Company Page you administer "
                "(see list_my_organizations)"
            )
        return urn

    def get_organization(
        self,
        *,
        organization_id: Optional[str] = None,
        vanity_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch organization metadata by numeric id or vanity name."""
        if organization_id and vanity_name:
            raise LinkedInValidationError(
                "Provide organization_id or vanity_name, not both"
            )
        if not organization_id and not vanity_name:
            raise LinkedInValidationError(
                "organization_id or vanity_name is required"
            )

        if organization_id:
            org_urn = organization_urn_from_id(organization_id)
            url = f"{ORGANIZATIONS_URL}/{org_urn.split(':')[-1]}"
            data = self._request("GET", url)
            record = _extract_org_record(data if isinstance(data, dict) else {})
            if not record:
                record = {
                    "organization_urn": org_urn,
                    "organization_id": org_urn.split(":")[-1],
                    "content_trust": "untrusted",
                    **(data if isinstance(data, dict) else {}),
                }
            return record

        vanity = (vanity_name or "").strip().lower()
        if not vanity:
            raise LinkedInValidationError("vanity_name is required")
        url = f"{ORGANIZATIONS_URL}?q=vanityName&vanityName={quote(vanity)}"
        data = self._request("GET", url)
        elements = data.get("elements") if isinstance(data, dict) else []
        if not elements:
            raise LinkedInError(
                f"No organization found for vanity_name={vanity}",
                error_code="NOT_FOUND",
                retryable=False,
            )
        record = _extract_org_record(elements[0])
        if not record:
            raise LinkedInError(
                "Organization lookup returned unexpected payload",
                error_code="PROVIDER_ERROR",
                retryable=True,
            )
        return record

    def create_text_post(
        self,
        organization_urn: str,
        text: str,
        *,
        visibility: str = "PUBLIC",
        article_url: Optional[str] = None,
        article_title: Optional[str] = None,
        article_description: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Create a Company Page feed share (text or article URL)."""
        commentary = (text or "").strip()
        if not commentary and not article_url:
            raise LinkedInValidationError("text or article_url is required")
        if len(commentary) > _max_text_chars():
            raise LinkedInValidationError(
                f"text exceeds LINKEDIN_CORP_MAX_TEXT_CHARS ({_max_text_chars()})"
            )

        vis = normalize_visibility(visibility)
        resolved_author = self._resolve_organization_author(organization_urn)

        share_content: Dict[str, Any] = {
            "shareCommentary": {"text": commentary},
            "shareMediaCategory": "NONE",
        }
        if article_url:
            media_item: Dict[str, Any] = {
                "status": "READY",
                "originalUrl": validate_article_url(article_url),
            }
            if article_title:
                media_item["title"] = {"text": article_title.strip()}
            if article_description:
                media_item["description"] = {"text": article_description.strip()}
            share_content["shareMediaCategory"] = "ARTICLE"
            share_content["media"] = [media_item]

        body = {
            "author": resolved_author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": share_content,
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": vis,
            },
        }
        if dry_run:
            return {
                "dry_run": True,
                "request_body": body,
                "organization_urn": resolved_author,
                "visibility": vis,
            }

        self._throttle_create()
        result = self._request("POST", UGC_POSTS_URL, json_body=body)
        post_urn = result.get("id")
        if not post_urn:
            raise LinkedInError(
                "LinkedIn create succeeded but returned no post id",
                error_code="PROVIDER_ERROR",
                retryable=True,
                original_error=result,
            )
        return {
            "post_id": post_urn,
            "post_urn": post_urn,
            "organization_urn": resolved_author,
            "visibility": vis,
        }

    def create_image_post(
        self,
        organization_urn: str,
        text: str,
        *,
        image_base64: str,
        image_media_type: str = "image/jpeg",
        visibility: str = "PUBLIC",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Register upload, push image bytes, then create an org IMAGE share."""
        commentary = (text or "").strip()
        if len(commentary) > _max_text_chars():
            raise LinkedInValidationError(
                f"text exceeds LINKEDIN_CORP_MAX_TEXT_CHARS ({_max_text_chars()})"
            )
        if not image_base64 or not str(image_base64).strip():
            raise LinkedInValidationError("image_base64 is required")

        media_type = (image_media_type or "image/jpeg").strip().lower()
        if media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
            raise LinkedInValidationError(
                "image_media_type must be one of: "
                + ", ".join(sorted(ALLOWED_IMAGE_MEDIA_TYPES))
            )

        try:
            raw = base64.b64decode(image_base64, validate=False)
        except Exception as e:
            raise LinkedInValidationError(
                "image_base64 is not valid base64",
                original_error=e,
            ) from e

        if len(raw) == 0:
            raise LinkedInValidationError("image_base64 decoded to empty bytes")

        max_bytes = _max_image_bytes()
        if len(raw) > max_bytes:
            raise LinkedInValidationError(
                f"image exceeds LINKEDIN_CORP_MAX_IMAGE_BYTES ({max_bytes})"
            )

        vis = normalize_visibility(visibility)
        resolved_author = self._resolve_organization_author(organization_urn)

        if dry_run:
            return {
                "dry_run": True,
                "organization_urn": resolved_author,
                "visibility": vis,
                "image_bytes": len(raw),
                "image_media_type": media_type,
            }

        self._throttle_create()
        register_body = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": resolved_author,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        register = self._request(
            "POST",
            f"{ASSETS_URL}?action=registerUpload",
            json_body=register_body,
        )
        value = register.get("value") or {}
        upload_mech = (
            (value.get("uploadMechanism") or {})
            .get("com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest")
            or {}
        )
        upload_url = upload_mech.get("uploadUrl")
        asset = value.get("asset")
        if not upload_url or not asset:
            raise LinkedInError(
                "Image upload registration did not return uploadUrl/asset",
                error_code="PROVIDER_ERROR",
                retryable=True,
            )

        safe_upload_url = validate_upload_url(upload_url)
        try:
            upload_resp = requests.put(
                safe_upload_url,
                data=raw,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": media_type,
                },
                timeout=_request_timeout(),
                allow_redirects=False,
            )
        except Exception as e:
            raise normalize_linkedin_error(e) from e
        if upload_resp.status_code < 200 or upload_resp.status_code >= 300:
            raise normalize_linkedin_error(
                Exception(f"HTTP {upload_resp.status_code}"),
                status_code=upload_resp.status_code,
            )

        body = {
            "author": resolved_author,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": commentary},
                    "shareMediaCategory": "IMAGE",
                    "media": [
                        {
                            "status": "READY",
                            "media": asset,
                            "title": {"text": "Image"},
                        }
                    ],
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": vis,
            },
        }
        result = self._request("POST", UGC_POSTS_URL, json_body=body)
        post_urn = result.get("id")
        if not post_urn:
            raise LinkedInError(
                "LinkedIn create succeeded but returned no post id",
                error_code="PROVIDER_ERROR",
                retryable=True,
            )
        return {
            "post_id": post_urn,
            "post_urn": post_urn,
            "organization_urn": resolved_author,
            "visibility": vis,
            "asset_urn": asset,
        }

    def get_post(self, post_urn: str) -> Dict[str, Any]:
        urn = validate_post_urn(post_urn)
        url = f"{UGC_POSTS_URL}/{encode_urn(urn)}"
        post = self._request("GET", url)
        if isinstance(post, dict):
            post = {**post, "content_trust": "untrusted"}
        return post

    def delete_post(self, post_urn: str) -> None:
        urn = validate_post_urn(post_urn)
        url = f"{UGC_POSTS_URL}/{encode_urn(urn)}"
        self._request("DELETE", url)


def build_org_ugc_text_body(
    organization_urn: str,
    text: str,
    visibility: str = "PUBLIC",
    article_url: Optional[str] = None,
) -> dict:
    """Pure helper for unit tests — shapes an org ugcPosts create body."""
    vis = normalize_visibility(visibility)
    author = validate_organization_urn(organization_urn)
    share_content: Dict[str, Any] = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }
    if article_url:
        share_content["shareMediaCategory"] = "ARTICLE"
        share_content["media"] = [
            {"status": "READY", "originalUrl": validate_article_url(article_url)},
        ]
    return {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content,
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": vis,
        },
    }
