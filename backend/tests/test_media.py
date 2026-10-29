from app import media, store


def test_audio_map_two_tracks():
    args = media.audio_map_args(2, game=0, mic=1)
    assert "[0:a:0][0:a:1]amix=inputs=2:duration=longest:normalize=0[mix]" in args
    assert args.count("-map") == 3
    assert "handler_name=Mic" in args


def test_audio_map_swapped_and_single():
    assert "[0:a:1][0:a:0]amix" in media.audio_map_args(2, game=1, mic=0)[1]
    assert media.audio_map_args(1, 0, 1)[:2] == ["-map", "0:a:0"]
    assert media.audio_map_args(0, 0, 1) == ["-an"]


def test_proxy_audio_is_mixed_only():
    args = media.audio_map_args(2, 0, 1, mixed_only=True)
    assert args.count("-map") == 1


def test_clip_filename():
    assert media.clip_filename(r"C:\vids\RL Session #3.mkv", "epic_save", 3725) == "RL_Session_3_epic_save_1-02-05.mp4"
    assert media.clip_filename("a.mp4", "goal", 65) == "a_goal_01-05.mp4"


def test_encoder_quality_presets():
    nv = media.video_encoder_args("nvenc", "balanced")
    assert nv[nv.index("-c:v") + 1] == "h264_nvenc" and nv[nv.index("-cq") + 1] == "23"
    assert "qres" in nv and "-tag:v" not in nv
    small = media.video_encoder_args("nvenc", "small")
    assert small[small.index("-c:v") + 1] == "hevc_nvenc" and small[small.index("-tag:v") + 1] == "hvc1"
    cpu = media.video_encoder_args("x264", "best")
    assert cpu[cpu.index("-c:v") + 1] == "libx264" and cpu[cpu.index("-crf") + 1] == "17"
    assert media.video_encoder_args("x264", "nonsense") == media.video_encoder_args("x264", "balanced")


def test_clip_filename_vertical():
    assert media.clip_filename("a.mp4", "save", 65, vertical=True) == "a_save_01-05_9x16.mp4"


def test_vertical_crop_window():
    # Full-height 9:16 slice of 1080p, centred, pushed to the edges, and zoomed.
    assert media.vertical_crop(1920, 1080) == (608, 1080, 656, 0)
    assert media.vertical_crop(1920, 1080, center_x=0.0) == (608, 1080, 0, 0)
    assert media.vertical_crop(1920, 1080, center_x=1.0) == (608, 1080, 1312, 0)
    w, h, x, y = media.vertical_crop(1920, 1080, zoom=1.25)
    assert (w, h, y) == (486, 864, 108)


INFO = {"width": 1920, "height": 1080}


def test_vertical_filters():
    assert media.vertical_filter(INFO, "crop").startswith("[0:v]crop=608:1080:656:0,scale=1080:1920")
    fit = media.vertical_filter(INFO, "fit")
    assert "overlay=(W-w)/2:(H-h)/2[v]" in fit and "scale=1080:-2" in fit
    focus = media.vertical_filter(INFO, "focus", mask_input=1)
    assert "[1:v]format=gray" in focus and "alphamerge" in focus and focus.endswith("[v]")


def test_export_cmd_vertical_keeps_three_audio_tracks(tmp_path):
    frame = {"info": INFO, "style": "focus", "mask": tmp_path / "m.png"}
    cmd = media.build_export_cmd("in.mkv", "out.mp4", 10, 20, 2, frame=frame)
    assert cmd[cmd.index("-loop") + 3] == str(tmp_path / "m.png")
    assert cmd.count("-filter_complex") == 2  # video framing + audio mix
    assert "[v]" in cmd and "handler_name=Mic" in cmd
    assert cmd[cmd.index("-t") + 1] == "10.000"
    assert "-filter_complex" not in media.build_export_cmd("in.mkv", "out.mp4", 10, 20, 0)


def test_focus_mask_sharp_middle_soft_edges(tmp_path):
    import cv2

    m = cv2.imread(str(media.focus_mask(tmp_path / "m.png", 0.5)), cv2.IMREAD_GRAYSCALE)
    assert m.shape == (1920, 1080)
    assert m[960, 540] == 255 and m[0, 540] < 40 and m[1919, 0] == 0


def test_focus45_is_full_height_4x5_over_blurred_9x16():
    # 4:5 of the full 1080 height is 864 wide, scoreboard included (y = 0).
    assert media.vertical_crop(1920, 1080, aspect=4 / 5) == (864, 1080, 528, 0)
    f = media.vertical_filter(INFO, "focus45")
    assert "[fg]crop=864:1080:528:0,scale=1080:1350" in f
    assert "[bg]crop=608:1080:656:0,scale=1080:1920" in f and "gblur" in f
    assert f.endswith("overlay=0:285[v]")  # (1920 - 1350) / 2


def test_carry_edits_to_reanalysed_events():
    old = [{"id": "o1", "type": "save", "player": "Me", "time": 100.0, "start": 95.0, "end": 104.0,
            "selected": False, "frame": "9:16", "crop_x": 0.3},
           {"id": "o2", "type": "save", "player": "Them", "time": 200.0, "start": 190.0, "end": 210.0, "selected": True}]
    new = [{"id": "n1", "type": "save", "player": "Me", "time": 100.4, "start": 90.4, "end": 110.4, "selected": True},
           {"id": "n2", "type": "goal", "player": "Them", "time": 200.0, "start": 190.0, "end": 210.0, "selected": False}]
    store.carry_edits(old, new)
    assert new[0] | {} == {"id": "n1", "type": "save", "player": "Me", "time": 100.4, "start": 95.4, "end": 104.4,
                           "selected": False, "frame": "9:16", "crop_x": 0.3}
    assert new[1]["selected"] is False  # different play type: untouched


def test_clamp_clip_window():
    ev = {"time": 30.0}
    assert store.clamp_clip(ev, 0, 100, 10, 10, 600) == (20.0, 40.0)
    assert store.clamp_clip(ev, 0, 100, 5, 8, 600) == (25.0, 38.0)
    assert store.clamp_clip({"time": 5.0}, -10, 12, 10, 10, 600) == (0.0, 12.0)
    assert store.clamp_clip(ev, 35, 35, 10, 10, 600) == (35.0, 35.5)
    assert store.clamp_clip({"time": 595.0}, 590, 700, 10, 10, 600) == (590.0, 600.0)
