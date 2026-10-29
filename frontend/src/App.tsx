import { useEffect, useState } from "react";
import { api, type Health, type Settings } from "./api";
import Home from "./components/Home";
import ProjectView, { type Tab } from "./components/ProjectView";
import SettingsDialog from "./components/SettingsDialog";

const TABS: Tab[] = ["clips", "youtube", "tiktok"];

/** #/p/<project id>[/<tab>] */
function readHash(): { id: string | null; tab: Tab } {
  const m = location.hash.match(/^#\/p\/(\w+)(?:\/(\w+))?/);
  const tab = (m?.[2] ?? "clips") as Tab;
  return { id: m ? m[1] : null, tab: TABS.includes(tab) ? tab : "clips" };
}

export default function App() {
  const [route, setRoute] = useState(readHash());
  const [health, setHealth] = useState<Health | null>(null);
  // Home-page Settings (a project has its own button); "accounts" scrolls to posting.
  const [settingsOpen, setSettingsOpen] = useState<null | "all" | "accounts">(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const openSettings = async (focus: "all" | "accounts" = "all") => {
    setSettings(await api.settings());
    setSettingsOpen(focus);
  };
  const refreshHealth = () => api.health().then(setHealth).catch((e) => setHealth({ ok: false, error: String(e) }));

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    refreshHealth();
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const open = (id: string | null) => {
    location.hash = id ? `#/p/${id}` : "";
    setRoute({ id, tab: "clips" });
  };

  const setTab = (tab: Tab) => {
    if (!route.id) return;
    history.replaceState(null, "", tab === "clips" ? `#/p/${route.id}` : `#/p/${route.id}/${tab}`);
    setRoute({ ...route, tab });
  };

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => open(null)}>
          <span className="brand-ball" /> RL Clipper
        </button>
        <span className="topbar-sub">goals · saves · epic saves → shorts</span>
        {!route.id && (
          <button className="ghost small topbar-settings" onClick={() => openSettings()}>
            Settings
          </button>
        )}
      </header>
      {health && !health.ok && <div className="banner error">Backend problem: {health.error}</div>}
      {route.id ? (
        <ProjectView id={route.id} tab={route.tab} onTab={setTab} onClose={() => open(null)} />
      ) : (
        <Home onOpen={open} health={health} onSettings={openSettings} />
      )}
      {settingsOpen && settings && !route.id && (
        <SettingsDialog
          settings={settings}
          focus={settingsOpen === "accounts" ? "accounts" : null}
          onClose={() => {
            setSettingsOpen(null);
            refreshHealth(); // a Connect may have happened in the meantime
          }}
          onSaved={() => {
            setSettingsOpen(null);
            refreshHealth();
          }}
        />
      )}
      <footer className="credit">
        RL Clipper · created by{" "}
        <a href="https://github.com/Youssof-Kandil" target="_blank" rel="noreferrer">
          Youssof Kandil (@Youssof-Kandil)
        </a>{" "}
        ·{" "}
        <a href="https://github.com/Youssof-Kandil/rl-clipper" target="_blank" rel="noreferrer">
          source
        </a>{" "}
        · Apache-2.0
      </footer>
    </div>
  );
}
