"""CLI entrypoint for GUI host runtime."""

from __future__ import annotations

import argparse
from dataclasses import replace

from human_sched.gui.config import load_gui_config
from human_sched.gui.host import GuiHost


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the human scheduler GUI host")
    parser.add_argument("--env-file", default=".env", help="Path to env file")
    parser.add_argument("--adapter", help="GUI adapter name (nextjs or terminal)")
    parser.add_argument("--host", help="HTTP bind host")
    parser.add_argument("--port", type=int, help="HTTP bind port")
    parser.add_argument(
        "--frontend-dev",
        action="store_true",
        help="Run Next.js frontend in dev mode with hot reload",
    )
    parser.add_argument(
        "--no-frontend-dev",
        action="store_true",
        help="Disable Next.js frontend dev mode",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        help="Port for Next.js frontend dev server (default: 3000)",
    )
    parser.add_argument(
        "--data-dir",
        help="Directory for persisted GUI data JSON files",
    )
    parser.add_argument("--scenario", help="Seed scenario key")
    parser.add_argument("--open-browser", action="store_true", help="Open browser on startup")
    parser.add_argument(
        "--no-open-browser",
        action="store_true",
        help="Do not open browser on startup",
    )
    parser.add_argument(
        "--disable-timers",
        action="store_true",
        help="Disable scheduler notification timers",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_gui_config(args.env_file)

    if args.adapter:
        config = replace(config, adapter_name=args.adapter)
    if args.host:
        config = replace(config, host=args.host)
    if args.port:
        config = replace(config, port=args.port)
    if args.frontend_dev:
        config = replace(config, frontend_dev=True)
    if args.no_frontend_dev:
        config = replace(config, frontend_dev=False)
    if args.frontend_port:
        config = replace(config, frontend_port=args.frontend_port)
    if args.data_dir:
        config = replace(config, data_dir=args.data_dir)
    if args.scenario:
        config = replace(config, seed_scenario=args.scenario)
    if args.open_browser:
        config = replace(config, open_browser=True)
    if args.no_open_browser:
        config = replace(config, open_browser=False)
    if args.disable_timers:
        config = replace(config, enable_timers=False)

    try:
        host = GuiHost(config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        host.start()
    except KeyboardInterrupt:
        pass
    finally:
        host.stop()


if __name__ == "__main__":
    main()
