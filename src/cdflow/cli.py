"""Command-line entry point and logging configuration."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cdflow", description="A lightweight Linux CD player and ripper")
    parser.add_argument("--debug", action="store_true", help="enable diagnostic logging")
    parser.add_argument(
        "--demo", choices=("audio", "data", "empty"), help="show deterministic media for UI development"
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="report local playback, ripping, and drive-monitoring capabilities",
    )
    parser.add_argument("--version", action="version", version=f"CDFlow {__version__}")
    return parser


def configure_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not debug:
        logging.getLogger("dbus_next").setLevel(logging.ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    configure_logging(options.debug)
    if options.diagnose:
        return run_diagnostics()
    try:
        from .app.application import run_application
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print("CDFlow requires PySide6. Run ./run.sh after installing the Fedora prerequisites.", file=sys.stderr)
            return 2
        raise
    return run_application(demo_mode=options.demo, debug=options.debug)


def run_diagnostics() -> int:
    """Print a bounded, on-demand capability report without starting the GUI."""

    from .services.audio_player import AudioPlayer
    from .services.dependencies import DependencyDetector

    report = DependencyDetector.detect(refresh=True)
    for dependency in report.dependencies:
        importance = "required" if dependency.required else "optional"
        state = "available" if dependency.available else "missing"
        detail = f" — {dependency.location or dependency.detail}" if dependency.location or dependency.detail else ""
        print(f"{dependency.name}: {state} ({importance}){detail}")

    player = AudioPlayer()
    playback_available = player.available
    player.shutdown()
    print(f"GStreamer CDDA playback backend: {'available' if playback_available else 'unavailable'}")
    return 1 if report.missing_required else 0
