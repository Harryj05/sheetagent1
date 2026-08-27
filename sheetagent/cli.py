"""Command-line entrypoint.

    python -m sheetagent "Create a sample employee CSV and import it into Excel and Google Sheets."
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent import MissingCredentials, SheetAgent, render_report
from .config import Config
from .events import Event
from .logging_setup import setup_logging

DEFAULT_PROMPT = ("Create a sample employee CSV with 20 rows and import it into "
                  "Excel and Google Sheets, then confirm both imports.")

_ICONS = {"run_started": "▶", "plan_ready": "🗺", "step_started": "→",
          "step_progress": "·", "step_succeeded": "✓", "step_failed": "✗",
          "run_finished": "■", "assistant_message": "💬"}

_ASCII_ICONS = {"run_started": ">", "plan_ready": "#", "step_started": "->",
                "step_progress": ".", "step_succeeded": "[OK]",
                "step_failed": "[FAIL]", "run_finished": "=",
                "assistant_message": "~"}


def _pick_icons(stream) -> dict[str, str]:
    """A cp1252 console raises on '✓'; the progress feed must never be the
    thing that breaks the run, so degrade to ASCII when the terminal can't
    encode the glyphs."""
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "".join(_ICONS.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _ASCII_ICONS
    return _ICONS


def _printer(quiet: bool, stream=None):
    # Progress goes to stderr so that --json emits parseable JSON on stdout.
    stream = stream if stream is not None else sys.stderr
    icons = _pick_icons(stream)

    def emit(event: Event) -> None:
        if quiet and event.kind in {"step_progress", "assistant_message"}:
            return
        if event.kind == "run_finished":
            # the full report is printed once, after the run
            print(f"{icons['run_finished']} Run finished", file=stream, flush=True)
            return
        icon = icons.get(event.kind, icons["step_progress"])
        print(f"{icon} {event.message}", file=stream, flush=True)
    return emit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheetagent",
        description="Autonomous agent: employee CSV → Excel → Google Sheets.")
    parser.add_argument("prompt", nargs="*", help="Natural-language request.")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml.")
    parser.add_argument("--test-mode", action="store_true",
                        help="FOR CI AND OFFLINE TESTING ONLY. Replaces the model "
                             "planner with a fixed deterministic plan that does no "
                             "reasoning and selects no tools. Not a supported way "
                             "to run the agent; without it an API key is required.")
    parser.add_argument("--excel-engine", choices=["auto", "com", "openpyxl"],
                        help="Override the Excel engine.")
    parser.add_argument("--rows", type=int, help="Row count hint appended to the prompt.")
    parser.add_argument("--json", action="store_true",
                        help="Print the machine-readable run result instead of prose.")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--log-level", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load(args.config)
    if args.excel_engine:
        config.excel.engine = args.excel_engine
    if args.log_level:
        config.log_level = args.log_level
    setup_logging(config.log_level, config.log_dir)

    prompt = " ".join(args.prompt).strip() or DEFAULT_PROMPT
    if args.rows:
        prompt += f" Use exactly {args.rows} rows."

    test_planner = None
    if args.test_mode:
        try:
            # Imported lazily and from tests/ on purpose: the deterministic
            # planner is a test double, not part of the shipped package.
            from tests.support.deterministic_planner import deterministic_test_planner
        except ImportError:
            print("--test-mode requires the tests/ directory, which is not "
                  "present in this installation.", file=sys.stderr)
            return 2
        test_planner = deterministic_test_planner
        print("WARNING: --test-mode is active. The plan below is fixed and no "
              "model reasoning was applied.", file=sys.stderr)

    try:
        agent = SheetAgent(config=config, test_planner=test_planner)
    except MissingCredentials as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    agent.events.subscribe(_printer(args.quiet))
    result = agent.run(prompt)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print()
        print(result.report or render_report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
