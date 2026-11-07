import io
import json
import subprocess

import httpx
import pytest

from app import media, sounds


def _ffmpeg_ok() -> bool:
    try:
        media.tool("ffmpeg")
        return True
    except media.MediaError:
        return False


needs_ffmpeg = pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not installed")


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(sounds, "USER_DIR", tmp_path / "sounds")
    monkeypatch.setattr(sounds, "CREDITS", tmp_path / "sounds" / "credits.json")
    monkeypatch.setattr(sounds, "LEVELLED", tmp_path / "sounds" / ".levelled.json")
    return tmp_path / "sounds"


def tone(tmp_path, seconds: float, ext: str = "wav") -> bytes:
    path = tmp_path / f"tone_{seconds}.{ext}"
    subprocess.run([media.tool("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=300:duration={seconds}", str(path)], check=True)
    return path.read_bytes()


@needs_ffmpeg
def test_add_list_and_remove(library, tmp_path):
    s = sounds.add("Bruh (real)?.wav", io.BytesIO(tone(tmp_path, 0.6)))
    assert s["name"] == "Bruh (real).wav" and s["seconds"] == pytest.approx(0.6, abs=0.05)
    again = sounds.add("Bruh (real).wav", io.BytesIO(tone(tmp_path, 0.6)))
    assert again["name"] == "Bruh (real) 2.wav"
    assert [x["name"] for x in sounds.list_sounds()] == ["Bruh (real) 2.wav", "Bruh (real).wav"]
    assert sounds.path("Bruh (real).wav") == library / "Bruh (real).wav"
    sounds.remove("Bruh (real).wav")
    assert sounds.path("Bruh (real).wav") is None


@needs_ffmpeg
def test_add_rejects_wrong_files(library, tmp_path):
    with pytest.raises(sounds.SoundError, match="Use a"):
        sounds.add("virus.exe", io.BytesIO(b"x"))
    with pytest.raises(sounds.SoundError, match="up to 15 seconds"):
        sounds.add("long.wav", io.BytesIO(tone(tmp_path, 16)))
    with pytest.raises(sounds.SoundError, match="no audio"):
        sounds.add("fake.mp3", io.BytesIO(b"not audio at all"))
    assert sounds.list_sounds() == []  # nothing half-written left behind


@pytest.mark.parametrize("name", ["../secret.wav", "a/b.wav", "x.exe", "", ".upload_1.wav"])
def test_path_refuses_odd_names(library, name):
    library.mkdir()
    (library / "secret.wav").write_bytes(b"")
    assert sounds.path(name) is None


def test_search_needs_a_key():
    with pytest.raises(sounds.SoundError, match="API key"):
        sounds.search({"freesound_api_key": ""}, "bruh")


def _freesound(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _sound(i, licence):
    return {"id": i, "name": f"bruh {i}.wav", "username": "someone", "license": licence, "duration": 0.8,
            "num_downloads": 10, "previews": {"preview-hq-mp3": f"https://cdn.freesound.org/previews/{i}.mp3"}}


def test_search_lists_free_sounds_first():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.url.params, auth=req.headers.get("authorization"), path=req.url.path)
        return httpx.Response(200, json={"count": 2, "next": "x", "results": [
            _sound(1, "Attribution"), _sound(2, "Creative Commons 0")]})

    out = sounds.search({"freesound_api_key": "k"}, " bruh ", client=_freesound(handler))
    assert seen["path"] == "/apiv2/search/" and seen["query"] == "bruh" and seen["auth"] == "Token k"
    assert seen["filter"] == "duration:[0 TO 15]"
    assert [(r["id"], r["license"]) for r in out["results"]] == [(2, "CC0"), (1, "CC BY")]
    assert out["more"] is True


def test_search_bad_key():
    client = _freesound(lambda req: httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(sounds.SoundError, match="didn't accept"):
        sounds.search({"freesound_api_key": "k"}, "bruh", client=client)


@needs_ffmpeg
def test_add_freesound_keeps_the_credit(library, tmp_path):
    mp3 = tone(tmp_path, 0.5, "mp3")
    asked = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append((req.url.host, req.headers.get("authorization")))
        if req.url.path == "/apiv2/sounds/7/":
            return httpx.Response(200, json=_sound(7, "Attribution"))
        return httpx.Response(200, content=mp3)

    s = sounds.add_freesound({"freesound_api_key": "k"}, 7, client=_freesound(handler))
    assert s["name"] == "bruh 7.mp3"
    # The key goes to Freesound's API and its own CDN, nowhere else.
    assert asked == [("freesound.org", "Token k"), ("cdn.freesound.org", "Token k")]
    credit = json.loads((library / "credits.json").read_text())["bruh 7.mp3"]
    assert credit["user"] == "someone" and credit["license"] == "CC BY"
    assert sounds.list_sounds()[0]["credit"]["url"] == "https://freesound.org/s/7/"
    sounds.remove("bruh 7.mp3")
    assert json.loads((library / "credits.json").read_text()) == {}


LOUD = "aevalsrc=0.98*sin(2*PI*300*t):d=1"  # a full-scale tone, like an over-mastered meme sound


def test_gain_targets_average_and_caps_peaks_and_boost():
    assert sounds.gain_for(-6.0, 0.0) == -14.0  # very loud: down to the target
    assert sounds.gain_for(-25.0, -1.0) == -2.0  # spiky: peaks win
    assert sounds.gain_for(-50.0, -40.0) == 12.0  # very quiet: lifted, but only so much


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["wav", "mp3"])
def test_loud_sounds_are_levelled_when_added(library, tmp_path, ext):
    loud = tmp_path / f"loud.{ext}"
    subprocess.run([media.tool("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    LOUD, str(loud)], check=True)
    before, _ = sounds._levels(loud)
    s = sounds.add(f"boom.{ext}", io.BytesIO(loud.read_bytes()))
    mean, peak = sounds._levels(sounds.path(s["name"]))
    assert before > -6 and abs(mean - sounds.TARGET_DB) < 1.5 and peak <= sounds.PEAK_DB + 0.5
    assert s["seconds"] == pytest.approx(1, abs=0.1)


@needs_ffmpeg
def test_sounds_added_earlier_get_levelled_once(library, tmp_path, monkeypatch):
    monkeypatch.setattr(sounds, "LEVELLED", library / ".levelled.json")
    library.mkdir()
    subprocess.run([media.tool("ffmpeg"), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    LOUD, str(library / "old.wav")], check=True)
    assert sounds._levels(library / "old.wav")[0] > -10
    assert [x["name"] for x in sounds.list_sounds()] == ["old.wav"]
    assert abs(sounds._levels(library / "old.wav")[0] - sounds.TARGET_DB) < 1.5
    calls = []
    monkeypatch.setattr(sounds, "level", calls.append)
    sounds.list_sounds()
    assert calls == []  # already done
