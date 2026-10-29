from datetime import datetime

import pytest

from app import replays
from app.detect import sync
from app.detect.scoreboard import ScoreGoal
from app.replays import ReplayEvent, ReplayInfo

# Object table and frames shaped like `rrrocket -n` output, trimmed to what the walker reads.
OBJECTS = [
    "Archetypes.Teams.Team0",
    "Archetypes.Teams.Team1",
    "Engine.PlayerReplicationInfo:PlayerName",
    "Engine.PlayerReplicationInfo:Team",
    "TAGame.PRI_TA:MatchSaves",
    "TAGame.PRI_TA:MatchGoals",
    "TAGame.GameEvent_Soccar_TA:ReplicatedStatEvent",
    "StatEvents.Events.Save",
    "StatEvents.Events.EpicSave",
    "StatEvents.Events.Goal",
    "Stadium_P.TheWorld:PersistentLevel.GoalVolume_TA_0.Goal_TA_53",
]
O = {name: i for i, name in enumerate(OBJECTS)}


def _upd(actor, obj, attr):
    return {"actor_id": actor, "object_id": O[obj], "attribute": attr}


def _frame(t, new=(), upd=()):
    return {"time": t, "delta": 0.03, "new_actors": list(new), "deleted_actors": [], "updated_actors": list(upd)}


def _stat(event):
    return _upd(99, "TAGame.GameEvent_Soccar_TA:ReplicatedStatEvent", {"StatEvent": {"unknown1": False, "object_id": O[event]}})


def _replay():
    frames = [
        _frame(10.0, new=[{"actor_id": 1, "object_id": O["Archetypes.Teams.Team0"]},
                          {"actor_id": 2, "object_id": O["Archetypes.Teams.Team1"]}]),
        _frame(10.1, upd=[
            _upd(5, "Engine.PlayerReplicationInfo:PlayerName", {"String": "Me"}),
            _upd(5, "Engine.PlayerReplicationInfo:Team", {"ActiveActor": {"active": True, "actor": 2}}),
            _upd(6, "Engine.PlayerReplicationInfo:PlayerName", {"String": "Rival"}),
            _upd(6, "Engine.PlayerReplicationInfo:Team", {"ActiveActor": {"active": True, "actor": 1}}),
        ]),
        # Rival saves; the counter arrives 0.6 s after the stat event.
        _frame(40.0, upd=[_stat("StatEvents.Events.Save")]),
        _frame(40.6, upd=[_upd(6, "TAGame.PRI_TA:MatchSaves", {"Int": 1})]),
        # Counters are re-sent all the time: not new events.
        _frame(45.0, upd=[_upd(6, "TAGame.PRI_TA:MatchSaves", {"Int": 1})]),
        # My epic save, announced twice, then a goal-volume stat event that isn't a play.
        _frame(70.0, upd=[_stat("StatEvents.Events.EpicSave")]),
        _frame(70.4, upd=[_stat("StatEvents.Events.EpicSave")]),
        _frame(70.9, upd=[_upd(5, "TAGame.PRI_TA:MatchSaves", {"Int": 1}),
                          _stat("Stadium_P.TheWorld:PersistentLevel.GoalVolume_TA_0.Goal_TA_53")]),
        # My goal: stat event and counter in the same frame.
        _frame(100.0, upd=[_stat("StatEvents.Events.Goal"), _upd(5, "TAGame.PRI_TA:MatchGoals", {"Int": 1})]),
        # A stat event nobody's counter follows (e.g. cut off at the end): dropped.
        _frame(130.0, upd=[_stat("StatEvents.Events.Save")]),
    ]
    return {"objects": OBJECTS, "network_frames": {"frames": frames}}


def test_events_from_json_pairs_players():
    events = replays.events_from_json(_replay())
    assert [(e.time, e.kind, e.player, e.team, e.score) for e in events] == [
        (30.0, "save", "Rival", "blue", None),
        (60.0, "epic_save", "Me", "orange", None),
        (90.0, "goal", "Me", "orange", (0, 1)),
    ]


@pytest.mark.parametrize("name,expected", [
    ("2026-10-27 03-42-47.mp4", datetime(2026, 10, 27, 3, 42, 47).timestamp()),
    ("C:/Videos/2025-01-02_10-20-30.mkv", datetime(2025, 1, 2, 10, 20, 30).timestamp()),
])
def test_recording_start_from_obs_name(name, expected):
    assert replays.recording_start(name) == expected


def test_fix_text_undoes_cp1252_mojibake():
    assert replays._fix_text("narkO \u00e3\u0192\u201e.") == "narkO ツ."
    assert replays._fix_text("Froggy") == "Froggy"


def _goal(t, team, score):
    return ReplayEvent(t, "goal", "x", team, score)


def test_solve_offset_uses_matching_goals():
    replay_goals = [_goal(30, "blue", (1, 0)), _goal(200, "blue", (2, 0)), _goal(250, "orange", (2, 1))]
    # Video goals 600.4 s later (scoreboard reads land a bit late), one goal missed by OCR,
    # plus a 1-0 from another match that must not win.
    video = [ScoreGoal(630.9, "blue", (1, 0)), ScoreGoal(850.2, "orange", (2, 1)),
             ScoreGoal(1500.0, "blue", (1, 0))]
    offset, anchors = sync.solve_offset(replay_goals, video, rough=598.0)
    assert anchors == 2
    assert offset == pytest.approx(600.55, abs=0.01)


def test_solve_offset_ignores_far_candidates():
    assert sync.solve_offset([_goal(30, "blue", (1, 0))], [ScoreGoal(1500, "blue", (1, 0))], rough=100) == (None, 0)


def _info(rid, epoch, duration=330.0):
    return ReplayInfo(path="", id=rid, name="", map="", start_epoch=epoch, duration=duration,
                      score=(0, 0), owner="Me")


def _ticks(start_t, start_c, n):
    return [(start_t + i, start_c - i) for i in range(n)]


def test_clock_runs_split_at_freezes():
    # Kickoff at 5:00, run to a goal at 4:38, frozen, then the next kickoff (time skipped after the goal).
    ticks = [(0.0, 300)] + _ticks(7.5, 299, 22) + _ticks(40.5, 277, 10)
    runs = sync.clock_runs(ticks)
    assert [(r.ticks[0][1], r.ticks[-1][1], r.start) for r in runs] == [(299, 278, 7.5), (277, 268, 40.5)]


def _video_samples(run_ticks, offset, start, end, fps=sync.CLOCK_FPS):
    """What reading the video clock at ``fps`` would give for a run shifted by ``offset``."""
    out, t = [], start
    while t < end:
        shown = [c for rt, c in run_ticks if rt + offset <= t]
        if shown:
            out.append((round(t, 3), shown[-1]))
        t += 1 / fps
    return out


def test_solve_run_finds_sub_second_offset():
    run = sync.Run(_ticks(10.0, 250, 40))
    samples = _video_samples(run.ticks, 3.37, 13.4, 52.0)
    samples[5] = (samples[5][0], 199)  # a misread
    sync.solve_run(run, samples)
    assert run.offset == pytest.approx(3.37, abs=0.15)
    assert run.readings >= 30


def test_overtime_ticks_negative_and_form_their_own_run():
    objects = ["TAGame.GameEvent_Soccar_TA:SecondsRemaining", "TAGame.GameEvent_Soccar_TA:bOverTime"]
    clock = lambda v: {"actor_id": 2, "object_id": 0, "attribute": {"Int": v}}  # noqa: E731
    frames = [_frame(0.0), _frame(1.0, upd=[clock(2)]), _frame(2.0, upd=[clock(1)]), _frame(3.0, upd=[clock(0)]),
              _frame(10.0, upd=[{"actor_id": 2, "object_id": 1, "attribute": {"Boolean": True}}]),
              _frame(14.0, upd=[clock(1)]), _frame(15.0, upd=[clock(2)]), _frame(16.0, upd=[clock(3)])]
    ticks = replays.clock_ticks_from_json({"objects": objects, "network_frames": {"frames": frames}})
    assert ticks == [(1.0, 2), (2.0, 1), (3.0, 0), (14.0, -1), (15.0, -2), (16.0, -3)]
    assert [(r.start, r.end) for r in sync.clock_runs(ticks)] == [(1.0, 3.0), (14.0, 16.0)]


def test_runs_cannot_lock_onto_previous_match_clock():
    # Match B's last run is its final 0:32 -> 0:00. Match A, which ended just before B
    # started, shows the same clock values earlier in the video, inside B's window.
    b_runs = [sync.Run(_ticks(10.0, 300, 60)), sync.Run(_ticks(370.0, 32, 33))]
    true = 400.0
    samples = _video_samples(b_runs[0].ticks, true, 405, 475)
    samples += _video_samples(b_runs[1].ticks, true + 8, 770, 812)  # B's real ending
    samples += _video_samples(b_runs[1].ticks, -35.0, 330, 372)  # A's ending, clearer and earlier
    sync.solve_runs(b_runs, samples, rough=395.0)
    assert b_runs[0].offset == pytest.approx(true, abs=0.15)
    assert b_runs[1].offset == pytest.approx(true + 8, abs=0.15)


def test_to_video_uses_each_runs_offset():
    runs = [sync.Run(_ticks(7.5, 299, 22), offset=2.7), sync.Run(_ticks(40.5, 277, 52), offset=3.25)]
    m = sync.MatchSync(_info("a", 0), "clock", runs)
    assert m.to_video(20.0) == pytest.approx(22.7)
    assert m.to_video(29.0) == pytest.approx(31.7)  # goal just after the run's last tick
    assert m.to_video(60.0) == pytest.approx(63.25)
    assert m.to_video(2.0) == pytest.approx(4.7)  # before the first kickoff


def test_fill_gaps_borrows_previous_offset():
    runs = [sync.Run(_ticks(0, 300, 3)), sync.Run(_ticks(10, 290, 3), offset=2.0),
            sync.Run(_ticks(20, 280, 3)), sync.Run(_ticks(30, 270, 3), offset=4.0)]
    sync.fill_gaps(runs)
    assert [r.offset for r in runs] == [2.0, 2.0, 2.0, 4.0]


def test_sync_matches_clock_then_fallbacks():
    rec_start = 1_000_000.0
    ticks_a = [(0.0, 300)] + _ticks(7.5, 299, 60)
    found = [
        (_info("a", rec_start + 60, duration=80), [_goal(30, "blue", (1, 0))], ticks_a),
        (_info("b", rec_start + 600), [], []),  # no clock data, no goals: start time
        (_info("c", 0), [_goal(30, "blue", (1, 0))], []),  # no start time: goals
    ]
    truth = 64.3  # true offset of match a (start time says 60)
    samples = _video_samples(ticks_a[1:], truth, 60, 140)
    out = sync.sync_matches(found, rec_start, 1800, read_samples=lambda windows: samples,
                            read_goals=lambda: [ScoreGoal(91.5, "blue", (1, 0))])
    assert [(m.replay.id, m.source) for m in out] == [("a", "clock"), ("b", "start time"), ("c", "goals")]
    assert out[0].to_video(30.0) == pytest.approx(30 + truth, abs=0.15)
    assert out[1].offset == 600
    assert out[2].offset == pytest.approx(61.5)


def test_uncovered_gaps():
    assert sync.uncovered([(100, 400), (390, 700)], 1000) == [(0.0, 100), (700, 1000)]
    assert sync.uncovered([(0, 1000)], 1000) == []
