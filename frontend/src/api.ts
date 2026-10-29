export type EventType = "goal" | "save" | "epic_save" | "goal_other" | "manual";

export interface ClipEvent {
  id: string;
  type: EventType;
  time: number;
  start: number;
  end: number;
  selected: boolean;
  confidence: number;
  source: string;
  team: "blue" | "orange" | null;
  text: string;
  thumb: string | null;
  /** Who made the play (replay events only). */
  player?: string | null;
  /** Your own play; other players' plays start unticked. */
  mine?: boolean;
  /** Export framing for this clip; null/missing = the default from Settings. */
  frame?: Frame | null;
  style?: VerticalStyle | null;
  /** Horizontal centre (0–1) of the 9:16 crop. */
  crop_x?: number;
}

export type Frame = "16:9" | "9:16";
export type VerticalStyle = "focus45" | "focus" | "crop" | "fit";
export const STYLE_LABEL: Record<VerticalStyle, string> = {
  focus45: "4:5 in focus + blurred 9:16 behind",
  focus: "Crop + oval focus blur",
  crop: "Crop",
  fit: "Fit + blurred fill",
};

/** What's sent to change a clip; "" clears frame/style back to the default. */
export type EventPatch = Partial<Pick<ClipEvent, "start" | "end" | "selected" | "type" | "crop_x">> & {
  frame?: Frame | "";
  style?: VerticalStyle | "";
};

export interface ReplayInfo {
  id: string;
  path: string;
  name: string;
  map: string;
  start_epoch: number;
  duration: number;
  score: [number, number];
  owner: string;
  players: { name: string; team: "blue" | "orange"; goals: number; saves: number }[];
  ignored?: boolean;
}

export interface MatchSync {
  replay: ReplayInfo;
  offset: number | null;
  source: "clock" | "goals" | "start time" | "none";
  anchors: number;
  span: [number, number] | null;
}

export interface ReplayStatus {
  rrrocket: string | null;
  demos_dir: string | null;
  version: string;
}

export type SeqKind = "youtube" | "tiktok";

/** One clip on a YouTube/TikTok timeline, with its own trim (source-video seconds). */
export interface SeqItem {
  id: string;
  event_id: string;
  start: number;
  end: number;
  crop_x: number;
  style: VerticalStyle | null;
}

export interface Sequence {
  items: SeqItem[];
  captions: boolean;
}

/** A caption line, in source-video seconds (shared by both timelines). */
export interface Cue {
  id: string;
  start: number;
  end: number;
  text: string;
  /** When each word was said (from transcription). */
  words?: { start: number; end: number; text: string }[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error" | "cancelled";
  progress: number;
  message: string;
  error: string;
  result: { files?: { name: string; path: string }[]; folder?: string; clips?: Record<string, number>; count?: number; device?: string };
}

export interface Project {
  id: string;
  name: string;
  source: string;
  info: { duration: number; width: number; height: number; fps: number; audio_streams: number };
  analyzed: boolean;
  proxy_ready: boolean;
  events: ClipEvent[];
  matches?: MatchSync[];
  exports: { name: string; path: string }[];
  job_status: Partial<Record<string, Job>>;
  sequences?: Partial<Record<SeqKind, Sequence>>;
  captions?: Cue[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  source: string;
  created: number;
  analyzed: boolean;
  event_count: number;
  duration: number;
}

export type Settings = Record<string, number | boolean | string | number[]>;

/** What this machine can do (only ffmpeg is required; the rest have fallbacks). */
export interface Health {
  ok: boolean;
  error?: string;
  platform?: string;
  ffmpeg?: string | null;
  nvenc?: boolean;
  captions_gpu?: boolean;
  captions_gpu_reason?: string;
  caption_model_ready?: boolean;
  rrrocket?: string | null;
  rrrocket_downloadable?: boolean;
  demos_dir?: string | null;
  picker?: boolean;
}

export const TYPE_LABEL: Record<EventType, string> = {
  goal: "Goal",
  save: "Save",
  epic_save: "Epic Save",
  goal_other: "Goal (scoreboard)",
  manual: "Manual",
};

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body instanceof FormData || body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const api = {
  health: () => call<Health>("GET", "/api/health"),
  projects: () => call<ProjectSummary[]>("GET", "/api/projects"),
  openPath: (path: string) => call<Project>("POST", "/api/projects", { path }),
  /** Opens the native file dialog on the machine running the server. */
  pickFile: () => call<{ path: string | null }>("POST", "/api/pick-file"),
  /** Native folder dialog (for the export folder). */
  pickFolder: () => call<{ path: string | null }>("POST", "/api/pick-folder"),
  upload: (file: File, onProgress: (p: number) => void) =>
    new Promise<Project>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);
      xhr.open("POST", "/api/projects/upload");
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () =>
        xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText));
      xhr.onerror = () => reject(new Error("Upload failed"));
      xhr.send(form);
    }),
  project: (id: string) => call<Project>("GET", `/api/projects/${id}`),
  deleteProject: (id: string) => call("DELETE", `/api/projects/${id}`),
  reanalyze: (id: string) => call<Project>("POST", `/api/projects/${id}/analyze`),
  patchEvent: (id: string, eid: string, patch: EventPatch) =>
    call<ClipEvent>("PATCH", `/api/projects/${id}/events/${eid}`, patch),
  addEvent: (id: string, time: number, type: EventType = "manual") =>
    call<ClipEvent>("POST", `/api/projects/${id}/events`, { time, type }),
  deleteEvent: (id: string, eid: string) => call("DELETE", `/api/projects/${id}/events/${eid}`),
  select: (id: string, ids: string[], selected: boolean) =>
    call<Project>("POST", `/api/projects/${id}/select`, { ids, selected }),
  export: (id: string, ids?: string[]) => call<Job>("POST", `/api/projects/${id}/export`, { ids }),
  openExports: (id: string) => call("POST", `/api/projects/${id}/open-exports`),
  cancelJob: (jobId: string) => call("POST", `/api/jobs/${jobId}/cancel`),
  replays: (id: string) => call<ReplayInfo[]>("GET", `/api/projects/${id}/replays`),
  chooseReplays: (id: string, ignored: string[]) => call<Project>("PUT", `/api/projects/${id}/replays`, { ignored }),
  replayStatus: () => call<ReplayStatus>("GET", "/api/replays/status"),
  installRrrocket: () => call<ReplayStatus>("POST", "/api/replays/rrrocket"),
  saveSequence: (id: string, kind: SeqKind, seq: Sequence) => call<Sequence>("PUT", `/api/projects/${id}/sequences/${kind}`, seq),
  exportSequence: (id: string, kind: SeqKind, mode: "compiled" | "separate") =>
    call<Job>("POST", `/api/projects/${id}/sequences/${kind}/export`, { mode }),
  saveCaptions: (id: string, captions: Cue[]) => call<Cue[]>("PUT", `/api/projects/${id}/captions`, { captions }),
  transcribe: (id: string, itemIds?: string[]) => call<Job>("POST", `/api/projects/${id}/captions/transcribe`, { item_ids: itemIds }),
  captionStatus: () => call<{ model: string; ready: boolean; device: string | null }>("GET", "/api/captions/status"),
  downloadCaptionModel: () => call<Job>("POST", "/api/captions/model"),
  job: (jobId: string) => call<Job>("GET", `/api/jobs/${jobId}`),
  settings: () => call<Settings>("GET", "/api/settings"),
  saveSettings: (s: Settings) => call<Settings>("PUT", "/api/settings", s),
};

export function fmt(t: number, decimals = false): string {
  const sign = t < 0 ? "-" : "";
  t = Math.abs(t);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  const ss = decimals ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return h ? `${sign}${h}:${String(m).padStart(2, "0")}:${ss}` : `${sign}${m}:${ss}`;
}
