import subprocess

import pytest

from app import captions, media, sequences

SETTINGS = {"pre_seconds": 10, "post_seconds": 10}


def _project():
    return {"info": {"duration": 600.0},
            "events": [{"id": "a", "type": "save", "time": 100.0, "start": 90.0, "end": 110.0},
                       {"id": "b", "type": "goal", "time": 300.0, "start": 290.0, "end": 310.0}]}


# ---------------------------------------------------------------- timelines

def test_clean_clamps_trims_and_drops_unknown_events():
    seq = sequences.clean(_project(), {"captions": True, "items": [
        {"id": "x", "event_id": "b", "start": 250, "end": 305, "crop_x": 1.7, "style": "focus45"},
        {"event_id": "gone", "start": 1, "end": 2},
        {"id": "y", "event_id": "a", "start": 95, "end": 96, "style": "nope"},
    ]}, SETTINGS)
    assert seq["captions"] is True
    assert [(i["id"], i["start"], i["end"], i["crop_x"], i["style"]) for i in seq["items"]] == [
        ("x", 290.0, 305.0, 1.0, "focus45"),  # order kept, trimmed into the event's window
        ("y", 95.0, 96.0, 0.5, None),
    ]


def test_prune_repoints_items_after_reanalysis():
    p = _project()
    p["sequences"] = {"tiktok": {"items": [{"id": "1", "event_id": "a"}, {"id": "2", "event_id": "b"}]}}
    old = p["events"]
    # Re-analysis: new ids, the save found 0.4 s later, the goal gone.
    p["events"] = [{"id": "a2", "type": "save", "time": 100.4, "start": 90.4, "end": 110.4}]
    sequences.prune(p, old)
    assert p["sequences"]["tiktok"]["items"] == [{"id": "1", "event_id": "a2"}]


# ---------------------------------------------------------------- captions

WORDS = [(0.0, 0.2, " what"), (0.25, 0.4, " a"), (0.45, 0.8, " save."), (0.9, 1.1, " I"),
         (1.15, 1.3, " was"), (1.35, 1.5, " so"), (1.55, 1.7, " ready"), (1.75, 1.9, " for"),
         (3.0, 3.4, " that")]


def test_chunk_words_whole_sentences_with_word_timings():
    cues = captions.chunk_words(WORDS)
    # Sentence end and the 1.1 s pause both start a new caption.
    assert [c["text"] for c in cues] == ["what a save.", "I was so ready for", "that"]
    assert [w["start"] for w in cues[1]["words"]] == [0.9, 1.15, 1.35, 1.55, 1.75]
    # Captions linger a little but never run into the next one.
    assert cues[0]["end"] == pytest.approx(0.9) and cues[1]["end"] <= cues[2]["start"]
    assert [c["text"] for c in captions.chunk_words(WORDS, max_words=3)][:3] == ["what a save.", "I was so", "ready for"]


def test_cue_words_spread_evenly_after_edit():
    cue = captions.chunk_words(WORDS)[1]
    assert captions.cue_words(cue) == cue["words"]
    cue["text"] = "I was totally ready"
    # The caption runs 0.9-2.05 s, so four words get 0.2875 s each.
    assert [(w["start"], w["text"]) for w in captions.cue_words(cue)] == [
        (0.9, "I"), (1.19, "was"), (1.48, "totally"), (1.76, "ready")]


def test_ass_highlights_one_word_at_a_time(tmp_path):
    cue = captions.chunk_words(WORDS)[0]  # what(0.0) a(0.25) save.(0.45), ends 0.9
    text = captions.write_ass(tmp_path / "h.ass", [cue], 0.0, 5.0, (1080, 1920), color="#2EA8FF").read_text()
    events = [line for line in text.splitlines() if line.startswith("Dialogue")]
    assert [e.split(",")[1:3] for e in events] == [["0:00:00.00", "0:00:00.25"], ["0:00:00.25", "0:00:00.45"],
                                                   ["0:00:00.45", "0:00:00.90"]]
    assert events[1].endswith("what {\\c&H00FFA82E&}a{\\c&H00FFFFFF&} save.")
    plain = captions.write_ass(tmp_path / "p.ass", [cue], 0.0, 5.0, (1080, 1920), highlight=False).read_text()
    assert [line for line in plain.splitlines() if line.startswith("Dialogue")][0].endswith("what a save.")


def test_merge_keeps_edits_outside_retranscribed_range():
    old = [captions.new_cue(10, 11, "keep me"), captions.new_cue(50, 51, "old take"),
           captions.new_cue(59.5, 61, "hangs over the clip's end")]
    new = [captions.new_cue(50.2, 51, "new take")]
    assert [c["text"] for c in captions.merge(old, new, [(45, 60)])] == ["keep me", "new take"]


def test_write_ass_clip_relative_and_escaped(tmp_path):
    cues = [captions.new_cue(98, 100.5, "nice {save} \\ lol"), captions.new_cue(200, 201, "elsewhere")]
    text = captions.write_ass(tmp_path / "c.ass", cues, 99.0, 109.0, (1080, 1920), 78, "lower", upper=True,
                              highlight=False).read_text()
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    dialogue = [line for line in text.splitlines() if line.startswith("Dialogue")]
    assert len(dialogue) == 1
    # Starts at the clip's first frame (the cue began before it), ends 1.5 s in.
    assert dialogue[0].startswith("Dialogue: 0,0:00:00.00,0:00:01.50,Cap")
    assert "\\pos(540,1344)" in dialogue[0] and dialogue[0].endswith("NICE (SAVE) / LOL")


def test_caption_positions_stay_in_focus_area():
    for pos in ("upper", "middle", "lower"):
        assert 285 < captions.caption_y((1080, 1920), pos) < 1635


# ---------------------------------------------------------------- rendering

def test_subtitles_appended_to_vertical_graph():
    cmd = media.build_export_cmd("in.mkv", "out.mp4", 0, 5, 2, frame={"info": {"width": 1920, "height": 1080},
                                                                        "style": "focus45"}, subtitles="cap_1.ass")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.endswith("[v];[v]subtitles='cap_1.ass'[vs]") and "[vs]" in cmd
    wide = media.build_export_cmd("in.mkv", "out.mp4", 0, 5, 2, subtitles="cap_1.ass")
    assert wide[wide.index("-filter_complex") + 1] == "[0:v]subtitles='cap_1.ass'[vs]"


def test_concat_cmd_copies_every_stream():
    cmd = media.build_concat_cmd("list.txt", "out.mp4", 2)
    assert cmd[cmd.index("-f") + 1] == "concat" and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-map") + 1] == "0" and "handler_name=Mic" in cmd


def _ffmpeg_ok() -> bool:
    try:
        media.tool("ffmpeg")
        return True
    except media.MediaError:
        return False


@pytest.mark.skipif(not _ffmpeg_ok(), reason="ffmpeg not installed")
def test_compiled_tiktok_render(tmp_path):
    src = tmp_path / "src.mkv"
    subprocess.run([media.tool("ffmpeg"), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-f", "lavfi", "-i", "sine=frequency=880:duration=8",
                    "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)],
                   check=True)
    info = media.probe(src)
    cues = [captions.new_cue(1.2, 2.5, "what a save")]
    parts = []
    for n, (a, b) in enumerate([(1.0, 3.0), (5.0, 6.5)]):
        ass = captions.write_ass(tmp_path / f"cap_{n}.ass", cues, a, b, media.VERTICAL_SIZE)
        part = tmp_path / f"part_{n}.mp4"
        frame = {"info": info, "style": "focus45", "center_x": 0.5, "zoom": 1.0, "blur": 30.0}
        media.export_clip(str(src), str(part), a, b, info, 0, 1, "x264", None, frame, ass)
        parts.append(part)
    out = tmp_path / "compiled.mp4"
    media.concat(parts, str(out), info["audio_streams"])
    p = media.probe(out)
    assert (p["width"], p["height"]) == (1080, 1920)
    assert p["duration"] == pytest.approx(3.5, abs=0.15)
    assert [a["title"] for a in p["audio"]] == ["Mixed", "Game", "Mic"]
