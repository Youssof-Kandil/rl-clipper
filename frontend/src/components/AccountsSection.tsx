import { useEffect, useRef, useState } from "react";
import { api, type Accounts, type Platform, type Settings } from "../api";

const GUIDE = "https://github.com/Youssof-Kandil/rl-clipper/blob/main/docs/publishing.md";

const PLATFORMS: { id: Platform; label: string; idKey: string; secretKey: string; idLabel: string; secretLabel: string }[] = [
  { id: "youtube", label: "YouTube", idKey: "youtube_client_id", secretKey: "youtube_client_secret", idLabel: "Client ID", secretLabel: "Client secret" },
  { id: "tiktok", label: "TikTok", idKey: "tiktok_client_key", secretKey: "tiktok_client_secret", idLabel: "Client key", secretLabel: "Client secret" },
];

interface Props {
  draft: Settings;
  set: (k: string, v: Settings[string]) => void;
  /** Opened from a "Connect" / "Set up posting" button: scroll here and highlight. */
  focus?: boolean;
}

/** Settings → Accounts: your own Google / TikTok app keys, and connecting your accounts. */
export default function AccountsSection({ draft, set, focus }: Props) {
  const [accounts, setAccounts] = useState<Accounts | null>(null);
  const [waiting, setWaiting] = useState<Platform | null>(null);
  const [error, setError] = useState("");
  const here = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focus) here.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focus]);

  const refresh = () => api.accounts().then(setAccounts).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  // While a sign-in tab is open, watch for the account to appear (up to 3 minutes).
  useEffect(() => {
    if (!waiting) return;
    const started = Date.now();
    const t = setInterval(async () => {
      const a = await api.accounts().catch(() => null);
      if (a) setAccounts(a);
      if ((a && a[waiting].connected) || Date.now() - started > 180_000) {
        setWaiting(null);
        clearInterval(t);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [waiting]);

  const connect = async (p: (typeof PLATFORMS)[number]) => {
    setError("");
    if (!String(draft[p.idKey] ?? "").trim() || !String(draft[p.secretKey] ?? "").trim()) {
      setError(`Paste your ${p.label} ${p.idLabel.toLowerCase()} and secret first.`);
      return;
    }
    // Keys must be saved before the server can start the sign-in.
    await api.saveSettings({ [p.idKey]: draft[p.idKey], [p.secretKey]: draft[p.secretKey], tiktok_direct_post: !!draft.tiktok_direct_post });
    api.connect(p.id);
    setWaiting(p.id);
  };

  return (
    <div ref={here} id="accounts" className={`accounts-section ${focus ? "focused" : ""}`}>
      <h3>Accounts (posting)</h3>
      <p className="hint">
        Post exports straight to YouTube and TikTok with your own developer apps.{" "}
        <a href={GUIDE} target="_blank" rel="noreferrer">
          How to get these keys (10 min)
        </a>
      </p>
      {PLATFORMS.map((p) => {
        const a = accounts?.[p.id];
        return (
          <fieldset key={p.id} className="account">
            <legend>
              {p.label}
              {a?.connected ? <span className="acct-ok">connected{a.name ? `: ${a.name}` : ""}</span> : <span className="muted">not connected</span>}
            </legend>
            <label>
              {p.idLabel}
              <input value={String(draft[p.idKey] ?? "")} onChange={(e) => set(p.idKey, e.target.value.trim())} spellCheck={false} />
            </label>
            <label>
              {p.secretLabel}
              <input type="password" value={String(draft[p.secretKey] ?? "")} onChange={(e) => set(p.secretKey, e.target.value.trim())} spellCheck={false} />
            </label>
            {p.id === "tiktok" && (
              <label className="check full">
                <input type="checkbox" checked={!!draft.tiktok_direct_post} onChange={(e) => set("tiktok_direct_post", e.target.checked)} />
                Direct post (needs TikTok's app audit; until then posts are forced to private). Off = drafts in your TikTok inbox.
              </label>
            )}
            <div className="row full">
              {a?.connected ? (
                <>
                  <button type="button" className="small" onClick={() => connect(p)}>
                    Reconnect
                  </button>
                  <button type="button" className="ghost small" onClick={async () => setAccounts(await api.disconnect(p.id))}>
                    Disconnect
                  </button>
                </>
              ) : (
                <button type="button" className="small primary" onClick={() => connect(p)} disabled={waiting === p.id}>
                  {waiting === p.id ? "Waiting for sign-in…" : `Connect ${p.label}`}
                </button>
              )}
            </div>
          </fieldset>
        );
      })}
      {error && <div className="banner error">{error}</div>}
    </div>
  );
}
