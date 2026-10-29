"""Send a video to TikTok (Content Posting API, file upload from disk).

Inbox mode (default, scope video.upload): the video lands in the creator's TikTok inbox
as a draft; they finish posting in the app. No TikTok audit needed.
Direct mode (scope video.publish): posts straight away, but until TikTok audits your
app every post is forced to private (SELF_ONLY).
"""

from __future__ import annotations

import os
import time
from typing import Callable

import httpx

from . import accounts
from .accounts import TIKTOK_API, PublishError, _client

MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024

Progress = Callable[[float, str], None]

_ERRORS = {
    "spam_risk_too_many_pending_share": "TikTok allows only a few pending drafts per day. Post or delete the drafts "
                                        "in your TikTok inbox, then try again.",
    "spam_risk_too_many_posts": "TikTok's daily posting limit for this account is reached. Try again tomorrow.",
    "unaudited_client_can_only_post_to_private_accounts": "Your TikTok app isn't audited yet, so direct posts must be "
                                                          "private. Turn off \"Direct post\" in Settings to send drafts "
                                                          "to your inbox instead.",
    "scope_not_authorized": "Your TikTok connection is missing a permission. Disconnect and connect again in Settings.",
    "access_token_invalid": "Your TikTok sign-in expired. Disconnect and connect again in Settings.",
    "url_ownership_unverified": "TikTok needs domain verification for this upload type.",
    "privacy_level_option_mismatch": "That privacy option isn't allowed for this account.",
}


def chunk_plan(size: int, chunk: int | None = None) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) by TikTok's rules: chunks 5-64 MB, files under
    5 MB go in one piece, and the last chunk takes the remainder (it may be bigger)."""
    if size < MIN_CHUNK:
        return size, 1
    chunk = min(max(chunk or CHUNK, MIN_CHUNK), MAX_CHUNK, size)
    return chunk, max(size // chunk, 1)


def _check(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        raise PublishError(f"TikTok answered {r.status_code}: {r.text[:200]}") from None
    err = body.get("error") or {}
    code = err.get("code", "ok")
    if r.status_code >= 400 or code not in ("ok", ""):
        raise PublishError(_ERRORS.get(code) or f"TikTok error: {err.get('message') or code}")
    return body.get("data") or {}


def creator_info(settings: dict, client: httpx.Client | None = None) -> dict:
    """Direct mode: the account's name and allowed privacy options (TikTok requires
    showing these before posting)."""
    token = accounts.access_token("tiktok", settings, client)
    with _client(client) as c:
        return _check(c.post(f"{TIKTOK_API}/v2/post/publish/creator_info/query/",
                             headers={"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json; charset=UTF-8"}))


def init_body(size: int, caption: str | None = None, privacy: str | None = None) -> dict:
    chunk, count = chunk_plan(size)
    body: dict = {"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                                  "total_chunk_count": count}}
    if privacy is not None:  # direct post
        body["post_info"] = {"title": (caption or "")[:2200], "privacy_level": privacy,
                             "disable_duet": False, "disable_comment": False, "disable_stitch": False}
    return body


def upload(path: str, settings: dict, caption: str = "", privacy: str | None = None,
           progress: Progress | None = None, cancelled: Callable[[], bool] = lambda: False,
           client: httpx.Client | None = None, poll_every: float = 3.0) -> dict:
    """Send ``path`` to TikTok. ``privacy`` None = inbox draft; otherwise a direct post
    with that privacy level. Returns {publish_id, status, mode}."""
    size = os.path.getsize(path)
    direct = privacy is not None
    token = accounts.access_token("tiktok", settings, client)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    endpoint = "video/init" if direct else "inbox/video/init"
    with _client(client) as c:
        data = _check(c.post(f"{TIKTOK_API}/v2/post/publish/{endpoint}/", headers=headers,
                             json=init_body(size, caption, privacy)))
        publish_id, upload_url = data["publish_id"], data["upload_url"]
        chunk, count = chunk_plan(size)
        with open(path, "rb") as fh:
            for i in range(count):
                if cancelled():
                    raise InterruptedError("Cancelled")
                start = i * chunk
                end = size - 1 if i == count - 1 else start + chunk - 1
                fh.seek(start)
                part = fh.read(end - start + 1)
                r = c.put(upload_url, content=part, headers={"Content-Type": "video/mp4",
                                                            "Content-Length": str(len(part)),
                                                            "Content-Range": f"bytes {start}-{end}/{size}"})
                if r.status_code not in (200, 201, 206):
                    raise PublishError(f"TikTok upload failed ({r.status_code}). Try again.")
                if progress:
                    progress(0.9 * (i + 1) / count, f"Uploading to TikTok · {(i + 1) * 100 // count}%")
        # TikTok processes the file, then drops it in the inbox (or publishes it).
        goal = "PUBLISH_COMPLETE" if direct else "SEND_TO_USER_INBOX"
        state = "PROCESSING_UPLOAD"
        for _ in range(100):
            info = _check(c.post(f"{TIKTOK_API}/v2/post/publish/status/fetch/", headers=headers,
                                 json={"publish_id": publish_id}))
            state = info.get("status", state)
            if state in (goal, "PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                break
            if state == "FAILED":
                raise PublishError(f"TikTok couldn't process the video: {info.get('fail_reason', 'unknown reason')}")
            if progress:
                progress(0.95, "TikTok is processing the video")
            time.sleep(poll_every)
    if progress:
        progress(1.0, "Sent to your TikTok inbox" if not direct else "Posted to TikTok")
    return {"publish_id": publish_id, "status": state, "mode": "direct" if direct else "inbox"}
