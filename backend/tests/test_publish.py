"""Posting: OAuth, YouTube resumable upload, TikTok chunked inbox upload (HTTP mocked)."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.publish import accounts, tiktok, youtube
from app.publish.accounts import PublishError

SETTINGS = {"youtube_client_id": "yt-id", "youtube_client_secret": "yt-secret",
            "tiktok_client_key": "tt-key", "tiktok_client_secret": "tt-secret", "tiktok_direct_post": False}


@pytest.fixture(autouse=True)
def isolated_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    accounts._pending.clear()


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def connect(platform, expires_in=3600):
    accounts._put(platform, {"access_token": "AT", "refresh_token": "RT", "expires_at": time.time() + expires_in})


# ---------------------------------------------------------------- OAuth

def test_pkce_challenges():
    v, c = accounts.pkce("youtube")
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    v, c = accounts.pkce("tiktok")  # TikTok desktop wants hex
    assert c == hashlib.sha256(v.encode()).hexdigest()
    assert 43 <= len(v) <= 128


def test_auth_urls():
    redirect = "http://127.0.0.1:8765/api/auth/youtube/callback"
    q = parse_qs(urlparse(accounts.auth_url("youtube", SETTINGS, redirect)).query)
    assert q["client_id"] == ["yt-id"] and q["redirect_uri"] == [redirect] and q["access_type"] == ["offline"]
    assert "youtube.upload" in q["scope"][0] and q["code_challenge_method"] == ["S256"]
    q = parse_qs(urlparse(accounts.auth_url("tiktok", SETTINGS, redirect)).query)
    assert q["client_key"] == ["tt-key"] and q["scope"] == ["user.info.basic,video.upload"]
    q = parse_qs(urlparse(accounts.auth_url("tiktok", SETTINGS | {"tiktok_direct_post": True}, redirect)).query)
    assert q["scope"] == ["user.info.basic,video.upload,video.publish"]


def test_auth_url_needs_keys():
    with pytest.raises(PublishError, match="keys"):
        accounts.auth_url("youtube", {}, "http://127.0.0.1:8765/x")


def test_finish_login_stores_tokens_once():
    url = accounts.auth_url("youtube", SETTINGS, "http://127.0.0.1:8765/cb")
    state = parse_qs(urlparse(url).query)["state"][0]

    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            form = parse_qs(req.content.decode())
            assert form["code"] == ["CODE"] and form["code_verifier"][0] and form["client_secret"] == ["yt-secret"]
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
        return httpx.Response(200, json={"items": [{"snippet": {"title": "Froggy RL"}}]})

    assert accounts.finish_login(state, "CODE", SETTINGS, mock(handler)) == {"platform": "youtube", "name": "Froggy RL"}
    assert accounts.status(SETTINGS)["youtube"] | {} == {"configured": True, "connected": True,
                                                        "name": "Froggy RL", "scope": ""}
    with pytest.raises(PublishError, match="expired or was already used"):
        accounts.finish_login(state, "CODE", SETTINGS, mock(handler))


def test_access_token_refreshes_when_expired():
    connect("tiktok", expires_in=-10)
    seen = {}

    def handler(req):
        seen.update(parse_qs(req.content.decode()))
        return httpx.Response(200, json={"access_token": "NEW", "expires_in": 86400, "open_id": "o"})

    assert accounts.access_token("tiktok", SETTINGS, mock(handler)) == "NEW"
    assert seen["grant_type"] == ["refresh_token"] and seen["refresh_token"] == ["RT"]
    assert accounts.get("tiktok")["refresh_token"] == "RT"  # kept when the response omits it


def test_bad_secret_message():
    connect("youtube", expires_in=-10)
    handler = lambda req: httpx.Response(401, json={"error": "invalid_client"})  # noqa: E731
    with pytest.raises(PublishError, match="invalid_client.*Settings"):
        accounts.access_token("youtube", SETTINGS, mock(handler))


def test_not_connected_message():
    with pytest.raises(PublishError, match="Connect your YouTube"):
        accounts.access_token("youtube", SETTINGS)


# ---------------------------------------------------------------- YouTube

def test_youtube_metadata():
    m = youtube.build_metadata("Epic save", "", ["RL"], "public", None, short=True)
    assert m["snippet"]["title"] == "Epic save #Shorts" and m["snippet"]["categoryId"] == "20"
    assert m["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    m = youtube.build_metadata("Intro", "", [], "public", "2026-11-01T18:00:00Z", short=False)
    assert m["snippet"]["title"] == "Intro"
    assert m["status"]["privacyStatus"] == "private" and m["status"]["publishAt"] == "2026-11-01T18:00:00Z"


def test_youtube_resumable_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "CHUNK", 256 * 1024)
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x" * (600 * 1024))  # 3 chunks
    connect("youtube")
    ranges = []

    def handler(req: httpx.Request):
        if req.method == "POST":
            assert req.headers["X-Upload-Content-Length"] == str(600 * 1024)
            assert json.loads(req.content)["snippet"]["title"] == "Save #Shorts"
            return httpx.Response(200, headers={"Location": "https://upload.example/session"})
        ranges.append(req.headers["Content-Range"])
        end = int(req.headers["Content-Range"].split("-")[1].split("/")[0])
        if end + 1 < 600 * 1024:
            return httpx.Response(308, headers={"Range": f"bytes=0-{end}"})
        return httpx.Response(200, json={"id": "abc123", "status": {"privacyStatus": "private"}})

    meta = youtube.build_metadata("Save", "", [], "public", None, short=True)
    res = youtube.upload(str(f), meta, SETTINGS, client=mock(handler))
    assert res == {"id": "abc123", "url": "https://youtu.be/abc123", "privacy": "private"}
    assert ranges == ["bytes 0-262143/614400", "bytes 262144-524287/614400", "bytes 524288-614399/614400"]


def test_youtube_quota_message(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    connect("youtube")
    body = {"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}}
    with pytest.raises(PublishError, match="quota is used up"):
        youtube.upload(str(f), youtube.build_metadata("a", "", [], "private", None, False), SETTINGS,
                       client=mock(lambda req: httpx.Response(403, json=body)))


# ---------------------------------------------------------------- TikTok

@pytest.mark.parametrize("size,expected", [
    (3 * 2**20, (3 * 2**20, 1)),            # under 5 MB: one piece
    (15 * 2**20, (10 * 2**20, 1)),          # remainder goes into the last chunk
    (25 * 2**20, (10 * 2**20, 2)),
    (100 * 2**20, (10 * 2**20, 10)),
])
def test_tiktok_chunk_plan(size, expected):
    assert tiktok.chunk_plan(size) == expected


def test_tiktok_inbox_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(tiktok, "CHUNK", 5 * 2**20)
    size = 12 * 2**20
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x" * size)
    connect("tiktok")
    calls = []
    statuses = iter(["PROCESSING_UPLOAD", "SEND_TO_USER_INBOX"])

    def handler(req: httpx.Request):
        path = req.url.path
        calls.append((req.method, path, req.headers.get("Content-Range")))
        if path.endswith("/inbox/video/init/"):
            body = json.loads(req.content)
            assert body == {"source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": 5 * 2**20,
                                            "total_chunk_count": 2}}
            return httpx.Response(200, json={"data": {"publish_id": "p1", "upload_url": "https://up.tiktok/x"},
                                             "error": {"code": "ok"}})
        if path.endswith("/status/fetch/"):
            return httpx.Response(200, json={"data": {"status": next(statuses)}, "error": {"code": "ok"}})
        return httpx.Response(201)

    res = tiktok.upload(str(f), SETTINGS, "Epic save", client=mock(handler), poll_every=0)
    assert res == {"publish_id": "p1", "status": "SEND_TO_USER_INBOX", "mode": "inbox"}
    puts = [c[2] for c in calls if c[0] == "PUT"]
    assert puts == [f"bytes 0-{5 * 2**20 - 1}/{size}", f"bytes {5 * 2**20}-{size - 1}/{size}"]


def test_tiktok_error_messages(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x" * 100)
    connect("tiktok")
    body = {"error": {"code": "spam_risk_too_many_pending_share", "message": "too many"}}
    with pytest.raises(PublishError, match="pending drafts"):
        tiktok.upload(str(f), SETTINGS, client=mock(lambda req: httpx.Response(403, json=body)))


def test_tiktok_direct_post_body():
    body = tiktok.init_body(1000, "Epic save #rl", "SELF_ONLY")
    assert body["post_info"]["privacy_level"] == "SELF_ONLY" and body["post_info"]["title"] == "Epic save #rl"
    assert "post_info" not in tiktok.init_body(1000)
