/**
 * One shared dashboard WebSocket for the whole application.
 *
 * Responsibilities: connection lifecycle, exponential-backoff reconnection,
 * heartbeat/ping, sequence-based duplicate suppression, and fan-out to any
 * number of React subscribers. Components never open sockets directly.
 */

import type { DashboardEvent } from "./types";

export type ConnectionState = "connecting" | "connected" | "reconnecting" | "disconnected" | "degraded";

type EventListener = (event: DashboardEvent) => void;
type StateListener = (state: ConnectionState, detail?: string) => void;

const MAX_BACKOFF_MS = 30_000;
const PING_INTERVAL_MS = 20_000;
const SILENCE_LIMIT_MS = 55_000;
const CLOSE_GRACE_MS = 300;

function socketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL as string | undefined;
  if (configured) return configured;
  if (typeof window === "undefined") return "ws://127.0.0.1:8420/ws/dashboard";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/dashboard`;
}

class DashboardSocket {
  private socket: WebSocket | null = null;
  private eventListeners = new Set<EventListener>();
  private stateListeners = new Set<StateListener>();
  private lastSeq = 0;
  private attempt = 0;
  private refCount = 0;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private silenceTimer: number | null = null;
  private closeTimer: number | null = null;
  private manuallyClosed = false;
  private state: ConnectionState = "disconnected";

  get connectionState(): ConnectionState {
    return this.state;
  }

  acquire(): void {
    this.refCount += 1;
    if (this.closeTimer !== null) {
      window.clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
    if (!this.socket && this.state !== "connecting") {
      this.connect();
    }
  }

  release(): void {
    this.refCount = Math.max(0, this.refCount - 1);
    if (this.refCount === 0 && this.closeTimer === null) {
      this.closeTimer = window.setTimeout(() => {
        this.closeTimer = null;
        if (this.refCount === 0) this.disconnect();
      }, CLOSE_GRACE_MS);
    }
  }

  onEvent(listener: EventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  onState(listener: StateListener): () => void {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => this.stateListeners.delete(listener);
  }

  reconnectNow(): void {
    if (this.refCount === 0) return;
    this.attempt = 0;
    this.clearTimers();
    this.socket?.close();
    this.socket = null;
    this.connect();
  }

  private setState(state: ConnectionState, detail?: string): void {
    this.state = state;
    for (const listener of this.stateListeners) listener(state, detail);
  }

  private connect(): void {
    if (this.socket || this.refCount === 0 || typeof window === "undefined") return;
    this.manuallyClosed = false;
    const initial = this.attempt === 0;
    this.setState(initial ? "connecting" : "reconnecting");

    let socket: WebSocket;
    try {
      socket = new WebSocket(socketUrl());
    } catch {
      this.scheduleReconnect("WebSocket could not be created.");
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.lastSeq = 0;
      this.setState("connected");
      this.startPing();
      this.armSilenceTimer();
    };

    socket.onmessage = (message) => {
      this.armSilenceTimer();
      let event: DashboardEvent;
      try {
        event = JSON.parse(String(message.data)) as DashboardEvent;
      } catch {
        return;
      }
      if (!event || typeof event.type !== "string") return;
      if (typeof event.seq === "number") {
        if (event.type !== "connection.ready" && event.seq <= this.lastSeq) return;
        this.lastSeq = Math.max(this.lastSeq, event.seq);
      }
      for (const listener of this.eventListeners) listener(event);
    };

    socket.onerror = () => {
      // onclose always follows; keep the detail for the status bubble.
      this.setState("degraded", "WebSocket error");
    };

    socket.onclose = (closeEvent) => {
      if (this.socket === socket) this.socket = null;
      this.stopPing();
      this.clearSilenceTimer();
      if (this.manuallyClosed || this.refCount === 0) {
        this.setState("disconnected");
        return;
      }
      this.scheduleReconnect(
        closeEvent.reason || `Socket closed (code ${closeEvent.code || "?"})`,
      );
    };
  }

  private scheduleReconnect(detail?: string): void {
    if (this.reconnectTimer !== null || this.refCount === 0) return;
    this.attempt += 1;
    const base = Math.min(1000 * 2 ** (this.attempt - 1), MAX_BACKOFF_MS);
    const delay = Math.round(base * (0.75 + Math.random() * 0.5));
    this.setState("reconnecting", `${detail ?? "Connection lost"} · retrying in ${Math.round(delay / 1000)}s`);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private startPing(): void {
    this.stopPing();
    this.pingTimer = window.setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        try {
          this.socket.send("ping");
        } catch {
          /* the close handler will reconnect */
        }
      }
    }, PING_INTERVAL_MS);
  }

  private stopPing(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private armSilenceTimer(): void {
    this.clearSilenceTimer();
    this.silenceTimer = window.setTimeout(() => {
      this.setState("degraded", "No events received; reconnecting.");
      this.socket?.close();
    }, SILENCE_LIMIT_MS);
  }

  private clearSilenceTimer(): void {
    if (this.silenceTimer !== null) {
      window.clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
  }

  private clearTimers(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopPing();
    this.clearSilenceTimer();
  }

  private disconnect(): void {
    this.manuallyClosed = true;
    this.clearTimers();
    this.socket?.close();
    this.socket = null;
    this.setState("disconnected");
  }

  /** Test-only: drop the connection and all listeners between test cases. */
  resetForTests(): void {
    this.refCount = 0;
    this.attempt = 0;
    this.lastSeq = 0;
    this.clearTimers();
    if (this.closeTimer !== null) {
      window.clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
    this.manuallyClosed = true;
    this.socket?.close();
    this.socket = null;
    this.eventListeners.clear();
    this.stateListeners.clear();
    this.state = "disconnected";
  }
}

export const dashboardSocket = new DashboardSocket();

if (typeof window !== "undefined") {
  window.addEventListener("online", () => dashboardSocket.reconnectNow());
}
