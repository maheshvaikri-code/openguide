import { Suspense, lazy, useEffect, useRef } from "react";
import { hrefFor, useRoute, type PageName } from "./lib/router";
import { useResource } from "./lib/useResource";
import { ApiProvider, useApi } from "./ui/ApiContext";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { AuditPage } from "./pages/Audit";
import { ContractsPage } from "./pages/Contracts";
import { FleetPage } from "./pages/Fleet";
import { PacksPage } from "./pages/Packs";
import { RunPage } from "./pages/Run";

// three.js is only needed on one page: keep it out of the main bundle.
const TrajectoryPage = lazy(() => import("./pages/Trajectory"));

const NAV: Array<{ page: PageName; label: string; glyph: string }> = [
  { page: "fleet", label: "Fleet", glyph: "▦" },
  { page: "run", label: "Run replay", glyph: "▷" },
  { page: "trajectory", label: "Trajectory", glyph: "∿" },
  { page: "contracts", label: "Contracts", glyph: "§" },
  { page: "packs", label: "Packs", glyph: "◈" },
  { page: "audit", label: "Audit", glyph: "✓" },
];

function Mark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r="11" fill="none" stroke="var(--rule)" strokeWidth="1.5" />
      <path d="M13 13 L21 8" stroke="var(--amber)" strokeWidth="2" strokeLinecap="round" />
      <circle cx="13" cy="13" r="2" fill="var(--strong)" />
      <path d="M4 13h2M20 13h2M13 4v2M13 20v2" stroke="var(--muted)" strokeWidth="1.2" />
    </svg>
  );
}

const SAMPLE = 500;

/** Says how much of the fleet is simulated, from what was actually inspected (never a single run). */
function SimBadge() {
  const api = useApi();
  const [res] = useResource(() => api.runs({ limit: SAMPLE }), []);
  if (res.status !== "ready" || res.data.length === 0) return null;
  const mock = res.data.filter((r) => r.model.startsWith("mock:")).length;
  if (mock === 0) return null;
  const all = mock === res.data.length;
  return (
    <span className="badge sim" title={`Of the ${res.data.length} highest-drift runs checked, ${mock} come from a deterministic simulation, not a real model.`}>
      <span aria-hidden="true">◐</span>
      {all ? "Simulated data" : "Includes simulated runs"}
    </span>
  );
}

/** The control plane is open to anyone who can reach it when no admin token is configured. */
function AuthNotice() {
  const api = useApi();
  const [res] = useResource(() => api.status(), []);
  if (res.status !== "ready" || res.data === null || res.data.auth_required) return null;
  return (
    <div className="notice" role="status" style={{ margin: "12px 28px 0" }}>
      This proxy has no admin token set, so anyone who can reach it can read traces and register contracts.
      Set OPENGUIDE_ADMIN_TOKEN before exposing it beyond this machine.
    </div>
  );
}

function Page() {
  const route = useRoute();
  switch (route.page) {
    case "run":
      return <RunPage runId={route.param} />;
    case "trajectory":
      return (
        <Suspense fallback={<div className="panel state" role="status"><span className="sr-only">Loading 3D view…</span><div className="skeleton" style={{ width: 240 }} /></div>}>
          <TrajectoryPage runId={route.param} />
        </Suspense>
      );
    case "contracts":
      return <ContractsPage selected={route.param} />;
    case "packs":
      return <PacksPage />;
    case "audit":
      return <AuditPage runId={route.param} />;
    default:
      return <FleetPage />;
  }
}

export function App({ api }: { api?: Parameters<typeof ApiProvider>[0]["api"] }) {
  const route = useRoute();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  // Move focus to the new page's content when the route changes, so keyboard and screen-reader
  // users land on it instead of staying on the navigation link they activated.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus({ preventScroll: false });
  }, [route.page, route.param]);
  return (
    <ApiProvider api={api}>
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); main.current?.focus(); }}>Skip to content</a>
      <div className="app">
        <aside className="rail">
          <div className="brand">
            <Mark />
            <div>
              <b>OpenGuide</b>
              <span>Console</span>
            </div>
          </div>
          <nav className="nav" aria-label="Console sections">
            {NAV.map((n) => (
              <a
                key={n.page}
                href={hrefFor(n.page)}
                aria-current={route.page === n.page ? "page" : undefined}
              >
                <span className="g" aria-hidden="true">{n.glyph}</span>
                {n.label}
              </a>
            ))}
          </nav>
          <div className="rail-foot">Behavioral control plane for AI agents</div>
        </aside>
        <div className="main">
          <div className="topbar">
            <span className="grow" />
            <SimBadge />
          </div>
          <AuthNotice />
          <main className="page" id="main" ref={main} tabIndex={-1}>
            <ErrorBoundary resetKey={`${route.page}/${route.param ?? ""}`}>
              <Page />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </ApiProvider>
  );
}
