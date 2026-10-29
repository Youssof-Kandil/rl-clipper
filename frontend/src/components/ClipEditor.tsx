import { useEffect, useRef, useState } from "react";
import { fmt, STYLE_LABEL, TYPE_LABEL, type ClipEvent, type EventPatch, type Frame, type Project, type VerticalStyle } from "../api";

interface Framing {
  frame: Frame;
  style: VerticalStyle;
  zoom: number;
  sharp: number;
}

interface Props {
  project: Project;
  event: ClipEvent;
  /** Seconds before/after the event: the default clip and the trim limit. */
  defaults: [number, number];
  /** Export framing from Settings; the clip can override frame and style. */
  framing: Framing;
  onLocal: (patch: Partial<ClipEvent>) => void;
  onSave: (patch: EventPatch) => void;
  onTime: (t: number) => void;
}

type Handle = "start" | "end" | "seek";

export default function ClipEditor({ project, event, defaults, framing, onLocal, onSave, onTime }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(event.start);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [drag, setDrag] = useState<Handle | null>(null);
  // Refs mirror the latest values for the rAF loop and global listeners.
  const clip = useRef({ start: event.start, end: event.end });
  clip.current = { start: event.start, end: event.end };
  const loopRef = useRef(loop);
  loopRef.current = loop;

  const duration = project.info.duration;
  const lo = Math.max(event.time - defaults[0], 0);
  const hi = Math.min(event.time + defaults[1], duration);
  const span = Math.max(hi - lo, 0.001);
  const pct = (t: number) => `${((t - lo) / span) * 100}%`;
  const clamp = (t: number) => Math.min(Math.max(t, lo), hi);

  const seek = (t: number) => {
    const v = video.current;
    t = clamp(t);
    if (v) v.currentTime = t;
    setNow(t);
    onTime(t);
  };

  // Jump to the clip's start whenever a new clip is opened / the preview appears.
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const go = () => seek(event.start);
    if (v.readyState >= 1) go();
    else v.addEventListener("loadedmetadata", go, { once: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event.id, project.proxy_ready]);

  // Smooth playhead + stop/loop at the out point and keep playback inside the window.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = video.current;
      if (v && !v.paused) {
        const { start, end } = clip.current;
        if (v.currentTime >= end) {
          if (loopRef.current) v.currentTime = start;
          else {
            v.pause();
            v.currentTime = end;
          }
        } else if (v.currentTime < lo - 0.05) {
          v.currentTime = start;
        }
        setNow(v.currentTime);
        onTime(v.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lo]);

  const playClip = () => {
    const v = video.current;
    if (!v) return;
    if (!v.paused) {
      v.pause();
      return;
    }
    if (v.currentTime < event.start || v.currentTime >= event.end - 0.05) v.currentTime = event.start;
    v.play();
  };

  const setIn = (t: number) => {
    t = Math.min(clamp(t), event.end - 0.5);
    onSave({ start: round(t) });
  };
  const setOut = (t: number) => {
    t = Math.max(clamp(t), event.start + 0.5);
    onSave({ end: round(t) });
  };

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || e.ctrlKey || e.metaKey) return;
      const t = video.current?.currentTime ?? now;
      const k = e.key.toLowerCase();
      if (k === " ") {
        e.preventDefault();
        playClip();
      } else if (k === "i") setIn(t);
      else if (k === "o") setOut(t);
      else if (k === "arrowleft") seek(t - (e.shiftKey ? 1 : 1 / 30));
      else if (k === "arrowright") seek(t + (e.shiftKey ? 1 : 1 / 30));
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Dragging the in/out handles or the playhead.
  useEffect(() => {
    if (!drag) return;
    const timeAt = (x: number) => {
      const r = bar.current!.getBoundingClientRect();
      return clamp(lo + ((x - r.left) / r.width) * span);
    };
    const move = (e: PointerEvent) => {
      const t = timeAt(e.clientX);
      if (drag === "start") onLocal({ start: round(Math.min(t, clip.current.end - 0.5)) });
      else if (drag === "end") onLocal({ end: round(Math.max(t, clip.current.start + 0.5)) });
      seek(t);
    };
    const up = () => {
      if (drag !== "seek") onSave({ start: clip.current.start, end: clip.current.end });
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

  const len = event.end - event.start;

  // 9:16 framing: same window maths as the export (media.vertical_crop).
  const { width: vw, height: vh } = project.info;
  const frame = event.frame ?? framing.frame;
  const style = event.style ?? framing.style;
  const vertical = frame === "9:16";
  const zoom = Math.min(Math.max(framing.zoom, 1), 2);
  // The box shows the sharp part: the 4:5 window for focus45, the 9:16 crop otherwise.
  const aspect = style === "focus45" ? 4 / 5 : 9 / 16;
  const boxW = Math.min(((vh / zoom) * aspect) / vw, 1); // fraction of the frame's width
  const boxH = 1 / zoom;
  const cropX = event.crop_x ?? 0.5;
  const boxLeft = Math.min(Math.max(cropX - boxW / 2, 0), 1 - boxW);
  const player = useRef<HTMLDivElement>(null);
  const [cropDrag, setCropDrag] = useState<{ x: number; crop: number } | null>(null);
  const latestCrop = useRef(cropX);
  latestCrop.current = cropX;

  useEffect(() => {
    if (!cropDrag) return;
    const move = (e: PointerEvent) => {
      const w = player.current!.getBoundingClientRect().width;
      const next = cropDrag.crop + (e.clientX - cropDrag.x) / w;
      // Keep the centre where the box can actually go.
      onLocal({ crop_x: round4(Math.min(Math.max(next, boxW / 2), 1 - boxW / 2)) });
    };
    const up = () => {
      onSave({ crop_x: latestCrop.current });
      setCropDrag(null);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cropDrag]);

  // Live stand-in for the focus blur: sharp oval in the middle, blurred towards the edges
  // (the same shape as the export's mask).
  const sharpY = Math.max(framing.sharp, 0.1) * 50;
  const focusMask = `radial-gradient(ellipse 62% ${sharpY}% at 50% 50%, transparent 100%, black 145%)`;

  return (
    <section className="card editor">
      <div className="editor-head">
        <h2>
          <span className={`dot t-${event.type}`} /> {TYPE_LABEL[event.type]} at {fmt(event.time)}
          {event.team && <span className={`team ${event.team}`}>{event.team}</span>}
        </h2>
        <label className="check">
          <input type="checkbox" checked={event.selected} onChange={() => onSave({ selected: !event.selected })} />
          Include in export
        </label>
      </div>

      <div className="player" ref={player} style={{ aspectRatio: `${vw} / ${vh}` }}>
        {vertical && style !== "fit" && (
          <div
            className={`crop-box ${cropDrag ? "dragging" : ""}`}
            style={{ left: `${boxLeft * 100}%`, width: `${boxW * 100}%`, top: `${((1 - boxH) / 2) * 100}%`, bottom: `${((1 - boxH) / 2) * 100}%` }}
            title="Drag to move the 9:16 crop"
            onPointerDown={(e) => {
              e.preventDefault();
              setCropDrag({ x: e.clientX, crop: cropX });
            }}
            onDoubleClick={() => onSave({ crop_x: 0.5 })}
          >
            {style === "focus" && <div className="focus-blur" style={{ maskImage: focusMask, WebkitMaskImage: focusMask }} />}
            <span className="crop-tag">{style === "focus45" ? "4:5 in focus · blurred 9:16 behind" : "9:16"} · drag to move</span>
          </div>
        )}
        {vertical && style === "fit" && <span className="fit-note">9:16 · whole frame, blurred fill above and below</span>}
        {project.proxy_ready ? (
          <video
            ref={video}
            src={`/api/projects/${project.id}/proxy`}
            preload="auto"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onClick={playClip}
          />
        ) : (
          <div className="player-wait">
            {event.thumb && <img src={`/api/projects/${project.id}/thumbs/${event.thumb}`} alt="" />}
            <span>Preview is still rendering…</span>
          </div>
        )}
      </div>

      <div className="framing">
        <span className="muted">Frame</span>
        <div className="seg">
          <button className={!vertical ? "on" : ""} onClick={() => onSave({ frame: "16:9" })} title="As recorded (YouTube)">
            16:9
          </button>
          <select
            className={`seg-select ${vertical ? "on" : ""}`}
            value={vertical ? style : ""}
            onChange={(e) => onSave({ frame: "9:16", style: e.target.value === framing.style ? "" : (e.target.value as VerticalStyle) })}
            title="9:16 (TikTok / Shorts / Reels)"
          >
            {!vertical && (
              <option value="" disabled>
                9:16 ▾
              </option>
            )}
            {(Object.keys(STYLE_LABEL) as VerticalStyle[]).map((s) => (
              <option key={s} value={s}>
                9:16 · {STYLE_LABEL[s]}
                {s === framing.style ? " (TikTok format)" : ""}
              </option>
            ))}
          </select>
        </div>
        {vertical && style !== "fit" && (
          <button className="ghost small" onClick={() => onSave({ crop_x: 0.5 })} disabled={cropX === 0.5}>
            Centre crop
          </button>
        )}
      </div>

      <div
        className="trim"
        ref={bar}
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).dataset.handle) return;
          setDrag("seek");
          const r = bar.current!.getBoundingClientRect();
          seek(lo + ((e.clientX - r.left) / r.width) * span);
        }}
      >
        <div className="trim-sel" style={{ left: pct(event.start), width: `${(len / span) * 100}%` }} />
        <div className="trim-event" style={{ left: pct(event.time) }} title="Detected moment" />
        <div className="trim-now" style={{ left: pct(now) }} />
        <div
          className="trim-handle in"
          data-handle="start"
          style={{ left: pct(event.start) }}
          onPointerDown={(e) => {
            e.stopPropagation();
            setDrag("start");
          }}
        />
        <div
          className="trim-handle out"
          data-handle="end"
          style={{ left: pct(event.end) }}
          onPointerDown={(e) => {
            e.stopPropagation();
            setDrag("end");
          }}
        />
        <span className="trim-label l">−{Math.round(event.time - lo)}s</span>
        <span className="trim-label r">+{Math.round(hi - event.time)}s</span>
      </div>

      <div className="controls">
        <button className="primary" onClick={playClip} disabled={!project.proxy_ready}>
          {playing ? "❚❚ Pause" : "▶ Play clip"}
        </button>
        <label className="check">
          <input type="checkbox" checked={loop} onChange={() => setLoop(!loop)} /> Loop
        </label>
        <span className="mono">
          {fmt(now, true)} <span className="muted">({(now - event.time >= 0 ? "+" : "") + (now - event.time).toFixed(1)}s)</span>
        </span>
        <span className="grow" />
        <button onClick={() => seek(event.time)} className="ghost small">
          Go to moment
        </button>
        <button
          className="ghost small"
          onClick={() => onSave({ start: round(Math.max(event.time - defaults[0], 0)), end: round(Math.min(event.time + defaults[1], duration)) })}
        >
          Reset
        </button>
      </div>

      <div className="inout">
        <div>
          <span className="muted">In</span>
          <b className="mono">{fmt(event.start, true)}</b>
          <button className="small" onClick={() => setIn(event.start - 0.5)}>−0.5</button>
          <button className="small" onClick={() => setIn(event.start + 0.5)}>+0.5</button>
          <button className="small" onClick={() => setIn(now)} title="Shortcut: I">Set to playhead [I]</button>
        </div>
        <div>
          <span className="muted">Out</span>
          <b className="mono">{fmt(event.end, true)}</b>
          <button className="small" onClick={() => setOut(event.end - 0.5)}>−0.5</button>
          <button className="small" onClick={() => setOut(event.end + 0.5)}>+0.5</button>
          <button className="small" onClick={() => setOut(now)} title="Shortcut: O">Set to playhead [O]</button>
        </div>
        <div className="len">
          <span className="muted">Length</span> <b>{len.toFixed(1)}s</b>
          {len > 60 && <span className="warn"> over 60s (Shorts limit)</span>}
        </div>
      </div>
      <p className="hint">Space play/pause · ←/→ frame step (Shift = 1s) · I / O set in/out · drag the orange handles</p>
    </section>
  );
}

const round = (t: number) => Math.round(t * 100) / 100;
const round4 = (t: number) => Math.round(t * 10000) / 10000;
