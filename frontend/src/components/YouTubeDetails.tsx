import { useState } from "react";
import { api, type YouTubeOptions, type YouTubeVideo } from "../api";

const CATEGORIES: [string, string][] = [
  ["20", "Gaming"], ["24", "Entertainment"], ["22", "People & Blogs"], ["17", "Sports"], ["23", "Comedy"],
  ["2", "Autos & Vehicles"], ["1", "Film & Animation"], ["10", "Music"], ["26", "Howto & Style"],
  ["27", "Education"], ["28", "Science & Technology"],
];

const LANGUAGES: [string, string][] = [
  ["", "Not set"], ["en", "English"], ["en-US", "English (US)"], ["en-GB", "English (UK)"], ["ar", "Arabic"],
  ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["pt", "Portuguese"], ["it", "Italian"], ["nl", "Dutch"],
  ["tr", "Turkish"], ["ru", "Russian"], ["pl", "Polish"], ["sv", "Swedish"], ["hi", "Hindi"], ["ja", "Japanese"],
  ["ko", "Korean"], ["zh-Hans", "Chinese (Simplified)"],
];

export const YOUTUBE_DEFAULTS: YouTubeOptions = {
  category: "20", language: "en", audio_language: "en", made_for_kids: false, synthetic: false,
  license: "youtube", embeddable: true, public_stats: true, related: null, related_in_description: true,
};

const length = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}` : `${Math.floor(s / 60)}`) + `:${String(s % 60).padStart(2, "0")}`;
const views = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : `${n}`) + " views";

interface Props {
  value: YouTubeOptions;
  onChange: (v: YouTubeOptions) => void;
  notify: boolean;
  onNotify: (v: boolean) => void;
  short: boolean;
  onError: (msg: string) => void;
}

/** The YouTube post form's extras: a related video for Shorts, and the standard upload details. */
export default function YouTubeDetails({ value, onChange, notify, onNotify, short, onError }: Props) {
  const [videos, setVideos] = useState<YouTubeVideo[] | null>(null);
  const [suggested, setSuggested] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showShorts, setShowShorts] = useState(false);
  const set = (patch: Partial<YouTubeOptions>) => onChange({ ...value, ...patch });

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.youtubeVideos();
      setVideos(res.videos);
      setSuggested(res.suggested);
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setLoading(false);
    }
  };

  const list = (videos ?? []).filter((v) => showShorts || !v.short);
  const pick = (v: YouTubeVideo) => set({ related: { id: v.id, title: v.title } });
  const top = videos?.find((v) => v.id === suggested);

  return (
    <>
      <fieldset className="yt-related">
        <legend>{short ? "Related video (links this Short to a full video)" : "Link a video"}</legend>
        {value.related ? (
          <div className="row">
            <span className="yt-chip">▶ {value.related.title}</span>
            <button className="ghost small" onClick={() => set({ related: null })}>
              Remove
            </button>
          </div>
        ) : videos === null ? (
          <button className="small" onClick={load} disabled={loading}>
            {loading ? "Loading your videos…" : "Choose from my channel"}
          </button>
        ) : (
          <>
            {top && (
              <button className="small primary" onClick={() => pick(top)} title="Your public long video getting the most views per day right now">
                Use suggested: {top.title}
              </button>
            )}
            <label className="check">
              <input type="checkbox" checked={showShorts} onChange={(e) => setShowShorts(e.target.checked)} /> Show Shorts too
            </label>
            <ul className="yt-videos">
              {list.map((v) => (
                <li key={v.id}>
                  <button onClick={() => pick(v)}>
                    {v.thumb ? <img src={v.thumb} alt="" loading="lazy" /> : <span className="yt-thumb" />}
                    <span className="yt-title">
                      {v.title}
                      {v.id === suggested && <span className="yt-badge">Suggested</span>}
                      <span className="muted">
                        {length(v.seconds)} · {views(v.views)} · {new Date(v.published).toLocaleDateString()}
                        {v.privacy !== "public" && ` · ${v.privacy}`}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
              {!list.length && <li className="muted">No videos to show.</li>}
            </ul>
          </>
        )}
        {value.related && !short && (
          <label className="check">
            <input type="checkbox" checked={value.related_in_description} onChange={(e) => set({ related_in_description: e.target.checked })} /> Also put
            the link at the top of the description
          </label>
        )}
        {short && (
          <p className="hint">
            YouTube doesn't let apps set a Short's <b>Related video</b>. After posting, click <b>Set related video</b> in the list below: it
            opens the Short in YouTube Studio, where you pick it with the ✎ next to Related video. (Links in Shorts descriptions aren't
            clickable, so RL Clipper doesn't add one.)
          </p>
        )}
      </fieldset>

      <details className="yt-more">
        <summary>More details: category, language, audience…</summary>
        <div className="yt-grid">
          <label>
            Category
            <select value={value.category} onChange={(e) => set({ category: e.target.value })}>
              {CATEGORIES.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Video language
            <select value={value.language} onChange={(e) => set({ language: e.target.value })}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Audio language
            <select value={value.audio_language} onChange={(e) => set({ audio_language: e.target.value })}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Recording date
            <input
              type="date"
              value={value.recording_date?.slice(0, 10) ?? ""}
              onChange={(e) => set({ recording_date: e.target.value ? `${e.target.value}T00:00:00Z` : undefined })}
            />
          </label>
          <label>
            Made for kids?
            <select value={value.made_for_kids ? "yes" : "no"} onChange={(e) => set({ made_for_kids: e.target.value === "yes" })}>
              <option value="no">No, it's not made for kids</option>
              <option value="yes">Yes, it's made for kids</option>
            </select>
          </label>
          <label>
            Altered or synthetic content?
            <select value={value.synthetic ? "yes" : "no"} onChange={(e) => set({ synthetic: e.target.value === "yes" })}>
              <option value="no">No</option>
              <option value="yes">Yes</option>
            </select>
          </label>
          <label>
            License
            <select value={value.license} onChange={(e) => set({ license: e.target.value as YouTubeOptions["license"] })}>
              <option value="youtube">Standard YouTube License</option>
              <option value="creativeCommon">Creative Commons (Attribution)</option>
            </select>
          </label>
        </div>
        <div className="row wrap">
          <label className="check">
            <input type="checkbox" checked={notify} onChange={(e) => onNotify(e.target.checked)} /> Notify subscribers
          </label>
          <label className="check">
            <input type="checkbox" checked={value.embeddable} onChange={(e) => set({ embeddable: e.target.checked })} /> Allow embedding
          </label>
          <label className="check">
            <input type="checkbox" checked={value.public_stats} onChange={(e) => set({ public_stats: e.target.checked })} /> Show how many
            likes it has
          </label>
        </div>
        <p className="hint">
          Game title: YouTube picks it automatically for Gaming videos and apps can't set it. To change it, open the video in YouTube
          Studio after posting. These choices are remembered for next time.
        </p>
      </details>
    </>
  );
}
