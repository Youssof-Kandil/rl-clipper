import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  fmt,
  STYLE_LABEL,
  TYPE_LABEL,
  type ClipEvent,
  type Cue,
  type Project,
  type SeqItem,
  type SeqKind,
  type Sequence,
  type Settings,
  type VerticalStyle,
} from "../api";
import { activeWord, drawCaption, drawFrame, type CaptionLook, type Look } from "../render";
import JobBar from "./JobBar";
import PublishPanel from "./PublishPanel";

interface Props {
  project: Project;
  kind: SeqKind;
  seq: Sequence;
  captions: Cue[];
  settings: Settings;
  onSeq: (change: Sequence | ((prev: Sequence) => Sequence)) => void;
  onCaptions: (change: Cue[] | ((prev: Cue[]) => Cue[])) => void;
  onSettings: (patch: Settings) => void;
  onError: (msg: string) => void;
  onRefresh: () => void;
  /** Open Settings at Accounts (connect YouTube / TikTok). */
  onSetupPosting: () => void;
}

export const newItem = (e: ClipEvent): SeqItem => ({
  id: Math.random().toString(36).slice(2, 10),
  event_id: e.id,
  start: e.start,
  end: e.end,
  crop_x: e.crop_x ?? 0.5,
  style: e.style ?? null,
});

const newCue = (start: number, end: number, text: string): Cue => ({
  id: Math.random().toString(36).slice(2, 10),
  start: round(start),
  end: round(end),
  text,
});

const round = (t: number) => Math.round(t * 100) / 100;
const len = (i: SeqItem) => i.end - i.start;

export default function SequenceView({ project, kind, seq, captions, settings, onSeq, onCaptions, onSettings, onError, onRefresh, onSetupPosting }: Props) {
  const tiktok = kind === "tiktok";
  const events = useMemo(() => new Map(project.events.map((e) => [e.id, e])), [project.events]);
  const items = seq.items.filter((i) => events.has(i.event_id));
  const offsets = useMemo(() => {
    let t = 0;
    return items.map((i) => {
      const at = t;
      t += len(i);
      return at;
    });
  }, [items]);
  const total = items.reduce((s, i) => s + len(i), 0);
  const [selectedId, setSelectedId] = useState<string | null>(items[0]?.id ?? null);
  const selected = items.find((i) => i.id === selectedId) ?? null;
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [model, setModel] = useState<{ model: string; ready: boolean; size: string } | null>(null);
  const [modelJob, setModelJob] = useState<string | null>(null);

  const pre = Number(settings.pre_seconds ?? 10);
  const post = Number(settings.post_seconds ?? 10);
  const defaultStyle = (settings.vertical_style as VerticalStyle) ?? "focus45";
  const captionLook: CaptionLook = {
    size: Number(settings.caption_size ?? 78),
    position: (settings.caption_position as CaptionLook["position"]) ?? "lower",
    upper: Boolean(settings.caption_upper),
    highlight: settings.caption_highlight !== false,
    color: String(settings.caption_color ?? "#2EA8FF"),
  };
  const showCaptions = seq.captions;

  const setItems = (next: SeqItem[]) => onSeq((s) => ({ ...s, items: next }));
  const editItems = (fn: (items: SeqItem[]) => SeqItem[]) => onSeq((s) => ({ ...s, items: fn(s.items) }));
  const patchItem = (id: string, patch: Partial<SeqItem>) => editItems((its) => its.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  const removeItem = (id: string) => editItems((its) => its.filter((i) => i.id !== id));

  // ---------------------------------------------------------------- player
  // Two videos take turns: while one plays an item, the other waits on the next item's
  // first frame, so cuts between clips don't stall.
  const videoA = useRef<HTMLVideoElement>(null);
  const videoB = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const play = useRef({ active: 0, idx: 0, playing: false });
  const live = useRef({ items, offsets, captions, showCaptions, settings, captionLook });
  live.current = { items, offsets, captions, showCaptions, settings, captionLook };
  const videos = () => [videoA.current!, videoB.current!];

  const lookFor = (item: SeqItem): Look => ({
    vertical: tiktok,
    style: item.style ?? ((live.current.settings.vertical_style as VerticalStyle) || "focus45"),
    cropX: item.crop_x,
    zoom: Number(live.current.settings.vertical_zoom ?? 1),
    blur: Number(live.current.settings.vertical_blur ?? 30),
    sharp: Number(live.current.settings.vertical_sharp ?? 0.55),
  });

  const prepare = (slot: number, idx: number) => {
    const v = videos()[slot];
    const it = live.current.items[idx];
    if (v && it) v.currentTime = it.start;
  };

  const seekTo = (g: number) => {
    const { items: its, offsets: offs } = live.current;
    if (!its.length) return;
    g = Math.min(Math.max(g, 0), Math.max(offs[offs.length - 1] + len(its[its.length - 1]) - 0.05, 0));
    let idx = offs.findIndex((o, i) => g >= o && g < o + len(its[i]));
    if (idx < 0) idx = its.length - 1;
    const p = play.current;
    p.idx = idx;
    const v = videos()[p.active];
    v.currentTime = its[idx].start + (g - offs[idx]);
    prepare(1 - p.active, idx + 1);
    setTime(g);
  };

  const pause = () => {
    play.current.playing = false;
    videos().forEach((v) => v.pause());
    setPlaying(false);
  };

  const start = () => {
    const { items: its, offsets: offs } = live.current;
    if (!its.length) return;
    const p = play.current;
    const v = videos()[p.active];
    const it = its[p.idx];
    if (!it || (p.idx === its.length - 1 && v.currentTime >= it.end - 0.05)) seekTo(0);
    videos().forEach((x, i) => (x.muted = i !== p.active));
    p.playing = true;
    setPlaying(true);
    videos()[p.active].play().catch(() => pause());
    void offs;
  };

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const p = play.current;
      const { items: its, offsets: offs, captions: cues, showCaptions: caps, captionLook: look } = live.current;
      const vs = videos();
      const v = vs[p.active];
      const it = its[p.idx];
      if (v && it) {
        if (p.playing) {
          if (v.currentTime >= it.end - 0.03) {
            if (p.idx + 1 < its.length) {
              const next = vs[1 - p.active];
              next.muted = false;
              next.play().catch(() => {});
              v.pause();
              v.muted = true;
              p.active = 1 - p.active;
              p.idx += 1;
              prepare(1 - p.active, p.idx + 1);
            } else {
              pause();
            }
          } else if (v.currentTime < it.start - 0.3) {
            v.currentTime = it.start;
          }
        }
        const cur = vs[p.active];
        const item = its[p.idx];
        const ctx = canvas.current?.getContext("2d");
        if (ctx && item) {
          drawFrame(ctx, cur, lookFor(item));
          if (caps) {
            const t = cur.currentTime;
            const cue = cues.find((c) => c.start <= t && t < c.end && c.end > item.start && c.start < item.end);
            if (cue) drawCaption(ctx, cue.text, look, activeWord(cue, t));
          }
          if (p.playing) setTime(offs[p.idx] + Math.max(cur.currentTime - item.start, 0));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-cue after the timeline changes (reorder / trim / add / remove).
  const shape = items.map((i) => `${i.id}:${i.start}:${i.end}`).join("|");
  useEffect(() => {
    if (!play.current.playing) seekTo(Math.min(time, Math.max(total - 0.05, 0)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, project.proxy_ready]);

  // Space toggles playback.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === " ") {
        e.preventDefault();
        play.current.playing ? pause() : start();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const selectAndSeek = (id: string) => {
    setSelectedId(id);
    const idx = items.findIndex((i) => i.id === id);
    if (idx >= 0 && !(time >= offsets[idx] && time < offsets[idx] + len(items[idx]))) seekTo(offsets[idx]);
  };

  // ---------------------------------------------------------------- captions
  // Re-check when the chosen model changes (Settings) and after a transcription, which
  // downloads a missing model itself.
  const transcribeStatus = project.job_status.transcribe?.status;
  const loadModelStatus = () =>
    api
      .captionStatus()
      .then(setModel)
      .catch(() => setModel(null));
  useEffect(() => {
    if (tiktok || showCaptions) loadModelStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tiktok, showCaptions, settings.caption_model, transcribeStatus]);

  useEffect(() => {
    if (!modelJob) return;
    const t = setInterval(async () => {
      const job = await api.job(modelJob);
      if (job.status === "done") {
        loadModelStatus();
        setModelJob(null);
      } else if (job.status === "error" || job.status === "cancelled") {
        onError(job.error || "Model download failed");
        setModelJob(null);
      }
    }, 1500);
    return () => clearInterval(t);
  }, [modelJob, onError]);

  const transcribe = async (ids?: string[]) => {
    try {
      await api.transcribe(project.id, ids);
      onRefresh();
    } catch (e) {
      onError(String((e as Error).message));
    }
  };

  const patchCue = (id: string, patch: Partial<Cue>) => onCaptions((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const playheadSource = () => {
    const idx = play.current.idx;
    const it = items[idx];
    return it ? it.start + (time - offsets[idx]) : null;
  };

  const exportJob = project.job_status[`export_${kind}`];
  const exporting = exportJob && ["queued", "running"].includes(exportJob.status);
  const transcribeJob = project.job_status.transcribe;
  const transcribing = transcribeJob && ["queued", "running"].includes(transcribeJob.status);

  const exportDir = String(settings.export_dir ?? "");
  // The first export asks where files should go (unless a folder is already set).
  const [askFolder, setAskFolder] = useState<"compiled" | "separate" | null>(null);

  const runExport = async (mode: "compiled" | "separate") => {
    if (!exportDir && !settings.export_dir_chosen) {
      setAskFolder(mode);
      return;
    }
    try {
      await api.exportSequence(project.id, kind, mode);
      onRefresh();
    } catch (e) {
      onError(String((e as Error).message));
    }
  };

  /** Save the export folder now (not debounced: an export may start right after). */
  const setExportDir = async (dir: string) => {
    const patch = { export_dir: dir, export_dir_chosen: true };
    await api.saveSettings(patch);
    onSettings(patch);
  };

  const pickExportDir = async () => {
    try {
      const { path } = await api.pickFolder();
      if (!path) return false;
      await setExportDir(path);
      return true;
    } catch (e) {
      onError(String((e as Error).message));
      return false;
    }
  };

  const answerFolder = async (choice: "pick" | "project") => {
    const mode = askFolder!;
    if (choice === "pick") {
      if (!(await pickExportDir())) return; // dialog cancelled: keep asking
    } else {
      await setExportDir("");
    }
    setAskFolder(null);
    try {
      await api.exportSequence(project.id, kind, mode);
      onRefresh();
    } catch (e) {
      onError(String((e as Error).message));
    }
  };

  const inSeq = new Set(seq.items.map((i) => i.event_id));
  const ticked = project.events.filter((e) => e.selected && !inSeq.has(e.id));
  const selectedEvent = selected ? events.get(selected.event_id)! : null;
  const selectedCues = selected ? captions.filter((c) => c.end > selected.start && c.start < selected.end) : [];

  return (
    <div className={`seq ${kind}`}>
      <div className="seq-top">
        <section className="card seq-player">
          <div className="seq-canvas-wrap">
            <canvas
              ref={canvas}
              width={tiktok ? 540 : 960}
              height={tiktok ? 960 : 540}
              className="seq-canvas"
              onClick={() => (playing ? pause() : start())}
            />
            {!items.length && <div className="seq-empty">Add clips from the list on the right →</div>}
            {!project.proxy_ready && <div className="seq-empty">Preview is still rendering…</div>}
          </div>
          {project.proxy_ready && (
            <>
              <video ref={videoA} src={`/api/projects/${project.id}/proxy`} preload="auto" playsInline hidden />
              <video ref={videoB} src={`/api/projects/${project.id}/proxy`} preload="auto" playsInline hidden muted />
            </>
          )}
          <div className="seq-controls">
            <button className="primary" onClick={() => (playing ? pause() : start())} disabled={!items.length || !project.proxy_ready}>
              {playing ? "❚❚ Pause" : "▶ Play"}
            </button>
            <span className="mono">
              {fmt(time, true)} / {fmt(total, true)}
            </span>
            {tiktok && total > 180 && <span className="warn">over 3 min</span>}
            {tiktok && total > 60 && total <= 180 && <span className="muted">over 60 s</span>}
          </div>
        </section>

        <div className="seq-side">
          <section className="card seq-export">
            <h2>{tiktok ? "TikTok · 9:16" : "YouTube · 16:9"}</h2>
            <p className="muted">
              {items.length} clip{items.length === 1 ? "" : "s"} · {total.toFixed(1)}s · {tiktok ? `1080×1920, ${STYLE_LABEL[defaultStyle]} by default` : "as recorded"} · audio: Mixed, Game, Mic
            </p>
            <label className="check">
              <input type="checkbox" checked={showCaptions} onChange={(e) => onSeq({ ...seq, captions: e.target.checked })} />
              Burn in captions
            </label>
            <div className="row">
              <button className="primary" onClick={() => runExport("compiled")} disabled={!items.length || !!exporting}>
                Export as one video
              </button>
              <button onClick={() => runExport("separate")} disabled={!items.length || !!exporting}>
                Export separate clips
              </button>
              <button className="ghost small" onClick={() => api.openExports(project.id)}>
                Open folder
              </button>
            </div>
            <div className="export-dest">
              <span className="muted">Saves to</span>
              <span className="path mono" title={exportDir || "Inside the project (data/projects/…/exports)"}>
                {exportDir || "the project folder"}
              </span>
              <button className="ghost small" onClick={pickExportDir}>
                Change…
              </button>
              <span className="grow" />
              <span className="muted">Size</span>
              <select
                className="small-select"
                value={String(settings.export_quality ?? "balanced")}
                onChange={(e) => onSettings({ export_quality: e.target.value })}
                title="Best ≈ 4 MB/s · Balanced ≈ 3 MB/s · Small (HEVC) ≈ 2 MB/s"
              >
                <option value="best">Best</option>
                <option value="balanced">Balanced</option>
                <option value="small">Small (HEVC)</option>
              </select>
            </div>
            {exportJob && <JobBar label="Export" job={exportJob} onCancel={() => api.cancelJob(exportJob.id)} files />}
          </section>

          <PublishPanel project={project} onRefresh={onRefresh} onError={onError} onSetup={onSetupPosting} />

          {selected && selectedEvent && (
            <section className="card seq-inspector">
              <div className="row spread">
                <h2>
                  <span className={`dot t-${selectedEvent.type}`} /> {TYPE_LABEL[selectedEvent.type]}
                  {selectedEvent.player && <span className="cl-player inline"> {selectedEvent.player}</span>}
                </h2>
                <button className="ghost small" onClick={() => removeItem(selected.id)}>
                  Remove from timeline
                </button>
              </div>
              <div className="inout compact">
                <Nudge label="In" value={selected.start} onChange={(v) => trimItem(selected, v, selected.end)} />
                <Nudge label="Out" value={selected.end} onChange={(v) => trimItem(selected, selected.start, v)} />
                <span className="muted">{len(selected).toFixed(1)}s · moment at {fmt(selectedEvent.time)}</span>
              </div>
              {tiktok && (
                <div className="seq-framing">
                  <label>
                    9:16 style
                    <select value={selected.style ?? ""} onChange={(e) => patchItem(selected.id, { style: (e.target.value || null) as VerticalStyle | null })}>
                      <option value="">{STYLE_LABEL[defaultStyle]} (TikTok format)</option>
                      {(Object.keys(STYLE_LABEL) as VerticalStyle[])
                        .filter((s) => s !== defaultStyle)
                        .map((s) => (
                          <option key={s} value={s}>
                            {STYLE_LABEL[s]}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="grow">
                    Crop position
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.005}
                      value={selected.crop_x}
                      onChange={(e) => patchItem(selected.id, { crop_x: Number(e.target.value) })}
                    />
                  </label>
                  <button className="ghost small" onClick={() => patchItem(selected.id, { crop_x: 0.5 })} disabled={selected.crop_x === 0.5}>
                    Centre
                  </button>
                </div>
              )}

              {showCaptions && (
                <div className="seq-captions">
                  <div className="row spread">
                    <h3>Captions</h3>
                    <div className="row">
                      <button
                        className="small"
                        onClick={() => {
                          const t = playheadSource();
                          const at = t !== null && t >= selected.start && t < selected.end ? t : selected.start;
                          onCaptions((cs) => [...cs, newCue(at, Math.min(at + 1.2, selected.end), "New line")].sort((a, b) => a.start - b.start));
                        }}
                      >
                        + Line at playhead
                      </button>
                      <button className="small" onClick={() => transcribe([selected.id])} disabled={!!transcribing}>
                        Transcribe this clip
                      </button>
                    </div>
                  </div>
                  {!selectedCues.length && <p className="muted">No captions for this clip yet.</p>}
                  <ul className="cues">
                    {selectedCues.map((c) => (
                      <li key={c.id}>
                        <span className="mono muted">{(c.start - selected.start).toFixed(1)}s</span>
                        <input value={c.text} onChange={(e) => patchCue(c.id, { text: e.target.value })} />
                        <span className="cue-nudge">
                          <button className="ghost small" title="Start earlier" onClick={() => patchCue(c.id, { start: round(c.start - 0.1) })}>
                            ⇤
                          </button>
                          <button className="ghost small" title="Start later" onClick={() => patchCue(c.id, { start: round(Math.min(c.start + 0.1, c.end - 0.1)) })}>
                            ⇥
                          </button>
                          <button className="ghost small" title="End earlier" onClick={() => patchCue(c.id, { end: round(Math.max(c.end - 0.1, c.start + 0.1)) })}>
                            ⇤
                          </button>
                          <button className="ghost small" title="End later" onClick={() => patchCue(c.id, { end: round(c.end + 0.1) })}>
                            ⇥
                          </button>
                        </span>
                        <button className="ghost small" title="Delete line" onClick={() => onCaptions((cs) => cs.filter((x) => x.id !== c.id))}>
                          ✕
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {showCaptions && (
            <section className="card seq-caption-look">
              <div className="row spread">
                <h3>Caption look</h3>
                <button className="small" onClick={() => transcribe()} disabled={!items.length || !!transcribing}>
                  Transcribe all clips
                </button>
              </div>
              {model && (
                <div className="model-line">
                  <span className="muted">Speech model</span>
                  <b>{model.model}</b>
                  {model.ready ? (
                    <span className="muted">downloaded</span>
                  ) : modelJob ? (
                    <span className="muted">downloading {model.size}…</span>
                  ) : (
                    <>
                      <span className="muted">not downloaded yet ({model.size}); transcribing downloads it first</span>
                      <button
                        className="ghost small"
                        onClick={async () => {
                          try {
                            setModelJob((await api.downloadCaptionModel()).id);
                          } catch (e) {
                            onError(String((e as Error).message));
                          }
                        }}
                      >
                        Download now
                      </button>
                    </>
                  )}
                </div>
              )}
              <div className="row">
                <label>
                  Size
                  <input type="number" min={40} max={140} step={2} value={captionLook.size} onChange={(e) => onSettings({ caption_size: Number(e.target.value) })} />
                </label>
                <label>
                  Position
                  <select value={captionLook.position} onChange={(e) => onSettings({ caption_position: e.target.value })}>
                    <option value="upper">Upper</option>
                    <option value="middle">Middle</option>
                    <option value="lower">Lower</option>
                  </select>
                </label>
                <label className="check">
                  <input type="checkbox" checked={captionLook.upper} onChange={(e) => onSettings({ caption_upper: e.target.checked })} />
                  ALL CAPS
                </label>
              </div>
              <div className="row">
                <label className="check">
                  <input type="checkbox" checked={captionLook.highlight} onChange={(e) => onSettings({ caption_highlight: e.target.checked })} />
                  Highlight the word being said
                </label>
                <input
                  type="color"
                  className="swatch-input"
                  value={captionLook.color}
                  onChange={(e) => onSettings({ caption_color: e.target.value.toUpperCase() })}
                  disabled={!captionLook.highlight}
                  title="Highlight colour"
                />
                <label>
                  Max words per caption
                  <input
                    type="number"
                    min={1}
                    max={16}
                    value={Number(settings.caption_max_words ?? 8)}
                    onChange={(e) => onSettings({ caption_max_words: Number(e.target.value) })}
                    title="Used the next time you transcribe"
                  />
                </label>
              </div>
              {transcribeJob && transcribeJob.status !== "done" && <JobBar label="Captions" job={transcribeJob} onCancel={() => api.cancelJob(transcribeJob.id)} />}
              {transcribeJob?.status === "done" && (
                <p className="muted">
                  Last transcription: {transcribeJob.result.count ?? 0} lines on {(transcribeJob.result.device ?? "cpu").toUpperCase()}. Edit any line in the clip panel above.
                </p>
              )}
            </section>
          )}

          <section className="card seq-add">
            <div className="row spread">
              <h3>Add clips</h3>
              <button className="small" onClick={() => editItems((its) => [...its, ...ticked.map(newItem)])} disabled={!ticked.length}>
                Add all ticked ({ticked.length})
              </button>
            </div>
            <ul className="seq-add-list">
              {project.events.map((e) => (
                <li key={e.id} className={inSeq.has(e.id) ? "in" : ""}>
                  <span className={`dot t-${e.type}`} />
                  <span className="grow">
                    {TYPE_LABEL[e.type]}
                    {e.player && <span className="muted"> · {e.player}</span>}
                  </span>
                  <span className="mono muted">{fmt(e.time)}</span>
                  <button className="ghost small" onClick={() => editItems((its) => [...its, newItem(e)])} title="Add to the end of the timeline">
                    {inSeq.has(e.id) ? "+ again" : "+ Add"}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </div>

      {askFolder && (
        <div className="modal-bg" onClick={() => setAskFolder(null)}>
          <div className="modal small" onClick={(e) => e.stopPropagation()}>
            <h2>Where should exports go?</h2>
            <p className="muted">Pick a folder for your {tiktok ? "TikToks" : "YouTube clips"} (and every export after this). You can change it any time next to the export buttons or in Settings.</p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => answerFolder("project")}>
                Keep them in the project folder
              </button>
              <button className="primary" onClick={() => answerFolder("pick")}>
                Choose folder…
              </button>
            </div>
          </div>
        </div>
      )}

      <Track
        items={items}
        offsets={offsets}
        total={total}
        time={time}
        events={events}
        selectedId={selectedId}
        cues={showCaptions ? captions : []}
        thumb={(e) => (e.thumb ? `/api/projects/${project.id}/thumbs/${e.thumb}` : null)}
        window={(e) => [Math.max(e.time - pre, 0), Math.min(e.time + post, project.info.duration)]}
        onSelect={selectAndSeek}
        onSeek={seekTo}
        onItems={setItems}
      />
    </div>
  );

  function trimItem(item: SeqItem, start: number, end: number) {
    const e = events.get(item.event_id)!;
    const lo = Math.max(e.time - pre, 0);
    const hi = Math.min(e.time + post, project.info.duration);
    start = Math.min(Math.max(start, lo), end - 0.5);
    end = Math.max(Math.min(end, hi), start + 0.5);
    patchItem(item.id, { start: round(start), end: round(end) });
  }
}

function Nudge({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <span className="muted">{label}</span>
      <b className="mono">{fmt(value, true)}</b>
      <button className="small" onClick={() => onChange(value - 0.5)}>
        −0.5
      </button>
      <button className="small" onClick={() => onChange(value - 0.1)}>
        −0.1
      </button>
      <button className="small" onClick={() => onChange(value + 0.1)}>
        +0.1
      </button>
      <button className="small" onClick={() => onChange(value + 0.5)}>
        +0.5
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- timeline

interface TrackProps {
  items: SeqItem[];
  offsets: number[];
  total: number;
  time: number;
  events: Map<string, ClipEvent>;
  selectedId: string | null;
  cues: Cue[];
  thumb: (e: ClipEvent) => string | null;
  /** The furthest an item may be trimmed out to (its event's window). */
  window: (e: ClipEvent) => [number, number];
  onSelect: (id: string) => void;
  onSeek: (t: number) => void;
  onItems: (items: SeqItem[]) => void;
}

type Drag = { mode: "move" | "in" | "out" | "seek"; id: string; x: number; moved: boolean; start: number; end: number };

function Track({ items, offsets, total, time, events, selectedId, cues, thumb, window: win, onSelect, onSeek, onItems }: TrackProps) {
  const [pps, setPps] = useState(40); // pixels per second
  const lane = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const latest = useRef({ items, offsets, pps });
  latest.current = { items, offsets, pps };

  const xToTime = (clientX: number) => {
    const r = lane.current!.getBoundingClientRect();
    return (clientX - r.left + lane.current!.scrollLeft - 12) / latest.current.pps;
  };

  useEffect(() => {
    if (!drag) return;
    const move = (ev: PointerEvent) => {
      const { items: its, offsets: offs, pps: scale } = latest.current;
      const dx = ev.clientX - drag.x;
      if (drag.mode === "seek") {
        onSeek(xToTime(ev.clientX));
        return;
      }
      if (!drag.moved && Math.abs(dx) < 4) return;
      drag.moved = true;
      const idx = its.findIndex((i) => i.id === drag.id);
      if (idx < 0) return;
      const item = its[idx];
      if (drag.mode === "move") {
        // Live reorder: the dragged clip goes before the first clip whose middle is right of the pointer.
        const t = xToTime(ev.clientX);
        const others = its.filter((i) => i.id !== drag.id);
        const otherOffs = its.map((_, k) => offs[k]).filter((_, k) => k !== idx);
        let to = others.findIndex((o, k) => otherOffs[k] + len(o) / 2 > t - (k >= idx ? len(item) : 0));
        if (to < 0) to = others.length;
        if (to !== idx) onItems([...others.slice(0, to), item, ...others.slice(to)]);
        return;
      }
      const e = events.get(item.event_id)!;
      const [lo, hi] = win(e);
      const next =
        drag.mode === "in"
          ? { start: round(Math.min(Math.max(drag.start + dx / scale, lo), item.end - 0.5)) }
          : { end: round(Math.max(Math.min(drag.end + dx / scale, hi), item.start + 0.5)) };
      onItems(its.map((i) => (i.id === drag.id ? { ...i, ...next } : i)));
    };
    const up = () => {
      if (drag.mode === "move" && !drag.moved) onSelect(drag.id);
      setDrag(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag]);

  const width = Math.max(total * pps + 80, 300);
  const ticks = [];
  const step = pps >= 60 ? 1 : pps >= 25 ? 2 : 5;
  for (let t = 0; t <= total + 0.001; t += step) ticks.push(t);

  return (
    <section className="card seq-track">
      <div className="row spread">
        <h3>
          Timeline <span className="muted">· drag clips to reorder, drag their edges to trim</span>
        </h3>
        <label className="zoom">
          Zoom
          <input type="range" min={12} max={140} value={pps} onChange={(e) => setPps(Number(e.target.value))} />
        </label>
      </div>
      <div className="lane" ref={lane}>
        <div className="lane-inner" style={{ width }}>
          <div
            className="ruler"
            onPointerDown={(e) => {
              onSeek(xToTime(e.clientX));
              setDrag({ mode: "seek", id: "", x: e.clientX, moved: false, start: 0, end: 0 });
            }}
          >
            {ticks.map((t) => (
              <span key={t} style={{ left: 12 + t * pps }}>
                {fmt(t)}
              </span>
            ))}
          </div>
          <div className="clips-row">
            {items.map((item, k) => {
              const e = events.get(item.event_id)!;
              const src = thumb(e);
              return (
                <div
                  key={item.id}
                  className={`block t-${e.type} ${item.id === selectedId ? "active" : ""} ${drag?.id === item.id && drag.moved ? "dragging" : ""}`}
                  style={{ left: 12 + offsets[k] * pps, width: Math.max(len(item) * pps - 2, 8) }}
                  onPointerDown={(ev) => {
                    ev.preventDefault();
                    setDrag({ mode: "move", id: item.id, x: ev.clientX, moved: false, start: item.start, end: item.end });
                  }}
                >
                  {src && <img src={src} alt="" draggable={false} />}
                  <span className="block-label">
                    {k + 1}. {TYPE_LABEL[e.type]}
                    {e.player ? ` · ${e.player}` : ""}
                  </span>
                  <span className="block-len">{len(item).toFixed(1)}s</span>
                  <span
                    className="edge in"
                    onPointerDown={(ev) => {
                      ev.stopPropagation();
                      ev.preventDefault();
                      onSelect(item.id);
                      setDrag({ mode: "in", id: item.id, x: ev.clientX, moved: false, start: item.start, end: item.end });
                    }}
                  />
                  <span
                    className="edge out"
                    onPointerDown={(ev) => {
                      ev.stopPropagation();
                      ev.preventDefault();
                      onSelect(item.id);
                      setDrag({ mode: "out", id: item.id, x: ev.clientX, moved: false, start: item.start, end: item.end });
                    }}
                  />
                </div>
              );
            })}
          </div>
          {cues.length > 0 && (
            <div className="caps-row">
              {items.flatMap((item, k) =>
                cues
                  .filter((c) => c.end > item.start && c.start < item.end)
                  .map((c) => {
                    const a = Math.max(c.start, item.start) - item.start + offsets[k];
                    const b = Math.min(c.end, item.end) - item.start + offsets[k];
                    return (
                      <div
                        key={`${item.id}-${c.id}`}
                        className="cap"
                        style={{ left: 12 + a * pps, width: Math.max((b - a) * pps - 1, 4) }}
                        title={c.text}
                        onClick={() => {
                          onSelect(item.id);
                          onSeek(a + 0.01);
                        }}
                      >
                        {c.text}
                      </div>
                    );
                  }),
              )}
            </div>
          )}
          <div className="seq-playhead" style={{ left: 12 + time * pps }} />
        </div>
      </div>
    </section>
  );
}
