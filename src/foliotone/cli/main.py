"""Bootstrap command-line interface for the project foundation."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from foliotone import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        prog="foliotone",
        description=(
            "Orchestrate specialist tools to analyze and reconcile e-book and music collections."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show the current bootstrap implementation status.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the FolioTone CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        print(
            "FolioTone W0 foundation: orchestration-first architecture documented; "
            "Docker verification pending."
        )
        print("Next implementation wave after verification: W1 core and persistence.")
        print("Source-media and external-tool mutation commands are not implemented.")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
