export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function InlineSpinner({ label }: { label?: string }) {
  return (
    <span className="row" style={{ gap: 8 }} role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label ? <span className="tiny muted">{label}</span> : null}
    </span>
  );
}
