import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { App } from "../App";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { DashboardProvider } from "../state/DashboardContext";
import {
  ACTIVE_MODEL,
  AGENTS,
  defaultRoutes,
  health,
  installFetchMock,
  metrics,
  overview,
  task,
  type RouteMap,
} from "./fixtures";
import { MockWebSocket } from "./mockWebSocket";

function renderApp(path = "/", routes: RouteMap = defaultRoutes()) {
  installFetchMock(routes);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DashboardProvider>
        <App />
      </DashboardProvider>
    </MemoryRouter>,
  );
}

async function boot() {
  await waitFor(
    () => expect(document.querySelector('[data-booted="true"]')).not.toBeNull(),
    { timeout: 4000 },
  );
}

function openSocket(): MockWebSocket {
  const socket = MockWebSocket.latest();
  if (!socket) throw new Error("The dashboard did not open a WebSocket");
  socket.open();
  return socket;
}

const event = (type: string, overrides: Record<string, unknown> = {}) => ({
  type,
  v: 1,
  seq: 1,
  timestamp: new Date().toISOString(),
  task_id: null,
  status: null,
  source: "test",
  message: "",
  progress: null,
  data: {},
  ...overrides,
});

afterEach(() => {
  window.localStorage.clear();
});

describe("dashboard rendering with real API data", () => {
  it("renders CPU, RAM and GPU values from the metrics endpoint", async () => {
    renderApp();
    await boot();

    expect(screen.getAllByText("12%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("63%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("21%").length).toBeGreaterThan(0);
    expect(screen.getByText(/NVIDIA GeForce RTX 3050/)).toBeInTheDocument();
    expect(screen.getByText(/16 logical|12 logical/i)).toBeInTheDocument();
  });

  it("renders all three layout regions without hiding functionality", async () => {
    renderApp();
    await boot();

    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: /live status/i })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getAllByText(/Local-first/i).length).toBeGreaterThan(0);
  });

  it("shows agents and health reported by the backend", async () => {
    renderApp();
    await boot();

    expect(screen.getAllByText("Research Agent").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Reasoning server/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/services healthy/i).length).toBeGreaterThan(0);
  });

  it("shows N/A rather than inventing GPU metrics when unavailable", async () => {
    const routes = defaultRoutes();
    routes["/api/dashboard/overview"] = () =>
      overview({
        metrics: metrics({
          gpu: {
            available: false,
            name: null,
            utilization_percent: null,
            memory_used_mb: null,
            memory_total_mb: null,
            memory_percent: null,
            temperature_c: null,
            provider: "nvidia-smi",
            reason: "nvidia-smi not found; GPU telemetry unavailable.",
          },
        }),
      });
    renderApp("/", routes);
    await boot();

    expect(screen.getByText(/GPU telemetry unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/NVIDIA GeForce/i)).not.toBeInTheDocument();
  });
});

describe("offline and reconnection states", () => {
  it("surfaces an unreachable backend and never fabricates success", async () => {
    const failing: RouteMap = {};
    const paths = Object.keys(defaultRoutes());
    for (const path of paths) {
      failing[path] = () => {
        throw new Error("ECONNREFUSED 127.0.0.1:8420");
      };
    }
    renderApp("/", failing);

    expect((await screen.findAllByText(/Backend unreachable/i)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/All systems online/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("N/A").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Backend ready/i)).not.toBeInTheDocument();
  });

  it("reports reconnecting after the socket closes", async () => {
    renderApp();
    await boot();
    const socket = openSocket();
    expect((await screen.findAllByText("Live")).length).toBeGreaterThan(0);

    socket.close();
    expect((await screen.findAllByText(/Reconnecting/i)).length).toBeGreaterThan(0);
  });
});

describe("live WebSocket updates", () => {
  it("refreshes the activity timeline when a task event arrives", async () => {
    let currentTask = task();
    const routes = defaultRoutes({
      "/api/activity": () => ({ total: 1, items: [currentTask] }),
    });
    renderApp("/", routes);
    await boot();
    const socket = openSocket();

    currentTask = task({ id: "task-2", title: "Live research task", kind: "research", status: "running" });
    socket.emit(event("task.updated", { seq: 1, task_id: "task-2", status: "running" }));

    expect((await screen.findAllByText("Live research task")).length).toBeGreaterThan(0);
  });

  it("updates agent state when a tool event completes", async () => {
    let agents = AGENTS;
    const routes = defaultRoutes({
      "/api/agents": () => ({ agents, count: agents.length }),
    });
    renderApp("/", routes);
    await boot();
    const socket = openSocket();

    agents = [
      {
        ...AGENTS[1],
        status: "working",
        current_task: "Quantum sweep",
        current_task_id: "task-9",
        last_activity: new Date().toISOString(),
        last_status: "running",
      },
    ];
    socket.emit(event("tool.completed", { seq: 2, status: "completed" }));

    expect(await screen.findByText("Quantum sweep")).toBeInTheDocument();
  });

  it("processes image completion events into activity", async () => {
    let currentTask = task();
    const routes = defaultRoutes({
      "/api/activity": () => ({ total: 1, items: [currentTask] }),
    });
    renderApp("/", routes);
    await boot();
    const socket = openSocket();

    currentTask = task({ id: "img-1", title: "A neon skyline", kind: "image", status: "completed" });
    socket.emit(event("image.completed", { seq: 3, status: "completed", source: "image" }));

    expect((await screen.findAllByText("A neon skyline")).length).toBeGreaterThan(0);
  });

  it("ignores duplicate and out-of-order event sequences", async () => {
    let currentTask = task();
    const routes = defaultRoutes({
      "/api/activity": () => ({ total: 1, items: [currentTask] }),
    });
    renderApp("/", routes);
    await boot();
    const socket = openSocket();

    currentTask = task({ id: "task-3", title: "Sequence ten", kind: "chat", status: "running" });
    socket.emit(event("task.updated", { seq: 10 }));
    expect((await screen.findAllByText("Sequence ten")).length).toBeGreaterThan(0);

    // Let the refresh scheduled by seq 10 finish before mutating the mock data.
    await new Promise((resolve) => setTimeout(resolve, 700));

    currentTask = task({ id: "task-4", title: "Stale duplicate", kind: "chat", status: "running" });
    socket.emit(event("task.updated", { seq: 9 }));
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(screen.queryByText("Stale duplicate")).not.toBeInTheDocument();
  });
});

describe("chat", () => {
  it("sends a turn, renders markdown output and model attribution", async () => {
    const routes = defaultRoutes({
      "/api/chat": () => ({
        task_id: "task-chat",
        response: "It is **10:00** local time.",
        keep_running: true,
        state: "IDLE",
        model: ACTIVE_MODEL,
        timestamp: new Date().toISOString(),
      }),
    });
    renderApp("/chat", routes);
    await screen.findByText(/Chat with F\.R\.I\.D\.A\.Y/i);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "what time is it?");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect(await screen.findByText("10:00")).toBeInTheDocument();
    expect(screen.getAllByText(/Bonsai-8B-Q1_0\.gguf/).length).toBeGreaterThan(0);
    expect(screen.getByText(/what time is it\?/)).toBeInTheDocument();
  });

  it("shows the real backend error and does not fake a reply", async () => {
    const routes = defaultRoutes({
      "/api/chat": () => {
        throw new Error("reasoner offline");
      },
    });
    renderApp("/chat", routes);
    await screen.findByText(/Chat with F\.R\.I\.D\.A\.Y/i);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "hello");
    await user.click(screen.getByRole("button", { name: /send message/i }));

    expect((await screen.findAllByText(/reasoner offline/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/Request failed/i)).toBeInTheDocument();
  });
});

describe("specialised pages", () => {
  it("marks the image backend unhealthy instead of showing success", async () => {
    const degradedHealth = health({
      overall: "degraded",
      components: {
        ...health().components,
        image: { status: "error", detail: "sd-cli executable not found" },
      },
    });
    const routes = defaultRoutes({
      "/api/dashboard/overview": () => overview({ health: degradedHealth }),
      "/api/system/health": () => degradedHealth,
    });
    renderApp("/image", routes);

    expect((await screen.findAllByText(/Image backend not healthy/i)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/sd-cli executable not found/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Idle").length).toBeGreaterThan(0);
  });

  it("renders the knowledge empty state honestly", async () => {
    renderApp("/knowledge");
    expect(await screen.findByText(/No indexable documents found/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("marks unsupported vision understanding explicitly", async () => {
    renderApp("/vision");
    expect(await screen.findByText(/No image-understanding model/i)).toBeInTheDocument();
  });

  it("never exposes a shell execution surface on the code page", async () => {
    renderApp("/code");
    expect(await screen.findByText(/No arbitrary shell execution/i)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /command/i })).not.toBeInTheDocument();
  });
});

describe("error boundary", () => {
  it("contains a render failure inside a panel", () => {
    function Bomb(): ReactElement {
      throw new Error("panel exploded");
    }
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/panel exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry panel/i })).toBeInTheDocument();
  });
});

describe("metrics polling", () => {
  it("updates resource gauges on the next poll without a page refresh", async () => {
    window.localStorage.setItem("friday.dashboard.metricsInterval.v1", "1000");
    let current = metrics();
    const routes = defaultRoutes({
      "/api/system/metrics": () => current,
    });
    renderApp("/", routes);
    await boot();
    expect(screen.getAllByText("12%").length).toBeGreaterThan(0);

    current = metrics({ cpu: { percent: 71.4, logical_cores: 12, physical_cores: 8 } });
    await waitFor(() => expect(screen.getAllByText("71%").length).toBeGreaterThan(0), {
      timeout: 4000,
    });
  });

  it("keeps the agent rail scoped to real backend agents", async () => {
    renderApp("/");
    await boot();
    const aside = screen.getByRole("complementary", { name: /live status/i });
    expect(within(aside).getAllByText(/Agent|Reasoner/i).length).toBeGreaterThan(0);
  });
});
