import { useEffect, useRef, useState } from "react";
import {
  api,
  EFFECT_LABEL,
  type EffectMarker,
  type EffectType,
  type FreesoundResult,
  type SeqItem,
  type Settings,
  type Sound,
  type SoundMarker,
} from "../api";
import { playSound } from "../effects";

interface Props {
  item: SeqItem;
  /** The playhead in source seconds, when it's inside this clip. */
  playhead: number | null;
  settings: Settings;
  onSettings: (patch: Settings) => void;
  onPatch: (patch: Partial<SeqItem>) => void;
  onSeek: (sourceTime: number) => void;
  onError: (msg: string) => void;
}

const uid = () => Math.random().toString(36).slice(2, 10);
const round = (t: number) => Math.round(t * 100) / 100;

/** One click: an effect plus a sound (found by name in your library) at the playhead. */
const PRESETS: { label: string; effect: EffectType; sound: string }[] = [
  { label: "Goal hit", effect: "impact", sound: "boom" },
  { label: "Clown", effect: "glitch", sound: "fart" },
  { label: "Bruh moment", effect: "bw", sound: "bruh" },
];

export default function EffectsPanel({ item, playhead, settings, onSettings, onPatch, onSeek, onError }: Props) {
  const [library, setLibrary] = useState<Sound[]>([]);
  const [pick, setPick] = useState("");
  // The sound browser; ``at`` places the sound you add from it.
  const [browse, setBrowse] = useState<{ query: string; at: number | null } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const effects = item.effects ?? [];
  const sounds = item.sounds ?? [];

  const loadLibrary = () =>
    api
      .sounds()
      .then((s) => {
        setLibrary(s);
        return s;
      })
      .catch(() => [] as Sound[]);
  useEffect(() => {
    loadLibrary();
  }, []);

  const clampT = (t: number) => round(Math.min(Math.max(t, item.start), item.end - 0.05));
  const at = () => clampT(playhead ?? item.start);
  const byTime = <T extends { t: number }>(xs: T[]) => [...xs].sort((a, b) => a.t - b.t);

  const addEffect = (type: EffectType, t = at()) => onPatch({ effects: byTime([...effects, { id: uid(), t, type, strength: 0.8 }]) });
  const patchEffect = (id: string, patch: Partial<EffectMarker>) =>
    onPatch({ effects: byTime(effects.map((e) => (e.id === id ? { ...e, ...patch } : e))) });
  const addSound = (sound: string, t = at()) => onPatch({ sounds: byTime([...sounds, { id: uid(), t, sound, volume: 1 }]) });
  const patchSound = (id: string, patch: Partial<SoundMarker>) =>
    onPatch({ sounds: byTime(sounds.map((s) => (s.id === id ? { ...s, ...patch } : s))) });

  const preset = (p: (typeof PRESETS)[number]) => {
    const t = at();
    const found = library.find((s) => s.label.toLowerCase().includes(p.sound));
    onPatch({
      effects: byTime([...effects, { id: uid(), t, type: p.effect, strength: 0.8 }]),
      ...(found ? { sounds: byTime([...sounds, { id: uid(), t, sound: found.name, volume: 1 }]) } : {}),
    });
    if (!found) setBrowse({ query: p.sound, at: t });
  };

  const upload = async (files: FileList | null) => {
    for (const f of Array.from(files ?? [])) {
      try {
        const s = await api.uploadSound(f);
        setPick(s.name);
      } catch (e) {
        onError(String((e as Error).message));
      }
    }
    loadLibrary();
  };

  const rel = (t: number) => `${(t - item.start).toFixed(1)}s`;

  return (
    <div className="seq-fx">
      <h3>Effects &amp; sounds</h3>
      <p className="muted">Added at the playhead{playhead === null ? " (it's outside this clip, so at the clip's start)" : ""}. Drag the markers under the timeline to move them.</p>
      <div className="fx-buttons">
        <span className="muted">Presets</span>
        {PRESETS.map((p) => (
          <button key={p.label} className="small" onClick={() => preset(p)} title={`${EFFECT_LABEL[p.effect]} + a "${p.sound}" sound`}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="fx-buttons">
        <span className="muted">Effects</span>
        {(Object.keys(EFFECT_LABEL) as EffectType[]).map((type) => (
          <button key={type} className="small" onClick={() => addEffect(type)}>
            + {EFFECT_LABEL[type]}
          </button>
        ))}
      </div>
      {effects.length > 0 && (
        <ul className="fx-list">
          {effects.map((e) => (
            <li key={e.id}>
              <span className="fx-icon">⚡</span>
              <b>{EFFECT_LABEL[e.type]}</b>
              <Time label={rel(e.t)} onSeek={() => onSeek(e.t)} onNudge={(d) => patchEffect(e.id, { t: clampT(e.t + d) })} />
              <label className="grow" title="Strength">
                <input type="range" min={0.2} max={1} step={0.05} value={e.strength} onChange={(ev) => patchEffect(e.id, { strength: Number(ev.target.value) })} />
              </label>
              <button className="ghost small" title="Remove" onClick={() => onPatch({ effects: effects.filter((x) => x.id !== e.id) })}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="fx-buttons">
        <span className="muted">Sounds</span>
        <select value={pick} onChange={(e) => setPick(e.target.value)} className="small-select">
          <option value="">{library.length ? "Choose a sound…" : "Your library is empty"}</option>
          {library.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label} ({s.seconds.toFixed(1)}s)
            </option>
          ))}
        </select>
        <button className="small" disabled={!pick} onClick={() => addSound(pick)}>
          + Add
        </button>
        <button className="small" disabled={!pick} onClick={() => playSound({ sound: pick, volume: 1 })} title="Listen">
          ▶
        </button>
        <button className="small" onClick={() => setBrowse({ query: "", at: null })}>
          Find sounds online…
        </button>
        <button className="ghost small" onClick={() => fileInput.current?.click()}>
          Upload…
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".wav,.mp3,.ogg,.m4a,audio/*"
          multiple
          hidden
          onChange={(e) => {
            upload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {sounds.length > 0 && (
        <ul className="fx-list">
          {sounds.map((s) => (
            <li key={s.id}>
              <span className="fx-icon">♪</span>
              <b className="fx-name" title={s.sound}>
                {s.sound.replace(/\.[^.]+$/, "")}
              </b>
              <Time label={rel(s.t)} onSeek={() => onSeek(s.t)} onNudge={(d) => patchSound(s.id, { t: clampT(s.t + d) })} />
              <label className="grow" title={`Volume ${Math.round(s.volume * 100)}%`}>
                <input type="range" min={0} max={2} step={0.05} value={s.volume} onChange={(ev) => patchSound(s.id, { volume: Number(ev.target.value) })} />
              </label>
              <button className="ghost small" title="Listen" onClick={() => playSound(s)}>
                ▶
              </button>
              <button className="ghost small" title="Remove" onClick={() => onPatch({ sounds: sounds.filter((x) => x.id !== s.id) })}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      {browse && (
        <SoundBrowser
          initial={browse.query}
          library={library}
          settings={settings}
          onSettings={onSettings}
          onError={onError}
          onClose={() => setBrowse(null)}
          onLibrary={loadLibrary}
          onAdded={(s) => {
            setPick(s.name);
            if (browse.at !== null) {
              addSound(s.name, browse.at);
              setBrowse(null);
            }
          }}
        />
      )}
    </div>
  );
}

function Time({ label, onSeek, onNudge }: { label: string; onSeek: () => void; onNudge: (d: number) => void }) {
  return (
    <span className="fx-time">
      <button className="ghost small" title="Earlier" onClick={() => onNudge(-0.1)}>
        ‹
      </button>
      <button className="ghost small mono" title="Go to" onClick={onSeek}>
        {label}
      </button>
      <button className="ghost small" title="Later" onClick={() => onNudge(0.1)}>
        ›
      </button>
    </span>
  );
}

// ---------------------------------------------------------------- Freesound browser

interface BrowserProps {
  initial: string;
  library: Sound[];
  settings: Settings;
  onSettings: (patch: Settings) => void;
  onError: (msg: string) => void;
  onClose: () => void;
  onLibrary: () => Promise<Sound[]>;
  onAdded: (s: Sound) => void;
}

function SoundBrowser({ initial, library, settings, onSettings, onError, onClose, onLibrary, onAdded }: BrowserProps) {
  const [query, setQuery] = useState(initial);
  const [results, setResults] = useState<FreesoundResult[] | null>(null);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState<number | null>(null);
  const [key, setKey] = useState("");
  const [err, setErr] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const hasKey = Boolean(String(settings.freesound_api_key ?? "").trim());

  const listen = (src: string) => {
    audio.current?.pause();
    audio.current = new Audio(src);
    audio.current.volume = 0.35; // Freesound's previews aren't levelled yet (added sounds are), and many are mastered very loud
    audio.current.play().catch(() => {});
  };
  useEffect(() => () => audio.current?.pause(), []);

  const run = async (q: string, p = 1) => {
    if (!q.trim()) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.searchSounds(q, p);
      setResults((prev) => (p > 1 && prev ? [...prev, ...r.results] : r.results));
      setMore(r.more);
      setPage(p);
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (hasKey && initial) run(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasKey]);

  const add = async (r: FreesoundResult) => {
    setAdding(r.id);
    try {
      const s = await api.addFreesound(r.id);
      await onLibrary();
      onAdded(s);
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setAdding(null);
    }
  };

  const saveKey = async () => {
    const patch = { freesound_api_key: key.trim() };
    await api.saveSettings(patch);
    onSettings(patch);
  };

  const owned = new Set(library.map((s) => s.credit?.url).filter(Boolean));

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal sound-browser" onClick={(e) => e.stopPropagation()}>
        <div className="row spread">
          <h2>Sounds</h2>
          <button className="ghost small" onClick={onClose}>
            Close
          </button>
        </div>
        {!hasKey ? (
          <div className="fs-key">
            <p>
              Search <a href="https://freesound.org" target="_blank" rel="noreferrer">Freesound</a>'s 600,000+ sounds right here (bruh, fart, vine boom, gunshot…). It needs a free API key:
            </p>
            <ol>
              <li>
                Make a free Freesound account, then open{" "}
                <a href="https://freesound.org/apiv2/apply" target="_blank" rel="noreferrer">
                  freesound.org/apiv2/apply
                </a>
                .
              </li>
              <li>Fill in a name (e.g. "RL Clipper") and description, and submit.</li>
              <li>Copy the <b>Client secret/Api key</b> it shows and paste it here.</li>
            </ol>
            <div className="row">
              <input className="grow" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Freesound API key" />
              <button className="primary" disabled={!key.trim()} onClick={saveKey}>
                Save key
              </button>
            </div>
          </div>
        ) : (
          <>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                run(query);
              }}
            >
              <input className="grow" autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search Freesound: bruh, fart, vine boom, gunshot…" />
              <button className="primary" disabled={busy || !query.trim()}>
                {busy && page === 1 ? "Searching…" : "Search"}
              </button>
            </form>
            {err && <p className="warn">{err}</p>}
            {results && !results.length && !busy && <p className="muted">Nothing found. Try another word.</p>}
            {results && results.length > 0 && (
              <ul className="fs-results">
                {results.map((r) => (
                  <li key={r.id}>
                    <button className="ghost small" title="Listen" onClick={() => listen(r.preview)} disabled={!r.preview}>
                      ▶
                    </button>
                    <span className="grow fs-name">
                      <b title={r.name}>{r.name}</b>
                      <span className="muted">
                        {" "}
                        {r.seconds.toFixed(1)}s · by {r.user}
                      </span>
                    </span>
                    <span className={`fs-license ${r.license === "CC0" ? "free" : ""}`} title={r.license === "CC0" ? "Free to use, no credit needed" : "Credit the author if you post it"}>
                      {r.license}
                    </span>
                    <button className="small" onClick={() => add(r)} disabled={adding !== null || owned.has(r.url)}>
                      {owned.has(r.url) ? "Added" : adding === r.id ? "Adding…" : "Add"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {more && (
              <button className="ghost small" onClick={() => run(query, page + 1)} disabled={busy}>
                {busy ? "Loading…" : "More results"}
              </button>
            )}
            <p className="muted small-print">
              CC0 sounds are free to use. "CC BY" sounds need a credit (author + link) in your video description; "CC BY-NC" ones can't be used in monetised videos.
            </p>
          </>
        )}
        <h3>Your library</h3>
        {!library.length && <p className="muted">No sounds yet. Add some from the search above, or upload your own files in the clip panel.</p>}
        <ul className="fs-results">
          {library.map((s) => (
            <li key={s.name}>
              <button className="ghost small" title="Listen" onClick={() => playSound({ sound: s.name, volume: 1 })}>
                ▶
              </button>
              <span className="grow fs-name">
                <b>{s.label}</b>
                <span className="muted">
                  {" "}
                  {s.seconds.toFixed(1)}s
                  {s.credit && (
                    <>
                      {" "}
                      · <a href={s.credit.url} target="_blank" rel="noreferrer">{s.credit.user} on Freesound</a> ({s.credit.license})
                    </>
                  )}
                </span>
              </span>
              <button
                className="ghost small"
                title="Remove from your library"
                onClick={async () => {
                  try {
                    await api.deleteSound(s.name);
                    onLibrary();
                  } catch (e) {
                    onError(String((e as Error).message));
                  }
                }}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
