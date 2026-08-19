from __future__ import annotations

import logging

import pytest

from cdflow import __version__
from cdflow.cli import build_parser, configure_logging


@pytest.mark.parametrize("mode", ["audio", "data", "empty"])
def test_cli_accepts_supported_demo_modes(mode: str) -> None:
    options = build_parser().parse_args(["--demo", mode])

    assert options.demo == mode


def test_cli_rejects_an_unknown_demo_mode() -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["--demo", "vinyl"])

    assert error.value.code == 2


def test_version_flag_matches_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["--version"])

    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == f"CDFlow {__version__}"


def test_debug_logging_requests_debug_level(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration: dict[str, object] = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: configuration.update(kwargs))

    configure_logging(True)

    assert configuration["level"] == logging.DEBUG


def test_cli_accepts_diagnostics_mode() -> None:
    options = build_parser().parse_args(["--diagnose"])

    assert options.diagnose is True
