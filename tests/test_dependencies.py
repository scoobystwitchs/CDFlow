from __future__ import annotations

from cdflow.services.dependencies import DependencyKind, DependencyReport, DependencyStatus


def status(
    name: str,
    available: bool,
    *,
    kind: DependencyKind = DependencyKind.EXECUTABLE,
    required: bool = False,
) -> DependencyStatus:
    return DependencyStatus(name=name, kind=kind, available=available, purpose="test", required=required)


def test_dependency_report_exposes_missing_required_tools() -> None:
    report = DependencyReport(
        (
            status("PySide6", False, kind=DependencyKind.PYTHON, required=True),
            status("dbus-next", True, kind=DependencyKind.PYTHON, required=True),
            status("ffmpeg", False),
        )
    )

    assert report.by_name("dbus-next").available is True  # type: ignore[union-attr]
    assert report.by_name("missing") is None
    assert [item.name for item in report.missing_required] == ["PySide6"]
    assert report.can_monitor_drives


def test_audio_disc_reading_accepts_either_toc_tool() -> None:
    with_cd_info = DependencyReport((status("cd-info", True), status("cdparanoia", False)))
    with_cdparanoia = DependencyReport((status("cd-info", False), status("cdparanoia", True)))
    with_neither = DependencyReport((status("cd-info", False), status("cdparanoia", False)))

    assert with_cd_info.can_read_audio_discs
    assert with_cdparanoia.can_read_audio_discs
    assert not with_neither.can_read_audio_discs


def test_playback_requires_python_binding_and_cdda_plugin() -> None:
    ready = DependencyReport(
        (
            status("PyGObject", True, kind=DependencyKind.PYTHON),
            status("cdparanoiasrc", True, kind=DependencyKind.GSTREAMER_PLUGIN),
        )
    )
    missing_binding = DependencyReport(
        (
            status("PyGObject", False, kind=DependencyKind.PYTHON),
            status("cdparanoiasrc", True, kind=DependencyKind.GSTREAMER_PLUGIN),
        )
    )

    assert ready.can_play_audio_discs
    assert not missing_binding.can_play_audio_discs


def test_compressed_encoding_requires_a_ripping_path_and_ffmpeg() -> None:
    ready = DependencyReport(
        (
            status("cd-info", False),
            status("cdparanoia", True),
            status("PyGObject", False, kind=DependencyKind.PYTHON),
            status("cdparanoiasrc", False, kind=DependencyKind.GSTREAMER_PLUGIN),
            status("ffmpeg", True),
        )
    )
    no_encoder = DependencyReport(
        tuple(item if item.name != "ffmpeg" else status("ffmpeg", False) for item in ready.dependencies)
    )

    assert ready.can_rip_wav
    assert ready.can_encode_compressed_audio
    assert not no_encoder.can_encode_compressed_audio


def test_gstreamer_ripping_requires_source_launcher_and_wav_encoder() -> None:
    ready = DependencyReport(
        (
            status("cdparanoia", False),
            status("gst-launch-1.0", True),
            status("cdparanoiasrc", True, kind=DependencyKind.GSTREAMER_PLUGIN),
            status("wavenc", True, kind=DependencyKind.GSTREAMER_PLUGIN),
        )
    )
    missing_wavenc = DependencyReport(
        tuple(item if item.name != "wavenc" else status("wavenc", False) for item in ready.dependencies)
    )

    assert ready.can_rip_wav
    assert not missing_wavenc.can_rip_wav
