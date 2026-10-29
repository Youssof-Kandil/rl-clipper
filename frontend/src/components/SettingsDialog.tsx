import { useState } from "react";
import { api, STYLE_LABEL, type Settings, type VerticalStyle } from "../api";

interface Props {
  projectId: string;
  time: number;
  settings: Settings;
  onClose: () => void;
  onSaved: (s: Settings, rerun: boolean) => void;
}

const ROI_LABELS = ["left", "top", "right", "bottom"];

export default function SettingsDialog({ projectId, time, settings, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<Settings>(settings);
  const [nonce, setNonce] = useState(0);
  const [saving, setSaving] = useState(false);

  const set = (k: string, v: Settings[string]) => setDraft((d) => ({ ...d, [k]: v }));
  const num = (k: string) => Number(draft[k]);

  const roi = (k: "tag_roi" | "scoreboard_roi", title: string, color: string) => (
    <fieldset>
      <legend>
        <span className="swatch" style={{ background: color }} /> {title}
      </legend>
      {ROI_LABELS.map((label, i) => (
        <label key={label}>
          {label}
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={(draft[k] as number[])[i]}
            onChange={(e) => {
              const next = [...(draft[k] as number[])];
              next[i] = Number(e.target.value);
              set(k, next);
            }}
          />
        </label>
      ))}
    </fieldset>
  );

  const save = async (rerun: boolean) => {
    setSaving(true);
    try {
      onSaved(await api.saveSettings(draft), rerun);
    } finally {
      setSaving(false);
    }
  };

  // Preview reflects saved settings, so save-then-refresh to check a region.
  const applyPreview = async () => {
    await api.saveSettings(draft);
    setNonce((n) => n + 1);
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Settings</h2>
        <div className="settings-grid">
          <div>
            <h3>Detection regions</h3>
            <p className="hint">Fractions of the frame (0–1). Adjust if your HUD scale or resolution differs.</p>
            {roi("tag_roi", "Point tags", "#ffa500")}
            {roi("scoreboard_roi", "Scoreboard", "#28a0ff")}
            <label className="check">
              <input type="checkbox" checked={!!draft.use_scoreboard} onChange={(e) => set("use_scoreboard", e.target.checked)} />
              Also detect goals from the scoreboard
            </label>
            <label>
              Frames scanned per second
              <input type="number" min={0.5} max={10} step={0.5} value={num("sample_fps")} onChange={(e) => set("sample_fps", Number(e.target.value))} />
            </label>

            <h3>Clips</h3>
            <div className="row">
              <label>
                Max seconds before
                <input type="number" min={0} max={20} step={0.5} value={num("pre_seconds")} onChange={(e) => set("pre_seconds", Number(e.target.value))} />
              </label>
              <label>
                Max seconds after
                <input type="number" min={0} max={20} step={0.5} value={num("post_seconds")} onChange={(e) => set("post_seconds", Number(e.target.value))} />
              </label>
            </div>

            <h3>Rocket League replays</h3>
            <label className="check">
              <input type="checkbox" checked={Boolean(draft.use_replays)} onChange={(e) => set("use_replays", e.target.checked)} />
              Use saved replays for exact timings (every player's plays)
            </label>
            <label>
              Your in-game name (empty = taken from the replays)
              <input value={String(draft.my_player_name ?? "")} onChange={(e) => set("my_player_name", e.target.value)} placeholder="Froggy" />
            </label>
            <label>
              Replay folder (empty = auto-detect)
              <input value={String(draft.demos_dir ?? "")} onChange={(e) => set("demos_dir", e.target.value)} placeholder="…\My Games\Rocket League\TAGame\Demos" />
            </label>

            <h3>Audio tracks in your recording</h3>
            <div className="row">
              <label>
                Game audio = track
                <input type="number" min={1} max={6} value={num("game_track") + 1} onChange={(e) => set("game_track", Number(e.target.value) - 1)} />
              </label>
              <label>
                Mic = track
                <input type="number" min={1} max={6} value={num("mic_track") + 1} onChange={(e) => set("mic_track", Number(e.target.value) - 1)} />
              </label>
            </div>

            <h3>Export</h3>
            <label>
              Export folder (empty = inside the project)
              <div className="row nowrap">
                <input
                  className="grow"
                  value={String(draft.export_dir ?? "")}
                  onChange={(e) => setDraft((d) => ({ ...d, export_dir: e.target.value, export_dir_chosen: true }))}
                  placeholder="C:\Videos\Shorts"
                />
                <button
                  type="button"
                  className="small"
                  onClick={async () => {
                    try {
                      const { path } = await api.pickFolder();
                      if (path) setDraft((d) => ({ ...d, export_dir: path, export_dir_chosen: true }));
                    } catch (e) {
                      alert((e as Error).message);
                    }
                  }}
                >
                  Browse…
                </button>
              </div>
            </label>
            <div className="row">
              <label>
                Frame
                <select value={String(draft.frame)} onChange={(e) => set("frame", e.target.value)}>
                  <option value="16:9">16:9 (as recorded)</option>
                  <option value="9:16">9:16 (TikTok / Shorts / Reels)</option>
                </select>
              </label>
              <label>
                9:16 style
                <select value={String(draft.vertical_style)} onChange={(e) => set("vertical_style", e.target.value)}>
                  {(Object.keys(STYLE_LABEL) as VerticalStyle[]).map((s) => (
                    <option key={s} value={s}>
                      {STYLE_LABEL[s]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="row">
              <label>
                Blur strength
                <input type="number" min={5} max={80} step={5} value={num("vertical_blur")} onChange={(e) => set("vertical_blur", Number(e.target.value))} />
              </label>
              <label>
                Oval sharp area (share of height)
                <input type="number" min={0.2} max={1} step={0.05} value={num("vertical_sharp")} onChange={(e) => set("vertical_sharp", Number(e.target.value))} />
              </label>
              <label>
                Extra zoom
                <input type="number" min={1} max={2} step={0.05} value={num("vertical_zoom")} onChange={(e) => set("vertical_zoom", Number(e.target.value))} />
              </label>
            </div>
            <p className="hint">Each clip can switch frame and style in the editor, and you can drag where the 9:16 crop sits.</p>

            <h3>Captions (TikTok)</h3>
            <div className="row">
              <label>
                Speech model
                <select value={String(draft.caption_model)} onChange={(e) => set("caption_model", e.target.value)}>
                  <option value="base.en">base.en (fast, ~150 MB)</option>
                  <option value="small.en">small.en (recommended, ~480 MB)</option>
                  <option value="medium.en">medium.en (best, ~1.5 GB, slow on CPU)</option>
                </select>
              </label>
              <label>
                Text size
                <input type="number" min={40} max={140} step={2} value={num("caption_size")} onChange={(e) => set("caption_size", Number(e.target.value))} />
              </label>
              <label>
                Position
                <select value={String(draft.caption_position)} onChange={(e) => set("caption_position", e.target.value)}>
                  <option value="upper">Upper</option>
                  <option value="middle">Middle</option>
                  <option value="lower">Lower</option>
                </select>
              </label>
            </div>
            <label className="check">
              <input type="checkbox" checked={Boolean(draft.caption_upper)} onChange={(e) => set("caption_upper", e.target.checked)} />
              ALL CAPS
            </label>
            <div className="row">
              <label className="check">
                <input type="checkbox" checked={draft.caption_highlight !== false} onChange={(e) => set("caption_highlight", e.target.checked)} />
                Highlight the word being said
              </label>
              <input type="color" className="swatch-input" value={String(draft.caption_color ?? "#2EA8FF")} onChange={(e) => set("caption_color", e.target.value.toUpperCase())} />
              <label>
                Max words per caption
                <input type="number" min={1} max={16} value={num("caption_max_words")} onChange={(e) => set("caption_max_words", Number(e.target.value))} />
              </label>
            </div>
            <label>
              Export size
              <select value={String(draft.export_quality ?? "balanced")} onChange={(e) => set("export_quality", e.target.value)}>
                <option value="best">Best quality (largest, ~4 MB per second at 9:16)</option>
                <option value="balanced">Balanced (recommended, ~3 MB per second)</option>
                <option value="small">Small (HEVC, ~2 MB per second; some old players can't open it)</option>
              </select>
            </label>
            <label>
              Video encoder
              <select value={String(draft.encoder)} onChange={(e) => set("encoder", e.target.value)}>
                <option value="auto">Auto (NVIDIA if available)</option>
                <option value="nvenc">NVIDIA NVENC</option>
                <option value="x264">CPU (x264)</option>
              </select>
            </label>
          </div>
          <div>
            <h3>Region preview</h3>
            <img className="roi-preview" src={`/api/projects/${projectId}/frame?t=${time.toFixed(2)}&n=${nonce}`} alt="Frame with detection regions" />
            <button className="small" onClick={applyPreview}>
              Save & refresh preview
            </button>
            <p className="hint">Tip: open a clip whose tag is on screen, then check the orange box covers it.</p>
          </div>
        </div>
        <div className="modal-actions">
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button onClick={() => save(false)} disabled={saving}>
            Save
          </button>
          <button className="primary" onClick={() => save(true)} disabled={saving}>
            Save & re-analyze
          </button>
        </div>
      </div>
    </div>
  );
}
