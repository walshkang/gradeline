
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .prompts import styled_error, styled_info, styled_success, styled_url
from .review.exporter import ReviewExportError, export_review_outputs
from .review.importer import ReviewInitError, initialize_review_state
from .review.server import run_review_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local review workflow for CLI grading outputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize review state from grading artifacts.")
    init_parser.add_argument("--output-dir", required=True, type=Path)
    init_parser.add_argument("--rubric-yaml", type=Path, default=None)

    serve_parser = subparsers.add_parser("serve", help="Serve local review web app.")
    serve_parser.add_argument("--output-dir", required=True, type=Path)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    export_parser = subparsers.add_parser("export", help="Export reviewed artifacts.")
    export_parser.add_argument("--output-dir", required=True, type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "init":
        try:
            state_path = initialize_review_state(output_dir=args.output_dir, rubric_yaml=args.rubric_yaml)
        except ReviewInitError as exc:
            styled_error(str(exc))
            return 2
        styled_success(f"Initialized review state: {state_path}")
        return 0

    if args.command == "serve":
        styled_url("Review server", f"http://{args.host}:{args.port}")
        run_review_server(output_dir=args.output_dir, host=args.host, port=args.port)
        return 0

    if args.command == "export":
        try:
            artifacts = export_review_outputs(output_dir=args.output_dir)
        except ReviewExportError as exc:
            styled_error(str(exc))
            return 2
        styled_success("Exported reviewed artifacts:")
        for label, path in artifacts.items():
            styled_info(f"  {label}: {path}")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
