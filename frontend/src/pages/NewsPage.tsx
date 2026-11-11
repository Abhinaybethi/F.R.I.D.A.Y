import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { Icon } from "../components/Icon";
import { LoadingState } from "../components/LoadingState";
import { StatusPill } from "../components/StatusPill";
import { api } from "../lib/api";
import { useDashboard } from "../state/DashboardContext";

interface NewsArticle {
  id?: string;
  title?: string;
  text?: string;
  content?: string;
  excerpt?: string;
  summary?: string;
  timestamp?: string;
  model?: string;
  source?: string;
}

const REFRESH_INTERVAL_MS = 30 * 60 * 1000;

export function NewsPage() {
  const { voice } = useDashboard();
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const loadNews = async () => {
      setLoading(true);
      setError(null);
      try {
        // Search F.R.I.D.A.Y's knowledge base for recent entries.
        const result = await api.search("recent updates news developments");
        if (!cancelled) {
          setArticles(Array.isArray(result) ? (result as NewsArticle[]) : [result as NewsArticle]);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load news");
          setLoading(false);
        }
      }
    };

    loadNews();

    if (!autoRefresh) {
      return () => {
        cancelled = true;
      };
    }

    // Refresh news every 30 minutes while the page is open.
    const interval = setInterval(() => {
      loadNews();
    }, REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [reloadKey, autoRefresh]);

  const refresh = useCallback(() => setReloadKey((key) => key + 1), []);

  if (loading) {
    return (
      <div className="page">
        <div className="page-header">
          <span className="eyebrow">News</span>
          <h1>Latest Updates</h1>
          <p className="panel-sub">F.R.I.D.A.Y knowledge base updates &amp; recent activity</p>
        </div>
        <LoadingState label="Loading news" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <div className="page-header">
          <span className="eyebrow">News</span>
          <h1>Latest Updates</h1>
          <p className="panel-sub">F.R.I.D.A.Y knowledge base updates &amp; recent activity</p>
        </div>
        <div className="alert" data-tone="error">
          <div>
            <span className="alert-title">News loading error</span>
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <span className="eyebrow">News</span>
          <h1>Latest Updates</h1>
          <p className="panel-sub">
            F.R.I.D.A.Y knowledge base updates &amp; recent activity
          </p>
        </div>
        <StatusPill
          status={voice?.microphone.available ? "idle" : "unavailable"}
          label={
            voice?.hands_free?.active
              ? `Listening for "Hey ${voice.hands_free.wake_word}"`
              : voice?.microphone.available
                ? "Microphone ready"
                : "No microphone"
          }
        />
      </div>

      <div className="page-body">
        <div className="grid-2">
          {articles.map((article, index) => {
            const title =
              article.title ?? article.text ?? article.content ?? "Untitled";
            const excerpt =
              article.excerpt ??
              article.summary ??
              (article.text ? `${article.text.substring(0, 120)}...` : "");
            const date = article.timestamp
              ? new Date(article.timestamp).toLocaleDateString()
              : "Recent";
            const source =
              article.model ?? article.source ?? "F.R.I.D.A.Y knowledge";

            return (
              <div
                key={article.id ?? article.title ?? index}
                className="panel panel-accent"
                style={{ marginBottom: 16 }}
              >
                <div className="panel-head">
                  <div>
                    <h3 className="panel-sub truncate">{title}</h3>
                    <p className="text-muted small">
                      {source} • {date}
                    </p>
                  </div>
                </div>
                <div className="panel-body">
                  <p
                    className="text-ellipsis truncate"
                    style={{
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      marginBottom: 8,
                    }}
                  >
                    {excerpt}
                  </p>
                  {article.text ? (
                    <a
                      href="#"
                      className="btn btn-sm btn-ghost"
                      style={{ marginTop: 4 }}
                      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
                        event.preventDefault();
                      }}
                    >
                      Read full
                    </a>
                  ) : null}
                </div>
              </div>
            );
          })}

          {articles.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">
                <Icon name="book" size={22} />
              </div>
              <h3>No recent updates</h3>
              <p className="text-muted">
                Check back later for new F.R.I.D.A.Y knowledge base entries.
              </p>
            </div>
          ) : null}
        </div>

        <div className="sidebar">
          <div className="side-section">
            <div className="side-title">News Settings</div>
            <button type="button" className="side-link" onClick={refresh}>
              <span>Refresh now</span>
              <Icon name="refresh" size={14} />
            </button>
            <button
              type="button"
              className="side-link"
              onClick={() => setAutoRefresh((enabled) => !enabled)}
            >
              <span>Toggle auto-refresh</span>
              <Icon name="toggle" size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
