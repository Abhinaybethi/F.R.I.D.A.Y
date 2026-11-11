import { Outlet, useNavigate } from "react-router-dom";

import { useDashboard } from "../state/DashboardContext";
import { ErrorBoundary } from "./ErrorBoundary";
import { Icon } from "./Icon";
import { RightRail } from "./RightRail";
import { Sidebar } from "./Sidebar";
import { TopNavigation } from "./TopNavigation";
import { VoiceHologramOverlay } from "./VoiceHologramOverlay";

export function AppShell() {
  const { bootError, booting, connection, refresh } = useDashboard();

  return (
    <div className="app-shell" data-booted={!booting && !bootError}>
      <TopNavigation />
      <div className="app-body">
        <Sidebar />
        <main className="app-main" id="main-content">
          {bootError ? (
            <div className="alert" data-tone="error" role="alert" style={{ marginBottom: 18 }}>
              <div className="grow">
                <span className="alert-title">Backend unreachable</span>
                {bootError} The dashboard is showing only what it can verify; no sample data is used.
              </div>
              <button type="button" className="btn btn-sm" onClick={() => void refresh()} disabled={booting}>
                <Icon name="refresh" size={12} /> Retry
              </button>
            </div>
          ) : connection === "reconnecting" ? (
            <div className="alert" data-tone="info" role="status" style={{ marginBottom: 18 }}>
              <div className="grow">
                <span className="alert-title">Reconnecting to the live event stream</span>
                REST data still loads; the dashboard will resume live updates automatically.
              </div>
            </div>
          ) : null}

          <ErrorBoundary fallbackTitle="This page failed to render">
            <Outlet />
          </ErrorBoundary>
        </main>
        <aside className="right-rail" aria-label="Live status">
          <ErrorBoundary fallbackTitle="The status rail failed to render">
            <RightRail />
          </ErrorBoundary>
        </aside>
      </div>
      <VoiceHologramOverlay />
    </div>
  );
}

export function useGoBack() {
  const navigate = useNavigate();
  return () => navigate(-1);
}
