"""
CLI test mode for the research subsystem.

Usage::

    python -m friday.research "latest Python version"
    python -m friday.research "what is a binary tree"          # decision only
    python -m friday.research "search the web for React 20" --max-results 3
    python -m friday.research "latest news" --debug            # debug diagnostics

Prints the research decision, generated queries and normalized results. Never
prints API keys or credentials. ``--debug`` adds the decision, provider,
query/result/failed/evidence counts and total latency.
"""
import argparse
import sys
import time

from friday.research.agent import ResearchAgent
from friday.research.config import ResearchConfig
from friday.research.models import QueryType


def _decide_only(agent: ResearchAgent, query: str) -> int:
    decision = agent.decide(query)
    print("Research Decision")
    print("-----------------")
    print(f"Needs Web: {str(decision.needs_web).lower()}")
    print(f"Type: {decision.query_type}")
    print(f"Reason: {decision.reason}")
    if decision.search_queries:
        print("\nSearch Queries")
        print("--------------")
        for i, q in enumerate(decision.search_queries, start=1):
            print(f"{i}. {q}")
    return 0 if decision.needs_web else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="friday.research",
        description="Phase 1+2 research subsystem: decide, plan, search.",
    )
    parser.add_argument("query", nargs="?", default="", help="user query to research")
    parser.add_argument("--max-results", type=int, default=None,
                        help="results to collect per query (default: config)")
    parser.add_argument("--decide-only", action="store_true",
                        help="show the routing decision without searching")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON payload with decision + results")
    parser.add_argument("--debug", action="store_true",
                        help="print decision, provider, per-query counts and "
                             "total latency (never prints credentials)")
    args = parser.parse_args(argv)

    # Results contain international / Unicode characters (titles, em dashes);
    # the Windows console is often cp1252 and would crash on print(). Emit
    # UTF-8 with an explicit replacement policy so result output never raises.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # non-reconfigureable stream
        pass

    query = (args.query or "").strip()
    if not query:
        parser.print_help()
        return 2

    config = ResearchConfig.load()
    if args.max_results:
        config.max_results = max(1, min(20, args.max_results))
    agent = ResearchAgent(config=config)

    if args.decide_only:
        return _decide_only(agent, query)

    if args.debug:
        decision = agent.decide(query)
        started = time.monotonic()

    response = agent.research(query)

    if args.debug:
        elapsed_total = (time.monotonic() - started) * 1000.0
        planned = decision.search_queries
        err_type = response.error.error_type if response.error else "none"
        print("[DEBUG] decision needs_web=%s type=%s reason=%s" % (
            response.needs_web, response.query_type, decision.reason,
        ))
        print("[DEBUG] resolved_query=%r (CLI has no conversation context)" % query)
        print("[DEBUG] provider=%s max_results=%d timeout=%.1f max_queries=%d" % (
            config.provider, config.max_results, config.timeout, config.max_queries,
        ))
        print("[DEBUG] search_queries=%d results=%d error=%s" % (
            len(planned), len(response.results), err_type,
        ))
        print("[DEBUG] total_latency_ms=%.1f" % elapsed_total)

    if args.json:
        import json
        from datetime import datetime

        payload = {
            "original_query": response.original_query,
            "needs_web": response.needs_web,
            "query_type": response.query_type,
            "search_queries": response.search_queries,
            "provider": response.provider,
            "success": response.success,
            "elapsed_ms": round(response.elapsed_ms, 1),
            "error": None if not response.error else {
                "provider": response.error.provider,
                "error_type": response.error.error_type,
                "message": response.error.message,
                "retryable": response.error.retryable,
            },
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "source": r.source,
                    "published_at": (
                        r.published_at.isoformat()
                        if isinstance(r.published_at, datetime) else None
                    ),
                    "rank": r.rank,
                }
                for r in response.results
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0 if response.success else 1

    decision = ResearchAgent(router=agent.router, config=config).decide(query)
    print("Research Decision")
    print("-----------------")
    print(f"Needs Web: {str(response.needs_web).lower()}")
    print(f"Type: {response.query_type}")
    print(f"Reason: {decision.reason}")
    print(f"Provider: {response.provider or '-'}")

    print("\nSearch Queries")
    print("--------------")
    if not response.search_queries:
        print("(none — query stays on the local pipeline)")
    for i, q in enumerate(response.search_queries, start=1):
        print(f"{i}. {q}")

    print("\nResults")
    print("-------")
    if not response.success:
        error = response.error
        print(f"Search did not run or failed ({error.error_type if error else 'n/a'}): "
              f"{error.message if error else 'no results'}")

    for i, r in enumerate(response.results, start=1):
        print(f"{i}. {r.title}")
        print(f"   {r.url}")
        print(f"   Source: {r.source}")
        if r.snippet:
            print(f"   {r.snippet}")
        if r.published_at:
            print(f"   Published: {r.published_at.isoformat()}")

    if not config.enabled:
        print("\n[NOTE] Web research is disabled. Set WEB_RESEARCH_ENABLED=1 "
              "or research.enabled: true in config.yaml to run searches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())