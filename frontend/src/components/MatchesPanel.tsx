import { useEffect, useState } from "react";
import { api, fmt, type Project, type ReplayInfo, type ReplayStatus } from "../api";

interface Props {
  project: Project;
  analyzing: boolean;
  onApplied: (p: Project) => void;
  onError: (msg: string) => void;
}

const SOURCE_LABEL = {
  clock: "synced on the match clock",
  goals: "synced on goals",
  "start time": "synced on start time (≈)",
  none: "couldn't place in the video",
};

/** Rocket League replays saved during this recording, and how each was lined up. */
export default function MatchesPanel({ project, analyzing, onApplied, onError }: Props) {
  const [status, setStatus] = useState<ReplayStatus | null>(null);
  const [found, setFound] = useState<ReplayInfo[] | null>(null);
  const [ignored, setIgnored] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const s = await api.replayStatus();
    setStatus(s);
    if (!s.rrrocket) return setFound([]);
    const list = await api.replays(project.id);
    setFound(list);
    setIgnored(new Set(list.filter((r) => r.ignored).map((r) => r.id)));
  };

  useEffect(() => {
    refresh().catch((e) => onError(String((e as Error).message)));
    // Re-list when an analysis finishes: that's when new syncs exist.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, analyzing]);

  const install = async () => {
    setBusy(true);
    try {
      await api.installRrrocket();
      await refresh();
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    try {
      onApplied(await api.chooseReplays(project.id, [...ignored]));
    } catch (e) {
      onError(String((e as Error).message));
    }
  };

  if (!status || found === null) return null;

  const syncs = new Map((project.matches ?? []).map((m) => [m.replay.id, m]));
  const saved = new Set((found ?? []).filter((r) => r.ignored).map((r) => r.id));
  const changed = saved.size !== ignored.size || [...ignored].some((id) => !saved.has(id));

  return (
    <section className="card cliplist matches">
      <div className="cliplist-head">
        <h2>Matches</h2>
        {changed && (
          <button className="small primary" onClick={apply} disabled={analyzing}>
            Apply &amp; re-analyze
          </button>
        )}
      </div>
      {!status.rrrocket ? (
        <p className="muted">
          Reading replays needs the rrrocket parser (open source, ~2 MB).{" "}
          <button className="small" onClick={install} disabled={busy}>
            {busy ? "Downloading…" : `Download rrrocket ${status.version}`}
          </button>
        </p>
      ) : !status.demos_dir ? (
        <p className="muted">Rocket League's replay folder wasn't found. Set it in Settings.</p>
      ) : found.length === 0 ? (
        <p className="muted">
          No saved replays from this recording, so clips come from the on-screen scan (your own plays only). Press{" "}
          <b>Save Replay</b> after each match to get every player's goals and saves, timed exactly.
        </p>
      ) : (
        <ul>
          {found.map((r, i) => {
            const m = syncs.get(r.id);
            const use = !ignored.has(r.id);
            return (
              <li key={r.id} className={use ? "" : "other"}>
                <input
                  type="checkbox"
                  checked={use}
                  aria-label="Use this replay"
                  onChange={() => {
                    const next = new Set(ignored);
                    use ? next.add(r.id) : next.delete(r.id);
                    setIgnored(next);
                  }}
                />
                <span className="cl-type">
                  Match {i + 1} · {r.map.replace(/_p$/i, "").replace(/_/g, " ")}
                  <span className="team blue">{r.score[0]}</span>
                  <span className="team orange">{r.score[1]}</span>
                  <span className="cl-player">
                    {m?.span
                      ? `${fmt(m.span[0])}–${fmt(m.span[1])} · ${SOURCE_LABEL[m.source]}${m.anchors ? ` (${m.anchors} ${m.source === "clock" ? "readings" : "goals"})` : ""}`
                      : m
                        ? SOURCE_LABEL.none
                        : use
                          ? "not used yet: re-analyze"
                          : "ignored"}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
