import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DashboardProvider } from "./state/DashboardContext";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root container missing");

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary fallbackTitle="The dashboard failed to start">
      <BrowserRouter>
        <DashboardProvider>
          <App />
        </DashboardProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
