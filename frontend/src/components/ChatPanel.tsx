import { useEffect, useRef, useState } from "react";

import { formatDateTime } from "../lib/format";
import { useDashboard } from "../state/DashboardContext";
import { EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { Markdown } from "./Markdown";
import { StatusPill } from "./StatusPill";

export function ChatPanel({ compact = false }: { compact?: boolean }) {
  const { chatMessages, chatBusy, chatError, sendChat, clearChat, activeModel } = useDashboard();
  const [draft, setDraft] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [chatMessages.length, chatBusy]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(200, textarea.scrollHeight)}px`;
  }, [draft]);

  const submit = async () => {
    const message = draft.trim();
    if (!message || chatBusy) return;
    setDraft("");
    await sendChat(message);
  };

  const copy = async (id: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedId(id);
      window.setTimeout(() => setCopiedId((current) => (current === id ? null : current)), 1600);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <div className={`chat-shell${compact ? " compact" : ""}`}>
      <div className="row between" style={{ marginBottom: 8 }}>
        <div className="row" style={{ gap: 8 }}>
          <StatusPill
            status={activeModel?.loaded ? "healthy" : "unknown"}
            label={activeModel ? activeModel.name : "No model reported"}
            title={activeModel?.endpoint ?? "No active reasoning model"}
          />
          {chatBusy ? (
            <span className="tiny muted row" style={{ gap: 6 }}>
              <span className="spinner" aria-hidden="true" /> waiting for local model
            </span>
          ) : null}
        </div>
        {chatMessages.length > 0 ? (
          confirmClear ? (
            <span className="row" style={{ gap: 6 }}>
              <span className="tiny muted">Clear all messages?</span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => setConfirmClear(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                onClick={() => {
                  clearChat();
                  setConfirmClear(false);
                }}
              >
                <Icon name="trash" size={12} /> Clear
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={() => setConfirmClear(true)}
            >
              <Icon name="trash" size={12} /> Clear
            </button>
          )
        ) : null}
      </div>

      <div className="chat-log" ref={logRef} aria-live="polite" aria-label="Conversation history">
        {chatMessages.length === 0 ? (
          <EmptyState
            title="No conversation yet"
            description={
              activeModel?.loaded
                ? "Messages are processed by your local reasoning model. Nothing is sent to a cloud service."
                : "The local reasoning server is not reachable. Start it, then send a message — the dashboard will report the real error if it still fails."
            }
            icon="chat"
          />
        ) : (
          chatMessages.map((message) => (
            <div className="chat-message" data-role={message.role} key={message.id}>
              <span className="chat-avatar" aria-hidden="true">
                {message.role === "user" ? "YOU" : "FR"}
              </span>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className={`chat-bubble${message.error ? " error" : ""}`}>
                  {message.pending ? (
                    <div className="typing" aria-label="Waiting for response">
                      <span />
                      <span />
                      <span />
                    </div>
                  ) : message.role === "assistant" ? (
                    <Markdown content={message.content} />
                  ) : (
                    <div style={{ whiteSpace: "pre-wrap" }}>{message.content}</div>
                  )}

                  {!message.pending ? (
                    <div className="chat-meta">
                      <span>{formatDateTime(message.timestamp)}</span>
                      {message.role === "assistant" && message.model ? (
                        <span title="Model that generated this response">· {message.model}</span>
                      ) : null}
                      {message.role === "assistant" && !message.error ? (
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => void copy(message.id, message.content)}
                          aria-label="Copy response"
                        >
                          <Icon name={copiedId === message.id ? "check" : "copy"} size={11} />
                          {copiedId === message.id ? "Copied" : "Copy"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {chatError ? (
        <div className="alert" data-tone="error" role="alert" style={{ marginBottom: 8 }}>
          <div>
            <span className="alert-title">Request failed</span>
            {chatError}
          </div>
        </div>
      ) : null}

      <div className="chat-composer">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask F.R.I.D.A.Y, or issue a command…  (Enter to send, Shift+Enter for a new line)"
            aria-label="Message"
            rows={2}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={chatBusy || draft.trim().length === 0}
            aria-label="Send message"
          >
            <Icon name="send" size={15} />
            Send
          </button>
        </div>
        <div className="row between tiny muted">
          <span>Enter sends · Shift+Enter adds a line</span>
          <span>Responses are generated locally; the backend does not stream partial tokens.</span>
        </div>
      </div>
    </div>
  );
}
