import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  error: Error | null;
  info: string;
}

/** Keeps a rendering failure in one panel instead of blanking the dashboard. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.setState({ error, info: info.componentStack ?? "" });
    // Local-only logging; never transmitted anywhere.
    console.error("[dashboard] render error", error);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="alert" data-tone="error" role="alert">
          <div>
            <span className="alert-title">{this.props.fallbackTitle ?? "This panel failed to render"}</span>
            <p className="mono tiny">{this.state.error.message}</p>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              style={{ marginTop: 8 }}
              onClick={() => this.setState({ error: null, info: "" })}
            >
              Retry panel
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
