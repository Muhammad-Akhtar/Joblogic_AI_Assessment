from __future__ import annotations

import argparse
from pathlib import Path

from desk.app import run_all, run_one, show_usage
from desk.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m desk",
        description="Aerlink disruption desk: work one inbound case, or all of them.",
        epilog=(
            "Examples:\n"
            "  python -m desk run cases/case-01\n"
            "  python -m desk run path/to/inbound.txt\n"
            "  python -m desk run-all\n"
            "  python -m desk usage\n"
            "  python -m desk usage --json\n"
            "  docker compose run --rm desk run cases/case-01\n"
            "  docker compose run --rm desk run-all\n"
            "  docker compose --profile test run --rm test\n"
            "See DEPLOYMENT.md for local and Docker setup."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=False)
    run_p = sub.add_parser("run", help="Work one case directory or inbound.txt")
    run_p.add_argument("path", help="cases/case-01 or a path to inbound.txt")
    sub.add_parser("run-all", help="Work every directory under cases/")
    usage_p = sub.add_parser(
        "usage",
        help="Show this desk's recorded OpenAI tokens and estimated USD (no billing API).",
    )
    usage_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the report as JSON.",
    )
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    settings = Settings.load()
    if args.command == "run":
        return run_one(Path(args.path), settings)
    if args.command == "run-all":
        return run_all(settings)
    if args.command == "usage":
        return show_usage(settings, as_json=args.as_json)
    return 1
