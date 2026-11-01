"""Upload a video to YouTube (Data API v3 resumable upload).

A vertical (9:16) video of 3 minutes or less becomes a Short; there's no separate
endpoint. Projects that haven't passed YouTube's API audit get every upload forced to
private: the response's privacyStatus tells us, and the UI says so.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Callable

import httpx

from . import accounts
from .accounts import PublishError, _client

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
CHUNK = 8 * 1024 * 1024  # a multiple of 256 KiB, as resumable uploads require
GAMING = "20"
SHORTS_MAX_SECONDS = 180
PRIVACY = ("private", "unlisted", "public")
# Assignable categories (videoCategories.list is the same everywhere for these).
CATEGORIES = {"20": "Gaming", "24": "Entertainment", "22": "People & Blogs", "17": "Sports", "23": "Comedy",
              "2": "Autos & Vehicles", "1": "Film & Animation", "10": "Music", "26": "Howto & Style",
              "27": "Education", "28": "Science & Technology"}
LICENSES = ("youtube", "creativeCommon")

Progress = Callable[[float, str], None]


def studio_url(video_id: str) -> str:
    """The video's edit page in YouTube Studio (where the Shorts "Related video" is set)."""
    return f"https://studio.youtube.com/video/{video_id}/edit"


def build_metadata(title: str, description: str, tags: list[str], privacy: str, publish_at: str | None,
                   short: bool, options: dict | None = None) -> dict:
    """The videos.insert body. Scheduling (publishAt) requires the video to be private
    until then; #Shorts in the title helps YouTube file a vertical video as a Short.

    ``options`` holds the rest of YouTube's upload details: category, language,
    audio_language, made_for_kids, license, embeddable, public_stats, synthetic,
    recording_date, and related ({id, title}) with related_in_description."""
    o = options or {}
    title = title.strip() or "Rocket League"
    if short and "#shorts" not in title.lower() and "#shorts" not in description.lower():
        title = f"{title} #Shorts" if len(title) <= 92 else title
    related = o.get("related") or {}
    if related.get("id") and o.get("related_in_description", True):
        line = f"▶ Full video: {related.get('title') or 'watch here'}\nhttps://youtu.be/{related['id']}"
        description = f"{line}\n\n{description}".strip()
    status = {"privacyStatus": "private" if publish_at else (privacy if privacy in PRIVACY else "private"),
              "selfDeclaredMadeForKids": bool(o.get("made_for_kids", False))}
    if publish_at:
        status["publishAt"] = publish_at
    if o.get("license") in LICENSES:
        status["license"] = o["license"]
    for key, field in (("embeddable", "embeddable"), ("public_stats", "publicStatsViewable"),
                       ("synthetic", "containsSyntheticMedia")):
        if key in o:
            status[field] = bool(o[key])
    snippet = {"title": title[:100], "description": description[:5000], "tags": tags[:30],
               "categoryId": o.get("category") if o.get("category") in CATEGORIES else GAMING}
    if o.get("language"):
        snippet["defaultLanguage"] = o["language"]
    if o.get("audio_language"):
        snippet["defaultAudioLanguage"] = o["audio_language"]
    meta = {"snippet": snippet, "status": status}
    if o.get("recording_date"):
        meta["recordingDetails"] = {"recordingDate": o["recording_date"]}
    return meta


def _seconds(iso: str) -> int:
    """'PT1H2M3S' -> 3723."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def my_videos(settings: dict, client: httpx.Client | None = None, limit: int = 50,
              match: str = "rocket league") -> dict:
    """The connected channel's latest uploads (newest first), with views and length, and
    the one we suggest linking: the public long video with the most views per day,
    among those whose title mentions ``match`` when there are any."""
    token = accounts.access_token("youtube", settings, client)
    h = {"Authorization": f"Bearer {token}"}
    with _client(client) as c:
        def get(path: str, **params) -> dict:
            r = c.get(f"{API}/{path}", params=params, headers=h)
            if r.status_code >= 400:
                if r.status_code == 403:
                    raise PublishError("YouTube didn't allow reading your videos. Reconnect YouTube in "
                                       "Settings → Accounts and allow viewing your YouTube account.")
                raise _error(r)
            return r.json()

        channels = get("channels", part="contentDetails", mine="true").get("items") or []
        if not channels:
            raise PublishError("This Google account has no YouTube channel yet.")
        uploads = channels[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        items = get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=min(limit, 50))
        ids = [i["contentDetails"]["videoId"] for i in items.get("items", [])]
        if not ids:
            return {"videos": [], "suggested": None}
        found = get("videos", part="snippet,contentDetails,statistics,status", id=",".join(ids)).get("items", [])
    now = time.time()
    videos = []
    for v in found:
        published = v["snippet"].get("publishedAt", "")
        try:
            age_days = max(1.0, (now - datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()) / 86400)
        except ValueError:
            age_days = 1.0
        views = int(v.get("statistics", {}).get("viewCount", 0))
        seconds = _seconds(v["contentDetails"].get("duration", ""))
        thumbs = v["snippet"].get("thumbnails", {})
        videos.append({"id": v["id"], "title": v["snippet"].get("title", ""), "published": published,
                       "seconds": seconds, "views": views, "per_day": views / age_days,
                       "privacy": v.get("status", {}).get("privacyStatus", ""),
                       "short": seconds <= SHORTS_MAX_SECONDS,
                       "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")})
    videos.sort(key=lambda v: v["published"], reverse=True)
    long_public = [v for v in videos if not v["short"] and v["privacy"] == "public"]
    long_public = [v for v in long_public if match.lower() in v["title"].lower()] or long_public
    suggested = max(long_public, key=lambda v: v["per_day"])["id"] if long_public else None
    return {"videos": videos, "suggested": suggested}


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
           cancelled: Callable[[], bool] = lambda: False, client: httpx.Client | None = None,
           notify: bool = True) -> dict:
    """Upload ``path``; returns {id, url, privacy}. ``notify`` tells subscribers about it."""
    size = os.path.getsize(path)
    token = accounts.access_token("youtube", settings, client)
    def done(r: httpx.Response) -> dict:
        video = r.json()
        if progress:
            progress(1.0, "Uploaded to YouTube")
        return {"id": video["id"], "url": f"https://youtu.be/{video['id']}",
                "privacy": video.get("status", {}).get("privacyStatus", metadata["status"]["privacyStatus"])}

    with _client(client) as c:
        params = {"uploadType": "resumable", "part": ",".join(metadata), "notifySubscribers": str(notify).lower()}
        r = c.post(UPLOAD_URL, params=params, json=metadata,
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
