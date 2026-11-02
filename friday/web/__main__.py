"""``python -m friday.web`` — start the dashboard server on localhost.

Binds to 127.0.0.1 only. Use ``--port``/``--host`` deliberately if you need a
different interface; exposing this server beyond loopback is not recommended
because it can read system telemetry and invoke permitted local tools.
"""
from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="F.R.I.D.A.Y dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--log-level", default="info")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Auto-reload on source changes (development only).",
    )
    args = parser.parse_args()

    uvicorn.run(
        "friday.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
