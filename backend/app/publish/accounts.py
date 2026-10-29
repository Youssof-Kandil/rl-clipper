"""Connected YouTube / TikTok accounts: OAuth with the user's own developer apps.

Each user creates their own Google / TikTok app and pastes its keys in Settings, so no
secrets ship with RL Clipper. Tokens are kept in data/accounts.json on this computer.

Both providers redirect back to this app's own server on 127.0.0.1 (Google "Desktop
app" clients and TikTok "Login Kit for Desktop" both allow loopback redirects).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlencode

import httpx

from ..config import DATA_DIR

PLATFORMS = ("youtube", "tiktok")
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
TIMEOUT = httpx.Timeout(30.0, read=120.0)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
YOUTUBE_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube.readonly")
TIKTOK_AUTH = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_REVOKE = "https://open.tiktokapis.com/v2/oauth/revoke/"
TIKTOK_API = "https://open.tiktokapis.com"

_lock = threading.Lock()
# Login attempts in progress: state -> (platform, PKCE verifier, redirect URI, started).
_pending: dict[str, tuple[str, str, str, float]] = {}


class PublishError(RuntimeError):
    """A problem worth showing the user as-is."""


def _client(client: httpx.Client | None):
    """The given client (tests pass a mocked one, left open) or a fresh one."""
    return contextlib.nullcontext(client) if client is not None else httpx.Client(timeout=TIMEOUT)


# ---------------------------------------------------------------- storage

def _load() -> dict:
    try:
        return json.loads(ACCOUNTS_FILE.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    ACCOUNTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACCOUNTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), "utf-8")
    tmp.replace(ACCOUNTS_FILE)


def get(platform: str) -> dict | None:
    with _lock:
        return _load().get(platform)


def _put(platform: str, account: dict | None) -> None:
    with _lock:
        data = _load()
        if account is None:
            data.pop(platform, None)
        else:
            data[platform] = account
        _save(data)


def keys(settings: dict, platform: str) -> tuple[str, str]:
    """(client id/key, client secret) from Settings."""
    if platform == "youtube":
        return str(settings.get("youtube_client_id", "")).strip(), str(settings.get("youtube_client_secret", "")).strip()
    return str(settings.get("tiktok_client_key", "")).strip(), str(settings.get("tiktok_client_secret", "")).strip()


def status(settings: dict) -> dict:
    """For the UI: per platform, whether keys are set and which account is connected."""
    out = {}
    for p in PLATFORMS:
        acc = get(p) or {}
        out[p] = {"configured": all(keys(settings, p)), "connected": bool(acc.get("refresh_token")),
                  "name": acc.get("name", ""), "scope": acc.get("scope", "")}
    out["tiktok"]["direct_post"] = bool(settings.get("tiktok_direct_post"))
    return out


# ---------------------------------------------------------------- OAuth

def tiktok_scopes(settings: dict) -> str:
    scopes = ["user.info.basic", "video.upload"]
    if settings.get("tiktok_direct_post"):
        scopes.append("video.publish")
    return ",".join(scopes)


def pkce(platform: str) -> tuple[str, str]:
    """(verifier, challenge). Google uses the standard base64url S256 challenge; TikTok's
    desktop Login Kit wants the SHA-256 digest hex-encoded."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = digest.hex() if platform == "tiktok" else base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def auth_url(platform: str, settings: dict, redirect_uri: str) -> str:
    client_id, secret = keys(settings, platform)
    if not client_id or not secret:
        raise PublishError(f"Add your {'Google' if platform == 'youtube' else 'TikTok'} app keys in Settings → Accounts first.")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce(platform)
    now = time.time()
    with _lock:
        for s in [s for s, v in _pending.items() if now - v[3] > 900]:
            _pending.pop(s, None)
        _pending[state] = (platform, verifier, redirect_uri, now)
    if platform == "youtube":
        params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                  "scope": " ".join(YOUTUBE_SCOPES), "access_type": "offline", "prompt": "consent",
                  "include_granted_scopes": "true", "state": state, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        return f"{GOOGLE_AUTH}?{urlencode(params)}"
    params = {"client_key": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": tiktok_scopes(settings), "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    return f"{TIKTOK_AUTH}?{urlencode(params)}"


def _token_request(platform: str, settings: dict, form: dict, client: httpx.Client | None = None) -> dict:
    client_id, secret = keys(settings, platform)
    if platform == "youtube":
        url, form = GOOGLE_TOKEN, {"client_id": client_id, "client_secret": secret, **form}
    else:
        url, form = TIKTOK_TOKEN, {"client_key": client_id, "client_secret": secret, **form}
    with _client(client) as c:
        r = c.post(url, data=form, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data and data.get("error") not in ("", None) or "access_token" not in data:
        desc = data.get("error_description") or data.get("error") or r.text[:200]
        raise PublishError(f"{'Google' if platform == 'youtube' else 'TikTok'} sign-in failed: {desc}. "
                           "Check the app keys in Settings → Accounts, then connect again.")
    return data


def _store_tokens(platform: str, data: dict, previous: dict | None = None) -> dict:
    account = dict(previous or {})
    account.update({
        "access_token": data["access_token"],
        "expires_at": time.time() + float(data.get("expires_in", 3600)) - 60,
        "scope": data.get("scope", account.get("scope", "")),
    })
    if data.get("refresh_token"):
        account["refresh_token"] = data["refresh_token"]
    if data.get("open_id"):
        account["open_id"] = data["open_id"]
    _put(platform, account)
    return account


def finish_login(state: str, code: str, settings: dict, client: httpx.Client | None = None) -> dict:
    """Exchange the authorization code from the redirect for tokens and save them."""
    with _lock:
        pending = _pending.pop(state, None)
    if not pending:
        raise PublishError("This sign-in link expired or was already used. Start Connect again.")
    platform, verifier, redirect_uri, _ = pending
    data = _token_request(platform, settings, {"code": code, "grant_type": "authorization_code",
                                               "redirect_uri": redirect_uri, "code_verifier": verifier}, client)
    account = _store_tokens(platform, data)
    try:
        account["name"] = _account_name(platform, account["access_token"], client)
        _put(platform, account)
    except (httpx.HTTPError, PublishError, KeyError, ValueError):
        pass  # the name is only for display
    return {"platform": platform, "name": account.get("name", "")}


def _account_name(platform: str, token: str, client: httpx.Client | None = None) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    with _client(client) as c:
        if platform == "youtube":
            r = c.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                      headers=headers)
            items = r.json().get("items") or []
            return items[0]["snippet"]["title"] if items else ""
        r = c.get(f"{TIKTOK_API}/v2/user/info/", params={"fields": "open_id,display_name"}, headers=headers)
        return r.json().get("data", {}).get("user", {}).get("display_name", "")


def access_token(platform: str, settings: dict, client: httpx.Client | None = None) -> str:
    """A valid access token, refreshed if it's about to expire."""
    account = get(platform)
    if not account or not account.get("refresh_token"):
        name = "YouTube" if platform == "youtube" else "TikTok"
        raise PublishError(f"Connect your {name} account first (Settings → Accounts).")
    if account.get("expires_at", 0) > time.time():
        return account["access_token"]
    data = _token_request(platform, settings, {"grant_type": "refresh_token",
                                               "refresh_token": account["refresh_token"]}, client)
    return _store_tokens(platform, data, account)["access_token"]


def disconnect(platform: str, settings: dict) -> None:
    """Forget the tokens here and revoke them at the provider (best effort)."""
    account = get(platform)
    _put(platform, None)
    if not account:
        return
    token = account.get("refresh_token") or account.get("access_token")
    client_id, secret = keys(settings, platform)
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            if platform == "youtube":
                c.post(GOOGLE_REVOKE, params={"token": token})
            else:
                c.post(TIKTOK_REVOKE, data={"client_key": client_id, "client_secret": secret, "token": token})
    except httpx.HTTPError:
        pass
