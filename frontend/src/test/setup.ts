import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { MockWebSocket } from "./mockWebSocket";
import { dashboardSocket } from "../lib/ws";

beforeEach(() => {
  MockWebSocket.reset();
  vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  dashboardSocket.resetForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
