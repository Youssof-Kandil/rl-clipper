import { useEffect, useState } from "react";
import { api, type Accounts, type ExportFile, type Platform, type Project } from "../api";
import JobBar from "./JobBar";

const LABEL: Record<Platform, string> = { youtube: "YouTube", tiktok: "TikTok" };
const TITLE_MAX: Record<Platform, number> = { youtube: 100, tiktok: 2200 };

/** "…_tiktok_02_epic_save_05-01.mp4" -> "Epic save"; compiled videos -> highlights. */
function defaultTitle(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("compiled")) return "Rocket League highlights";
  if (n.includes("epic_save")) return "Epic save";
  if (n.includes("goal")) return "Goal";
  if (n.includes("save")) return "Save";
  return "Rocket League clip";
}

function remember(key: string, value?: string): string {
  try {
    if (value !== undefined) localStorage.setItem(`rlc.${key}`, value);
    return localStorage.getItem(`rlc.${key}`) ?? "";
  } catch {
    return value ?? "";
  }
}

const mb = (b: number) => `${(b / 1e6).toFixed(0)} MB`;

interface Props {
  project: Project;
  onRefresh: () => void;
  onError: (msg: string) => void;
  /** Open Settings at Accounts. */
  onSetup: () => void;
}

/** Post exported files to YouTube (Shorts or regular) and TikTok (inbox draft or direct). */
export default function PublishPanel({ project, onRefresh, onError, onSetup }: Props) {
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [files, setFiles] = useState<ExportFile[]>([]);
  const [form, setForm] = useState<{ platform: Platform; file: ExportFile } | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [privacy, setPrivacy] = useState("private");
  const [schedule, setSchedule] = useState("");
  const [tiktokOptions, setTiktokOptions] = useState<{ name: string; options: string[] } | null>(null);

  const exportDone = ["export_youtube", "export_tiktok", "export"].map((k) => project.job_status[k]?.status).join();
  useEffect(() => {
    api.accounts().then(setAccounts).catch(() => {});
    api.exportsList(project.id).then(setFiles).catch(() => {});
  }, [project.id, exportDone]);
  // Pick up a Connect done in Settings without reloading the page.
  useEffect(() => {
    const onFocus = () => api.accounts().then(setAccounts).catch(() => {});
    window.addEventListener("focus", onFocus);
    const t = setInterval(onFocus, 5000);
    return () => {
      window.removeEventListener("focus", onFocus);
      clearInterval(t);
    };
  }, []);

  const open = async (platform: Platform, file: ExportFile) => {
    setForm({ platform, file });
    const base = defaultTitle(file.name);
    setTitle(platform === "youtube" ? `${base} #RocketLeague` : `${base} 🔥 #rocketleague #rl #gaming`);
    setDescription(remember(`desc.${platform}`) || (platform === "youtube" ? "Clipped with RL Clipper." : ""));
    setTags(remember("tags.youtube") || "Rocket League, RL, gaming, shorts");
    setPrivacy(platform === "youtube" ? remember("privacy.youtube") || "private" : "");
    setSchedule("");
    setTiktokOptions(null);
    if (platform === "tiktok" && accounts?.tiktok.direct_post) {
      try {
        const info = await api.tiktokCreatorInfo();
        const options = info.privacy_level_options ?? [];
        setTiktokOptions({ name: info.creator_nickname ?? "", options });
        setPrivacy(options.includes("SELF_ONLY") ? "SELF_ONLY" : options[0] ?? "");
      } catch (e) {
        onError(String((e as Error).message));
      }
    }
  };

  const submit = async () => {
    if (!form) return;
    const { platform, file } = form;
    remember(`desc.${platform}`, description);
    if (platform === "youtube") {
      remember("tags.youtube", tags);
      remember("privacy.youtube", privacy);
    }
    try {
      await api.publish(project.id, {
        platform,
        file: file.path,
        title,
        description: platform === "youtube" ? description : "",
        tags: platform === "youtube" ? tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
        privacy,
        publish_at: platform === "youtube" && schedule ? new Date(schedule).toISOString() : null,
      });
      setForm(null);
      onRefresh();
    } catch (e) {
      onError(String((e as Error).message));
    }
  };

  const jobs = (["youtube", "tiktok"] as Platform[]).map((p) => ({ p, job: project.job_status[`publish_${p}`] }));
  const posts = [...(project.posts ?? [])].reverse().slice(0, 8);
  const ready = (p: Platform) => !!accounts?.[p].connected;

  return (
    <section className="card seq-publish">
      <div className="row spread">
        <h3>Post</h3>
        <span className="row">
          <span className="muted small-text">
            {(["youtube", "tiktok"] as Platform[]).map((p) => `${LABEL[p]}: ${ready(p) ? accounts![p].name || "connected" : "not connected"}`).join(" · ")}
          </span>
          <button className={`small ${ready("youtube") && ready("tiktok") ? "ghost" : "primary"}`} onClick={onSetup}>
            {ready("youtube") && ready("tiktok") ? "Accounts" : "Set up posting"}
          </button>
        </span>
      </div>
      {!ready("youtube") && !ready("tiktok") && <p className="hint">Connect YouTube or TikTok to post exports from here.</p>}
      {!files.length && <p className="muted">Export something first; your exports appear here.</p>}
      <ul className="publish-list">
        {files.map((f) => {
          const vertical = (f.height ?? 0) > (f.width ?? 0);
          return (
            <li key={f.path} title={f.path}>
              <span className="pl-name">{f.name}</span>
              <span className="muted">
                {vertical ? "9:16" : "16:9"} · {f.duration ? `${Math.round(f.duration)}s` : "?"} · {mb(f.size)}
              </span>
              {(["youtube", "tiktok"] as Platform[]).map((p) => (
                <button
                  key={p}
                  className={`small ${form?.file.path === f.path && form.platform === p ? "primary" : "ghost"}`}
                  disabled={!ready(p)}
                  title={ready(p) ? `Post to ${LABEL[p]}` : `Connect ${LABEL[p]} in Settings → Accounts`}
                  onClick={() => open(p, f)}
                >
                  {LABEL[p]}
                </button>
              ))}
            </li>
          );
        })}
      </ul>

      {form && (
        <div className="publish-form">
          <strong>
            Post {form.file.name} to {LABEL[form.platform]}
          </strong>
          <label>
            {form.platform === "youtube" ? "Title" : "Caption"}
            {form.platform === "youtube" ? (
              <input value={title} maxLength={TITLE_MAX.youtube} onChange={(e) => setTitle(e.target.value)} />
            ) : (
              <textarea value={title} maxLength={TITLE_MAX.tiktok} onChange={(e) => setTitle(e.target.value)} />
            )}
            <span className="count">
              {title.length}/{TITLE_MAX[form.platform]}
              {form.platform === "youtube" && (form.file.height ?? 0) > (form.file.width ?? 0) && " · #Shorts is added automatically"}
            </span>
          </label>
          {form.platform === "youtube" && (
            <>
              <label>
                Description
                <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
              <label>
                Tags (comma separated)
                <input value={tags} onChange={(e) => setTags(e.target.value)} />
              </label>
              <div className="row">
                <label>
                  Visibility
                  <select value={schedule ? "private" : privacy} disabled={!!schedule} onChange={(e) => setPrivacy(e.target.value)}>
                    <option value="private">Private</option>
                    <option value="unlisted">Unlisted</option>
                    <option value="public">Public</option>
                  </select>
                </label>
                <label>
                  Schedule (optional)
                  <input type="datetime-local" value={schedule} onChange={(e) => setSchedule(e.target.value)} />
                </label>
              </div>
              <p className="hint">
                {schedule
                  ? "Uploads now as private and goes public at that time, even if your PC is off."
                  : "Until your Google project passes YouTube's API audit, YouTube keeps every upload private: publish it in YouTube Studio."}
              </p>
            </>
          )}
          {form.platform === "tiktok" &&
            (accounts?.tiktok.direct_post ? (
              <label>
                Who can see it{tiktokOptions?.name ? ` (posting as ${tiktokOptions.name})` : ""}
                <select value={privacy} onChange={(e) => setPrivacy(e.target.value)}>
                  {(tiktokOptions?.options ?? []).map((o) => (
                    <option key={o} value={o}>
                      {o.replace(/_/g, " ").toLowerCase()}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="hint">
                Sends the video to your TikTok inbox as a draft. Open TikTok, tap the notification, add sounds or edits, and post. The caption
                is kept here for you to paste.
              </p>
            ))}
          <div className="row">
            <button className="primary" onClick={submit} disabled={!title.trim() || (form.platform === "tiktok" && !!accounts?.tiktok.direct_post && !privacy)}>
              {form.platform === "tiktok" && !accounts?.tiktok.direct_post ? "Send to TikTok inbox" : `Post to ${LABEL[form.platform]}`}
            </button>
            {form.platform === "tiktok" && !accounts?.tiktok.direct_post && (
              <button className="ghost small" onClick={() => navigator.clipboard?.writeText(title)}>
                Copy caption
              </button>
            )}
            <button className="ghost" onClick={() => setForm(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {jobs.map(
        ({ p, job }) =>
          job &&
          job.status !== "done" && <JobBar key={p} label={`Posting to ${LABEL[p]}`} job={job} onCancel={() => api.cancelJob(job.id)} />,
      )}

      {posts.length > 0 && (
        <ul className="posts">
          {posts.map((post) => (
            <li key={`${post.platform}-${post.remote_id}`}>
              ✓ {LABEL[post.platform]}
              {post.short ? " Short" : ""} · {post.name} ·{" "}
              {post.platform === "tiktok" && post.mode === "inbox" ? (
                <span>draft in your TikTok inbox</span>
              ) : (
                <a href={post.url} target="_blank" rel="noreferrer">
                  {post.publish_at ? `scheduled for ${new Date(post.publish_at).toLocaleString()}` : post.privacy}
                </a>
              )}
              {post.forced_private && <span className="note"> (kept private by YouTube: your Google project isn't audited yet)</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
