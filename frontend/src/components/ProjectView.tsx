import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  fmt,
  type ClipEvent,
  type Cue,
  type EventPatch,
  type EventType,
  type Frame,
  type Project,
  type SeqKind,
  type Sequence,
  type Settings,
  type VerticalStyle,
} from "../api";
import ClipEditor from "./ClipEditor";
import ClipList from "./ClipList";
import JobBar from "./JobBar";
import MatchesPanel from "./MatchesPanel";
import SequenceView, { newItem } from "./SequenceView";
import SettingsDialog from "./SettingsDialog";
import Timeline from "./Timeline";

const ALL_TYPES: EventType[] = ["goal", "epic_save", "save", "goal_other", "manual"];
const KINDS: SeqKind[] = ["youtube", "tiktok"];
const TAB_LABEL = { clips: "Clips", youtube: "YouTube", tiktok: "TikTok" };
export type Tab = "clips" | SeqKind;

const emptySeq = (kind: SeqKind): Sequence => ({ items: [], captions: kind === "tiktok" });

interface Props {
  id: string;
  /** The open tab lives in the URL (#/p/<id>/tiktok) so it survives a reload. */
  tab: Tab;
  onTab: (tab: Tab) => void;
  onClose: () => void;
}

export default function ProjectView({ id, tab, onTab, onClose }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filters, setFilters] = useState<Set<EventType>>(new Set(ALL_TYPES));
  const [mineOnly, setMineOnly] = useState(false);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [showSettings, setShowSettings] = useState<false | "all" | "accounts">(false);
  // Timelines and captions are edited here and saved in the background.
  const [seqs, setSeqs] = useState<Record<SeqKind, Sequence> | null>(null);
  const [captions, setCaptions] = useState<Cue[]>([]);
  const savedOnServer = useRef<Set<SeqKind>>(new Set());
  const lastAnalysis = useRef<string | undefined>();
  const loaded = useRef(false);
  const lastTranscribe = useRef<string | undefined>();
  const saveTimers = useRef<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      const fresh = await api.project(id);
      const status = fresh.job_status.analysis?.status;
      const first = !loaded.current;
      // Only take the server's events on first load or when an analysis just finished,
      // so polling never stomps on edits that are still being saved.
      const analysisDone = status === "done" && lastAnalysis.current !== undefined && lastAnalysis.current !== "done";
      lastAnalysis.current = status;
      setProject((prev) => (!prev || first || analysisDone ? fresh : { ...fresh, events: prev.events }));
      if (first || analysisDone) {
        // On load, and after a re-analysis re-pointed timeline items at the new events.
        KINDS.forEach((k) => fresh.sequences?.[k] && savedOnServer.current.add(k));
        setSeqs({ youtube: fresh.sequences?.youtube ?? emptySeq("youtube"), tiktok: fresh.sequences?.tiktok ?? emptySeq("tiktok") });
      }
      const tStatus = fresh.job_status.transcribe?.status;
      if (first || (tStatus === "done" && lastTranscribe.current && lastTranscribe.current !== "done")) setCaptions(fresh.captions ?? []);
      lastTranscribe.current = tStatus;
      loaded.current = true;
    } catch (e) {
      setError(String((e as Error).message));
    }
  }, [id]);

  useEffect(() => {
    setProject(null);
    setSeqs(null);
    loaded.current = false;
    lastAnalysis.current = undefined;
    lastTranscribe.current = undefined;
    savedOnServer.current = new Set();
    load();
    api.settings().then(setSettings);
  }, [id, load]);

  const busy = project && Object.values(project.job_status).some((j) => j && ["queued", "running"].includes(j.status));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [busy, load]);

  const later = (key: string, fn: () => Promise<unknown>) => {
    window.clearTimeout(saveTimers.current[key]);
    saveTimers.current[key] = window.setTimeout(() => fn().catch((e) => setError(String((e as Error).message))), 400);
  };

  // Edits build on the latest value even when several land before a re-render.
  const seqsRef = useRef(seqs);
  seqsRef.current = seqs;
  const captionsRef = useRef(captions);
  captionsRef.current = captions;

  const updateSeq = (kind: SeqKind, change: Sequence | ((prev: Sequence) => Sequence)) => {
    const cur = seqsRef.current;
    if (!cur) return;
    const seq = typeof change === "function" ? change(cur[kind]) : change;
    seqsRef.current = { ...cur, [kind]: seq };
    setSeqs(seqsRef.current);
    savedOnServer.current.add(kind);
    later(`seq-${kind}`, () => api.saveSequence(id, kind, seq));
  };

  const updateCaptions = (change: Cue[] | ((prev: Cue[]) => Cue[])) => {
    const cues = typeof change === "function" ? change(captionsRef.current) : change;
    captionsRef.current = cues;
    setCaptions(cues);
    later("captions", () => api.saveCaptions(id, cues));
  };

  const updateSettings = async (patch: Settings) => {
    setSettings((s) => s && { ...s, ...patch });
    later("settings", () => api.saveSettings(patch));
  };

  const openTab = (next: Tab) => {
    // First visit to an empty timeline: start it with the ticked clips.
    if (next !== "clips" && seqs && project && !savedOnServer.current.has(next) && !seqs[next].items.length) {
      const ticked = project.events.filter((e) => e.selected);
      if (ticked.length) updateSeq(next, (s) => ({ ...s, items: ticked.map(newItem) }));
    }
    onTab(next);
  };

  const toggleInSeq = (kind: SeqKind, e: ClipEvent) =>
    updateSeq(kind, (seq) => {
      const has = seq.items.some((i) => i.event_id === e.id);
      return { ...seq, items: has ? seq.items.filter((i) => i.event_id !== e.id) : [...seq.items, newItem(e)] };
    });

  const events = project?.events ?? [];
  const hasOwner = events.some((e) => e.mine === false);
  const visible = useMemo(
    () => events.filter((e) => filters.has(e.type) && !(mineOnly && e.mine === false)),
    [events, filters, mineOnly],
  );
  const selected = events.find((e) => e.id === selectedId) ?? null;
  const games = useMemo(
    () =>
      (project?.matches ?? [])
        .filter((m) => m.span)
        .map((m, i) => ({ start: m.span![0], end: m.span![1], label: `Game ${i + 1} · ${m.replay.score[0]}-${m.replay.score[1]}` })),
    [project?.matches],
  );
  const membership = useMemo(() => {
    const m: Record<SeqKind, Set<string>> = { youtube: new Set(), tiktok: new Set() };
    if (seqs) KINDS.forEach((k) => seqs[k].items.forEach((i) => m[k].add(i.event_id)));
    return m;
  }, [seqs]);

  useEffect(() => {
    if (!selectedId && visible.length) setSelectedId(visible[0].id);
  }, [visible, selectedId]);

  const updateLocal = (eid: string, patch: Partial<ClipEvent>) =>
    setProject((p) => p && { ...p, events: p.events.map((e) => (e.id === eid ? { ...e, ...patch } : e)) });

  const saveEvent = async (eid: string, patch: EventPatch) => {
    updateLocal(eid, { ...patch, frame: patch.frame === "" ? null : patch.frame, style: patch.style === "" ? null : patch.style });
    try {
      const saved = await api.patchEvent(id, eid, patch);
      updateLocal(eid, saved);
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const removeEvent = async (eid: string) => {
    setProject((p) => p && { ...p, events: p.events.filter((e) => e.id !== eid) });
    setSeqs((s) => s && { youtube: { ...s.youtube, items: s.youtube.items.filter((i) => i.event_id !== eid) }, tiktok: { ...s.tiktok, items: s.tiktok.items.filter((i) => i.event_id !== eid) } });
    if (selectedId === eid) setSelectedId(null);
    await api.deleteEvent(id, eid);
  };

  const addAt = async (t: number) => {
    const ev = await api.addEvent(id, t);
    setProject((p) => p && { ...p, events: [...p.events, ev].sort((a, b) => a.time - b.time) });
    setSelectedId(ev.id);
  };

  const bulkSelect = async (ids: string[], value: boolean) => {
    const set = new Set(ids);
    setProject((p) => p && { ...p, events: p.events.map((e) => (set.has(e.id) ? { ...e, selected: value } : e)) });
    await api.select(id, ids, value);
  };

  const reanalyze = async () => {
    try {
      setProject(await api.reanalyze(id));
      lastAnalysis.current = "queued";
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  if (!project || !seqs) return <main className="loading">{error || "Loading…"}</main>;

  const analysis = project.job_status.analysis;
  const proxy = project.job_status.proxy;
  const analyzing = analysis && ["queued", "running"].includes(analysis.status);
  const ticked = events.filter((e) => e.selected);

  return (
    <main className="project">
      <div className="project-head">
        <button className="ghost" onClick={onClose}>
          ← Back
        </button>
        <div className="grow">
          <h1 title={project.source}>{project.name}</h1>
          <span className="muted">
            {fmt(project.info.duration)} · {project.info.width}×{project.info.height} @ {Math.round(project.info.fps)}fps ·{" "}
            {project.info.audio_streams} audio track{project.info.audio_streams === 1 ? "" : "s"}
            {project.info.audio_streams !== 2 && <span className="warn"> (expected 2: game + mic)</span>}
          </span>
        </div>
        <button className="ghost" onClick={reanalyze} disabled={!!analyzing}>
          Re-analyze
        </button>
        <button className="ghost" onClick={() => setShowSettings("all")}>
          Settings
        </button>
      </div>

      <nav className="tabs">
        {(["clips", "youtube", "tiktok"] as Tab[]).map((t) => (
          <button key={t} className={`tab tab-${t} ${tab === t ? "on" : ""}`} onClick={() => openTab(t)}>
            {TAB_LABEL[t]}
            <span className="tab-count">{t === "clips" ? events.length : seqs[t].items.length}</span>
          </button>
        ))}
      </nav>

      {(analyzing || analysis?.status === "error") && (
        <JobBar label="Scanning for goals & saves" job={analysis!} onCancel={() => api.cancelJob(analysis!.id)} />
      )}
      {proxy && proxy.status !== "done" && <JobBar label="Building preview" job={proxy} />}
      {error && (
        <div className="banner error" onClick={() => setError("")}>
          {error}
        </div>
      )}

      {tab !== "clips" && settings ? (
        <SequenceView
          key={tab}
          project={project}
          kind={tab}
          seq={seqs[tab]}
          captions={captions}
          settings={settings}
          onSeq={(s) => updateSeq(tab, s)}
          onCaptions={updateCaptions}
          onSettings={updateSettings}
          onError={setError}
          onRefresh={load}
          onSetupPosting={() => setShowSettings("accounts")}
        />
      ) : (
        <>
          <Timeline
            duration={project.info.duration}
            events={visible}
            selectedId={selectedId}
            cursor={cursor}
            playhead={playhead}
            thumbUrl={(e) => (e.thumb ? `/api/projects/${id}/thumbs/${e.thumb}` : null)}
            onSelect={setSelectedId}
            onCursor={setCursor}
            onAddAt={addAt}
            matches={games}
          />

          <div className="workspace">
            <ClipList
              events={events}
              visible={visible}
              filters={filters}
              allTypes={ALL_TYPES}
              selectedId={selectedId}
              onFilters={setFilters}
              onSelect={setSelectedId}
              onToggle={(e) => saveEvent(e.id, { selected: !e.selected })}
              onBulk={bulkSelect}
              onDelete={removeEvent}
              analyzing={!!analyzing}
              mineOnly={hasOwner ? mineOnly : null}
              onMineOnly={setMineOnly}
              games={games}
              membership={membership}
              onToggleSeq={toggleInSeq}
            />
            <div className="right">
              {selected ? (
                <ClipEditor
                  key={selected.id}
                  project={project}
                  event={selected}
                  defaults={[Number(settings?.pre_seconds ?? 10), Number(settings?.post_seconds ?? 10)]}
                  framing={{
                    frame: (settings?.frame as Frame) ?? "16:9",
                    style: (settings?.vertical_style as VerticalStyle) ?? "focus45",
                    zoom: Number(settings?.vertical_zoom ?? 1),
                    sharp: Number(settings?.vertical_sharp ?? 0.55),
                  }}
                  onLocal={(patch) => updateLocal(selected.id, patch)}
                  onSave={(patch) => saveEvent(selected.id, patch)}
                  onTime={setPlayhead}
                />
              ) : (
                <div className="card empty">
                  {analyzing ? "Clips show up here once the scan finishes." : "Select a clip on the timeline or in the list."}
                </div>
              )}
              <section className="card send">
                <h2>Make videos</h2>
                <p className="muted">Put clips on the YouTube (16:9) or TikTok (9:16, with captions) timeline, order and trim them there, then export one video or separate clips.</p>
                <div className="row">
                  {KINDS.map((k) => {
                    const missing = ticked.filter((e) => !membership[k].has(e.id));
                    return (
                      <button
                        key={k}
                        className={k === "tiktok" ? "primary" : ""}
                        disabled={!missing.length}
                        onClick={() => updateSeq(k, (s) => ({ ...s, items: [...s.items, ...missing.map(newItem)] }))}
                      >
                        Add {missing.length} ticked to {TAB_LABEL[k]}
                      </button>
                    );
                  })}
                </div>
                <div className="row">
                  {KINDS.map((k) => (
                    <button key={k} className="ghost small" onClick={() => openTab(k)}>
                      Open {TAB_LABEL[k]} timeline ({seqs[k].items.length}) →
                    </button>
                  ))}
                </div>
              </section>
              <MatchesPanel
                project={project}
                analyzing={!!analyzing}
                onApplied={(p) => {
                  setProject(p);
                  lastAnalysis.current = "queued";
                }}
                onError={setError}
              />
            </div>
          </div>
        </>
      )}

      {showSettings && settings && (
        <SettingsDialog
          projectId={id}
          time={selected ? selected.time : playhead}
          settings={settings}
          focus={showSettings === "accounts" ? "accounts" : null}
          onClose={() => setShowSettings(false)}
          onSaved={(s, rerun) => {
            setSettings(s);
            setShowSettings(false);
            if (rerun) reanalyze();
          }}
        />
      )}
    </main>
  );
}
