import { useMemo, useRef, useState } from "react";
import { fmt, TYPE_LABEL, type ClipEvent } from "../api";

interface Props {
  duration: number;
  events: ClipEvent[];
  selectedId: string | null;
  cursor: number | null;
  playhead: number;
  thumbUrl: (e: ClipEvent) => string | null;
  onSelect: (id: string) => void;
  onCursor: (t: number | null) => void;
  onAddAt: (t: number) => void;
  /** Stretches covered by a synced replay, shaded behind the markers. */
  matches?: { start: number; end: number; label: string }[];
}

const STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

export default function Timeline({ duration, events, selectedId, cursor, playhead, thumbUrl, onSelect, onCursor, onAddAt, matches = [] }: Props) {
  const [zoom, setZoom] = useState(1);
  const [hover, setHover] = useState<{ e: ClipEvent; x: number } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pct = (t: number) => `${(t / Math.max(duration, 1)) * 100}%`;

  const ticks = useMemo(() => {
    const visibleSeconds = duration / zoom;
    const step = STEPS.find((s) => visibleSeconds / s <= 12) ?? 3600;
    const out: number[] = [];
    for (let t = 0; t <= duration; t += step) out.push(t);
    return out;
  }, [duration, zoom]);

  const timeAt = (clientX: number, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    return Math.min(Math.max(((clientX - r.left) / r.width) * duration, 0), duration);
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    events.forEach((e) => (c[e.type] = (c[e.type] ?? 0) + 1));
    return c;
  }, [events]);

  return (
    <section className="card timeline">
      <div className="timeline-head">
        <div className="legend">
          {Object.entries(counts).map(([type, n]) => (
            <span key={type} className={`chip t-${type}`}>
              {TYPE_LABEL[type as ClipEvent["type"]]} <b>{n}</b>
            </span>
          ))}
          {!events.length && <span className="muted">No clips yet</span>}
        </div>
        <div className="row">
          {cursor !== null && (
            <>
              <span className="muted">Cursor {fmt(cursor)}</span>
              <button className="small" onClick={() => onAddAt(cursor)}>
                + Add clip here
              </button>
            </>
          )}
          <label className="zoom">
            Zoom
            <input type="range" min={1} max={30} step={0.5} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
          </label>
        </div>
      </div>
      <div className="timeline-scroll" ref={scroller}>
        <div
          className="timeline-track"
          style={{ width: `${zoom * 100}%` }}
          onClick={(ev) => onCursor(timeAt(ev.clientX, ev.currentTarget))}
        >
          {matches.map((m, i) => (
            <div key={`match-${i}`} className="match-span" style={{ left: pct(m.start), width: pct(m.end - m.start) }} title={m.label}>
              <span>{m.label}</span>
            </div>
          ))}
          {ticks.map((t) => (
            <div key={t} className="tick" style={{ left: pct(t) }}>
              <span>{fmt(t)}</span>
            </div>
          ))}
          {events.map((e) => (
            <div
              key={`span-${e.id}`}
              className={`span t-${e.type} ${e.selected ? "on" : ""}`}
              style={{ left: pct(e.start), width: pct(e.end - e.start) }}
            />
          ))}
          {events.map((e) => (
            <button
              key={e.id}
              className={`marker t-${e.type} ${e.id === selectedId ? "active" : ""} ${e.selected ? "" : "dim"}`}
              style={{ left: pct(e.time) }}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelect(e.id);
              }}
              onMouseEnter={(ev) => {
                const r = scroller.current!.getBoundingClientRect();
                setHover({ e, x: ev.currentTarget.getBoundingClientRect().left - r.left });
              }}
              onMouseLeave={() => setHover(null)}
              aria-label={`${TYPE_LABEL[e.type]} at ${fmt(e.time)}`}
            />
          ))}
          {cursor !== null && <div className="cursor" style={{ left: pct(cursor) }} />}
          <div className="playhead" style={{ left: pct(playhead) }} />
        </div>
      </div>
      {hover && (
        <div className="tooltip" style={{ left: Math.min(Math.max(hover.x - 80, 0), (scroller.current?.clientWidth ?? 400) - 170) }}>
          {thumbUrl(hover.e) && <img src={thumbUrl(hover.e)!} alt="" />}
          <div>
            <strong>{TYPE_LABEL[hover.e.type]}</strong> {hover.e.team && <span className={`team ${hover.e.team}`}>{hover.e.team}</span>}
          </div>
          {hover.e.player && <div>{hover.e.player}</div>}
          <div className="muted">
            {fmt(hover.e.time)} · {hover.e.source === "replay" ? "from replay" : `${Math.round(hover.e.confidence * 100)}%`}
          </div>
        </div>
      )}
    </section>
  );
}
