import { fmt, TYPE_LABEL, type ClipEvent, type EventType, type SeqKind } from "../api";

interface Props {
  events: ClipEvent[];
  visible: ClipEvent[];
  filters: Set<EventType>;
  allTypes: EventType[];
  selectedId: string | null;
  analyzing: boolean;
  /** null when no clip says whose play it is (no replays used). */
  mineOnly: boolean | null;
  onMineOnly: (v: boolean) => void;
  onFilters: (f: Set<EventType>) => void;
  onSelect: (id: string) => void;
  onToggle: (e: ClipEvent) => void;
  onBulk: (ids: string[], value: boolean) => void;
  onDelete: (id: string) => void;
  /** Each replay-synced game's span in the video; clips are listed under their game. */
  games?: { start: number; end: number; label: string }[];
  /** Which clips are on the YouTube / TikTok timelines; the row chips toggle them. */
  membership?: Record<SeqKind, Set<string>>;
  onToggleSeq?: (kind: SeqKind, e: ClipEvent) => void;
}

interface Group {
  label: string | null;
  items: ClipEvent[];
}

/** Split clips (already in time order) into one group per game; clips outside every game get their own group. */
function groupByGame(events: ClipEvent[], games: { start: number; end: number; label: string }[]): Group[] {
  if (!games.length) return [{ label: null, items: events }];
  const groups: Group[] = [];
  for (const e of events) {
    const game = games.find((g) => e.time >= g.start - 1 && e.time <= g.end + 1);
    const label = game?.label ?? "Outside replays (screen scan)";
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(e);
    else groups.push({ label, items: [e] });
  }
  return groups;
}

export default function ClipList({ events, visible, filters, allTypes, selectedId, analyzing, mineOnly, onMineOnly, onFilters, onSelect, onToggle, onBulk, onDelete, games = [], membership, onToggleSeq }: Props) {
  const present = allTypes.filter((t) => events.some((e) => e.type === t));
  const toggleFilter = (t: EventType) => {
    const next = new Set(filters);
    next.has(t) ? next.delete(t) : next.add(t);
    onFilters(next);
  };
  const ids = visible.map((e) => e.id);

  return (
    <section className="card cliplist">
      <div className="cliplist-head">
        <h2>Clips</h2>
        <div className="row">
          <button className="small ghost" onClick={() => onBulk(ids, true)} disabled={!ids.length}>
            Select all
          </button>
          <button className="small ghost" onClick={() => onBulk(ids, false)} disabled={!ids.length}>
            None
          </button>
        </div>
      </div>
      {present.length > 0 && (
        <div className="filters">
          {present.map((t) => (
            <button key={t} className={`chip t-${t} ${filters.has(t) ? "" : "off"}`} onClick={() => toggleFilter(t)}>
              {TYPE_LABEL[t]}
            </button>
          ))}
          {mineOnly !== null && (
            <button className={`chip mine ${mineOnly ? "" : "off"}`} onClick={() => onMineOnly(!mineOnly)} title="Hide other players' plays">
              Mine only
            </button>
          )}
        </div>
      )}
      <ul>
        {groupByGame(visible, games).map((g, gi) => [
          g.label && (
            <li key={`game-${gi}`} className="game-head">
              <input
                type="checkbox"
                checked={g.items.every((e) => e.selected)}
                onChange={(ev) => onBulk(g.items.map((e) => e.id), ev.target.checked)}
                aria-label={`Include all of ${g.label}`}
              />
              <span className="game-label">{g.label}</span>
              <span className="muted">{g.items.length} {g.items.length === 1 ? "clip" : "clips"}</span>
            </li>
          ),
          ...g.items.map((e) => (
          <li key={e.id} className={`${e.id === selectedId ? "active" : ""} ${e.mine === false ? "other" : ""}`} onClick={() => onSelect(e.id)}>
            <input
              type="checkbox"
              checked={e.selected}
              onClick={(ev) => ev.stopPropagation()}
              onChange={() => onToggle(e)}
              aria-label="Include in export"
            />
            <span className={`dot t-${e.type}`} />
            <span className="cl-type">
              {TYPE_LABEL[e.type]}
              {e.team && <span className={`team ${e.team}`}>{e.team}</span>}
              {e.player && <span className="cl-player">{e.player}</span>}
            </span>
            <span className="cl-time">{fmt(e.time)}</span>
            <span className="cl-len muted">{(e.end - e.start).toFixed(1)}s</span>
            {membership && onToggleSeq && (
              <span className="cl-seq">
                {(["youtube", "tiktok"] as SeqKind[]).map((k) => (
                  <button
                    key={k}
                    className={`seq-chip ${k} ${membership[k].has(e.id) ? "on" : ""}`}
                    title={membership[k].has(e.id) ? `On the ${k === "youtube" ? "YouTube" : "TikTok"} timeline (click to remove)` : `Add to the ${k === "youtube" ? "YouTube" : "TikTok"} timeline`}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onToggleSeq(k, e);
                    }}
                  >
                    {k === "youtube" ? "YT" : "TT"}
                  </button>
                ))}
              </span>
            )}
            <button
              className="ghost small"
              title="Delete clip"
              onClick={(ev) => {
                ev.stopPropagation();
                onDelete(e.id);
              }}
            >
              ✕
            </button>
          </li>
          )),
        ])}
        {!visible.length && <li className="muted none">{analyzing ? "Scanning…" : "Nothing here."}</li>}
      </ul>
    </section>
  );
}
