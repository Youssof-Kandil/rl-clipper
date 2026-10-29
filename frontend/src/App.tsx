import { useEffect, useState } from "react";
import { api, type Health } from "./api";
import Home from "./components/Home";
import ProjectView, { type Tab } from "./components/ProjectView";

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

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    api.health().then(setHealth).catch((e) => setHealth({ ok: false, error: String(e) }));
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
      </header>
      {health && !health.ok && <div className="banner error">Backend problem: {health.error}</div>}
      {route.id ? (
        <ProjectView id={route.id} tab={route.tab} onTab={setTab} onClose={() => open(null)} />
      ) : (
        <Home onOpen={open} health={health} />
      )}
    </div>
  );
}
