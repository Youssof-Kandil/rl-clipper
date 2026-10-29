"""Upload a video to YouTube (Data API v3 resumable upload).

A vertical (9:16) video of 3 minutes or less becomes a Short; there's no separate
endpoint. Projects that haven't passed YouTube's API audit get every upload forced to
private: the response's privacyStatus tells us, and the UI says so.
"""

from __future__ import annotations

import os
import time
from typing import Callable

import httpx

from . import accounts
from .accounts import PublishError, _client

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK = 8 * 1024 * 1024  # a multiple of 256 KiB, as resumable uploads require
GAMING = "20"
SHORTS_MAX_SECONDS = 180
PRIVACY = ("private", "unlisted", "public")

Progress = Callable[[float, str], None]


def build_metadata(title: str, description: str, tags: list[str], privacy: str, publish_at: str | None,
                   short: bool) -> dict:
    """The videos.insert body. Scheduling (publishAt) requires the video to be private
    until then; #Shorts in the title helps YouTube file a vertical video as a Short."""
    title = title.strip() or "Rocket League"
    if short and "#shorts" not in title.lower() and "#shorts" not in description.lower():
        title = f"{title} #Shorts" if len(title) <= 92 else title
    status = {"privacyStatus": "private" if publish_at else (privacy if privacy in PRIVACY else "private"),
              "selfDeclaredMadeForKids": False}
    if publish_at:
        status["publishAt"] = publish_at
    return {"snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30],
                        "categoryId": GAMING},
            "status": status}


def _error(r: httpx.Response) -> PublishError:
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        message = err.get("message", r.text[:200])
    except ValueError:
        reason, message = "", r.text[:200]
    hints = {
        "quotaExceeded": "Your Google project's daily YouTube quota is used up. It resets at midnight Pacific time.",
        "uploadLimitExceeded": "This channel hit YouTube's upload limit for now. Try again later.",
        "youtubeSignupRequired": "This Google account has no YouTube channel yet. Create one, then connect again.",
        "invalidPublishAt": "The scheduled time must be in the future.",
        "forbidden": "YouTube refused the upload. Is the YouTube Data API v3 enabled for your Google project?",
    }
    return PublishError(hints.get(reason) or f"YouTube upload failed ({r.status_code}): {message}")


def upload(path: str, metadata: dict, settings: dict, progress: Progress | None = None,
           cancelled: Callable[[], bool] = lambda: False, client: httpx.Client | None = None) -> dict:
    """Upload ``path``; returns {id, url, privacy}."""
    size = os.path.getsize(path)
    token = accounts.access_token("youtube", settings, client)
    def done(r: httpx.Response) -> dict:
        video = r.json()
        if progress:
            progress(1.0, "Uploaded to YouTube")
        return {"id": video["id"], "url": f"https://youtu.be/{video['id']}",
                "privacy": video.get("status", {}).get("privacyStatus", metadata["status"]["privacyStatus"])}

    with _client(client) as c:
        r = c.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=metadata,
                   headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size),
                            "X-Upload-Content-Type": "video/mp4"})
        if r.status_code >= 400:
            raise _error(r)
        session = r.headers["Location"]
        sent, retries = 0, 0
        with open(path, "rb") as fh:
            while True:
                if cancelled():
                    raise InterruptedError("Cancelled")
                fh.seek(sent)
                chunk = fh.read(CHUNK)
                end = sent + len(chunk) - 1
                try:
                    r = c.put(session, content=chunk, headers={"Content-Length": str(len(chunk)),
                                                               "Content-Range": f"bytes {sent}-{end}/{size}"})
                except httpx.TransportError:
                    r = None
                if r is not None and r.status_code in (200, 201):
                    return done(r)
                if r is not None and r.status_code == 308:  # chunk stored: continue after what YouTube has
                    rng = r.headers.get("Range")
                    sent = int(rng.split("-")[1]) + 1 if rng else 0
                    retries = 0
                    if progress:
                        progress(sent / size, f"Uploading to YouTube · {sent * 100 // size}%")
                    continue
                if r is not None and r.status_code < 500 and r.status_code != 429:
                    raise _error(r)
                # Network hiccup or server error: ask where the upload stands, then resume.
                retries += 1
                if retries > 5:
                    raise PublishError("YouTube upload kept failing; check your connection and try again.")
                time.sleep(2 ** retries)
                q = c.put(session, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"})
                if q.status_code in (200, 201):
                    return done(q)
                rng = q.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if q.status_code == 308 and rng else 0
