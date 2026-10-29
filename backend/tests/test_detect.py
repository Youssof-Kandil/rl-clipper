from pathlib import Path

import cv2
import pytest

from app.detect.events import Hit, attach_scoreboard, merge_hits
from app.detect.scoreboard import ScoreGoal, ScoreTracker, parse_clock, parse_score, read_clock, read_scores
from app.detect.tags import classify

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("texts,expected", [
    (["SAVE", "+50"], "save"),
    (["EPIC SAVE", "+75"], "epic_save"),
    (["EPICSAVE", "+75"], "epic_save"),
    (["5AVE", "+75"], "epic_save"),  # OCR misread, points disambiguate
    (["SAVF"], "save"),
    (["GOAL", "+100"], "goal"),
    (["G0AL"], "goal"),
    (["AERIAL GOAL", "+100"], "goal"),
    # Seen on real footage:
    (["AERIALGOAL", "+20"], "goal"),
    (["GOAL", "100"], "goal"),
    (["EPICSAVE", "￥75"], "epic_save"),
])
def test_classify_matches(texts, expected):
    assert classify(texts)[0] == expected


@pytest.mark.parametrize("texts", [
    ["SHOT ON GOAL", "+20"], ["CLEAR", "+20"], ["SAVIOR"], ["CENTER"], [],
    ["SHOTON GOAL", "+10"], ["SHOT.ON.GOAL", "+10"], ["SHOT ONGOAL", "+10"],
    ["SCORE", "GOALS", "ASSISTS", "SAVES"],  # end-of-match scoreboard headers
])
def test_classify_ignores_other_tags(texts):
    assert classify(texts) is None


def test_points_raise_confidence():
    assert classify(["SAVE", "+50"])[1] > classify(["SAVE"])[1]


@pytest.mark.parametrize("name,expected", [("save_tag.png", "save"), ("epic_save_ingame.png", "epic_save")])
def test_screenshots(name, expected):
    from app.detect.ocr import read_text

    boxes = read_text(cv2.imread(str(FIXTURES / name)))
    assert classify([b.text for b in boxes])[0] == expected


def test_merge_collapses_one_tag():
    hits = [Hit(10.0, "save", 0.9), Hit(10.5, "epic_save", 0.95), Hit(11.0, "epic_save", 0.95),
            Hit(11.5, "save", 0.7), Hit(30.0, "goal", 0.95), Hit(30.5, "goal", 0.95)]
    events = merge_hits(hits, 4.0)
    assert [(e.time, e.type) for e in events] == [(10.5, "epic_save"), (30.0, "goal")]


def test_merge_splits_far_apart_same_type():
    events = merge_hits([Hit(5, "save", 0.9), Hit(20, "save", 0.9)], 4.0)
    assert len(events) == 2


def test_scoreboard_merges_into_tag_goal():
    events = merge_hits([Hit(41.0, "goal", 0.95)], 4.0)
    out = attach_scoreboard(events, [ScoreGoal(41.5, "blue", (1, 0)), ScoreGoal(90, "orange", (1, 1))], 6.0)
    assert [(e.type, e.team) for e in out] == [("goal", "blue"), ("goal_other", "orange")]


@pytest.mark.parametrize("text,score,expected", [
    ("2", 0.99, 2), ("12", 0.99, 12),
    # The scoreboard font's square digits, as OCR returns them.
    ("口", 0.54, 0), ("回", 0.6, 0), ("B", 0.9, 3), ("I", 0.8, 1),
    ("4:31", 0.99, None), ("", 0.99, None), ("7", 0.2, None),
])
def test_parse_score(text, score, expected):
    assert parse_score(text, score) == expected


@pytest.mark.parametrize("name,expected", [
    ("scoreboard_0_1.png", (0, 1)), ("scoreboard_3_5.png", (3, 5)),
    # Playing orange: your team's score sits on the left, in orange.
    ("scoreboard_orange_left_2_0.png", (0, 2)),
])
def test_read_scores_real_frames(name, expected):
    from app.detect.ocr import read_line

    assert read_scores(cv2.imread(str(FIXTURES / name)), read_line) == expected


def test_tracker_needs_two_reads_and_ignores_resets():
    tr = ScoreTracker()
    for t, s in [(0, (0, 0)), (1, (0, 0)), (2, (1, 0)), (3, (7, 0)), (4, (1, 0)), (5, (1, 0)),
                 (6, (0, 0)), (7, (0, 0))]:
        tr.update(t, s)
    # (7,0) was a one-off misread; 1-0 confirmed (first seen at 4); 0-0 is a new match.
    assert [(g.time, g.team) for g in tr.goals] == [(4, "blue")]


def test_tracker_ignores_repeated_misread():
    # Real footage: orange "3" read as "13" twice, then the real 1-4 arrives.
    tr = ScoreTracker()
    for t, s in [(0, (1, 3)), (1, (1, 3)), (2, (1, 13)), (3, (1, 13)), (4, (1, 3)),
                 (10, (1, 4)), (11, (1, 4))]:
        tr.update(t, s)
    assert [(g.time, g.score) for g in tr.goals] == [(10, (1, 4))]


def test_tracker_resyncs_after_missed_goal():
    # A goal never read cleanly (1-3 -> 1-5): adopt 1-5 after enough reads, then keep going.
    tr = ScoreTracker()
    for t, s in [(0, (1, 3)), (1, (1, 3))] + [(t, (1, 5)) for t in range(2, 7)] + [(8, (1, 6)), (9, (1, 6))]:
        tr.update(t, s)
    assert [g.score for g in tr.goals] == [(1, 6)]


@pytest.mark.parametrize("text,score,expected,want", [
    ("4:35", 0.98, None, 275), ("0:00", 0.9, None, 0), (" 0:12", 0.87, None, 12),
    (":55", 0.76, 117, 115), ("O:51", 0.82, None, 51),  # dropped minute; O for 0
    (":55", 0.76, None, None), ("4:35", 0.3, None, None), ("", 0.0, None, None),
    # Overtime counts up and is stored negative, like the replay's overtime ticks.
    ("+0:35", 0.9, None, -35), ("+1:05", 0.9, None, -65), (":36", 0.8, -35, -36), ("+:36", 0.8, None, None),
])
def test_parse_clock(text, score, expected, want):
    assert parse_clock(text, score, expected) == want


def test_read_clock_real_frame():
    from app.detect.ocr import read_line

    assert read_clock(cv2.imread(str(FIXTURES / "scoreboard_orange_left_2_0.png")), read_line) == 152
