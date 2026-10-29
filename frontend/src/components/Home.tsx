import { useEffect, useRef, useState } from "react";
import { api, fmt, type Health, type ProjectSummary } from "../api";

const STEPS = [
  {
    title: "Record",
    body: "Record Rocket League with OBS: game audio on track 1, your mic on track 2. Press Save Replay at the end of each match for the most accurate results (optional).",
  },
  {
    title: "Detect",
    body: "Open the recording. With saved replays, every player's goals, saves and epic saves are read from the replay files and synced to the video using the match clock. Without them, the on-screen point tags and scoreboard are read instead (OCR).",
  },
  {
    title: "Review",
    body: "Each play becomes a clip, 10 s before to 10 s after. Watch them, trim, tick the ones you want. Your own plays are ticked for you.",
  },
  {
    title: "Make videos",
    body: "Put clips on the YouTube (16:9) or TikTok (9:16) timeline, reorder and trim them, add auto captions of what you say, preview the whole thing, then export one video or separate clips.",
  },
];

export default function Home({ onOpen, health }: { onOpen: (id: string) => void; health: Health | null }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = () => api.projects().then(setProjects).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const openPath = async (target = path) => {
    if (!target.trim()) return;
    setError("");
    setBusy("Opening…");
    try {
      onOpen((await api.openPath(target)).id);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  // The server opens Windows' own file dialog, so we get the real path and nothing is copied.
  const pickFile = async () => {
    setError("");
    setBusy("Choose a file in the window that opened…");
    try {
      const picked = (await api.pickFile()).path;
      setBusy(null);
      if (picked) {
        setPath(picked);
        await openPath(picked);
      }
    } catch (e) {
      setError(String((e as Error).message));
      setBusy(null);
    }
  };

  const upload = async (file: File) => {
    setError("");
    setBusy("Uploading 0%");
    try {
      const p = await api.upload(file, (x) => setBusy(`Uploading ${Math.round(x * 100)}%`));
      onOpen(p.id);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(null);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Remove this project? Your source video is not deleted.")) return;
    await api.deleteProject(id);
    refresh();
  };

  return (
    <main className="home">
      <section className="card import">
        <h1>New recording</h1>
        <p className="muted">
          Point at an OBS recording (.mkv / .mp4). It gets scanned for point tags and scoreboard changes, and a
          preview copy is made for the editor. The original file is never modified.
        </p>
        <div className="row">
          {health?.picker !== false && (
            <button className="primary" onClick={pickFile} disabled={!!busy}>
              Select file…
            </button>
          )}
          <input
            className="grow"
            placeholder={String.raw`…or paste a path: C:\Videos\2026-10-27 20-14-03.mkv`}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && openPath()}
            disabled={!!busy}
          />
          <button onClick={() => openPath()} disabled={!!busy || !path.trim()}>
            Analyze
          </button>
        </div>
        <div
          className={`dropzone ${drag ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const f = e.dataTransfer.files[0];
            if (f) upload(f);
          }}
          onClick={() => fileInput.current?.click()}
        >
          {busy ?? "…or drop a video here to upload a copy"}
          <input
            ref={fileInput}
            type="file"
            accept="video/*,.mkv"
            hidden
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
        </div>
        <p className="hint">Select file (or paste a path) is faster for big files: the video is used where it is, nothing gets copied.</p>
        {error && <div className="banner error">{error}</div>}
      </section>

      <section className="card how">
        <h2>How it works</h2>
        <ol className="steps">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <span className="step-n">{i + 1}</span>
              <div>
                <strong>{s.title}</strong>
                <p className="muted">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="hint">Everything runs on this computer: nothing is uploaded anywhere.</p>
      </section>

      {health?.ok && <SystemCheck health={health} />}

      {projects.length > 0 && (
        <section className="card">
          <h2>Recent</h2>
          <ul className="recent">
            {projects.map((p) => (
              <li key={p.id}>
                <button className="link" onClick={() => onOpen(p.id)}>
                  <strong>{p.name}</strong>
                  <span className="muted">
                    {p.duration ? fmt(p.duration) : "?"} · {p.analyzed ? `${p.event_count} clips` : "not analyzed"}
                  </span>
                </button>
                <button className="ghost small" onClick={() => remove(p.id)} title="Remove project">
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

/** What this computer can do. Only ffmpeg is required; everything else falls back. */
function SystemCheck({ health }: { health: Health }) {
  const rows: { ok: boolean; label: string; detail: string }[] = [
    { ok: !!health.ffmpeg, label: "ffmpeg", detail: health.ffmpeg ? "found" : "required: install it and restart" },
    {
      ok: !!health.nvenc,
      label: "Video encoding",
      detail: health.nvenc ? "NVIDIA GPU (NVENC)" : "CPU (works everywhere, slower exports)",
    },
    {
      ok: !!health.captions_gpu,
      label: "Captions",
      detail: health.captions_gpu
        ? "GPU"
        : `CPU, about 3 s per 10 s clip${health.captions_gpu_reason ? ` (${health.captions_gpu_reason})` : ""}`,
    },
    {
      ok: !!health.captions_burn,
      label: "Burned-in captions",
      detail: health.captions_burn
        ? "supported (libass)"
        : "this ffmpeg lacks libass: install a full ffmpeg build to burn captions in",
    },
    {
      ok: !!health.caption_model_ready,
      label: "Speech model",
      detail: health.caption_model_ready ? "downloaded" : "downloads automatically the first time you transcribe",
    },
    {
      ok: !!health.rrrocket,
      label: "Replay reader (rrrocket)",
      detail: health.rrrocket
        ? "installed"
        : health.rrrocket_downloadable
          ? "offered for download when you open a project"
          : "not available for this platform: on-screen detection only",
    },
    {
      ok: !!health.demos_dir,
      label: "Rocket League replays",
      detail: health.demos_dir ?? "folder not found: set it in Settings, or skip (on-screen detection)",
    },
  ];
  return (
    <section className="card system">
      <h2>This computer</h2>
      <ul className="checks">
        {rows.map((r) => (
          <li key={r.label} className={r.ok ? "ok" : "optional"}>
            <span className="check-dot">{r.ok ? "✓" : "–"}</span>
            <strong>{r.label}</strong>
            <span className="muted" title={r.detail}>
              {r.detail}
            </span>
          </li>
        ))}
      </ul>
      <p className="hint">Only ffmpeg is required. Everything marked – has a fallback and the app still works.</p>
    </section>
  );
}
