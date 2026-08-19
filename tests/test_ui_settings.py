from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdflow.ui.pages.settings import SettingsPage


def test_chosen_settings_destination_is_emitted_for_persistence() -> None:
    app = QApplication.instance() or QApplication([])
    page = SettingsPage()
    emitted: list[dict] = []
    page.settings_changed.connect(emitted.append)

    page.set_destination("/tmp/CDFlow Music")
    app.processEvents()

    assert emitted
    assert emitted[-1]["output_directory"] == "/tmp/CDFlow Music"
