from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from cdflow import __version__
from cdflow.app.constants import VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_stay_in_sync() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    appstream = ET.parse(PROJECT_ROOT / "packaging" / "io.github.cdflow.CDFlow.metainfo.xml")
    release = appstream.find("./releases/release")

    assert release is not None
    assert project["project"]["version"] == __version__ == VERSION == release.attrib["version"]


def test_pyinstaller_uses_absolute_import_entrypoint() -> None:
    entrypoint = (PROJECT_ROOT / "packaging" / "pyinstaller_entry.py").read_text(encoding="utf-8")

    assert "from cdflow.cli import main" in entrypoint
    assert "from ." not in entrypoint
