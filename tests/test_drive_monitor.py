from __future__ import annotations

from cdflow.app.constants import UDISKS_BLOCK_INTERFACE, UDISKS_DRIVE_INTERFACE
from cdflow.services.drive_monitor import _build_drives, _decode_udisks_bytes, _media_token


def managed_objects() -> dict:
    drive_path = "/org/freedesktop/UDisks2/drives/HL_DT_ST"
    block_path = "/org/freedesktop/UDisks2/block_devices/sr2"
    return {
        drive_path: {
            UDISKS_DRIVE_INTERFACE: {
                "Optical": True,
                "Vendor": "HL-DT-ST",
                "Model": "DVDRAM",
                "ConnectionBus": "usb",
                "MediaAvailable": True,
                "Media": "optical_cd",
                "OpticalNumAudioTracks": 12,
                "OpticalNumDataTracks": 0,
                "TimeMediaDetected": 123,
                "Ejectable": True,
            }
        },
        block_path: {
            UDISKS_BLOCK_INTERFACE: {
                "Drive": drive_path,
                "PreferredDevice": list(b"/dev/sr2\0"),
            }
        },
    }


def test_synthetic_udisks_snapshot_builds_the_real_device_mapping() -> None:
    objects = managed_objects()
    drives = _build_drives(objects)

    assert len(drives) == 1
    drive = drives[0]
    assert drive.device == "/dev/sr2"
    assert drive.block_path.endswith("/sr2")
    assert drive.display_name == "HL-DT-ST DVDRAM"
    assert drive.media_available and drive.audio_tracks == 12


def test_media_token_changes_when_a_late_block_device_arrives() -> None:
    objects = managed_objects()
    drive = _build_drives(objects)[0]
    complete = _media_token(drive.object_path, objects, drive)
    without_block = {drive.object_path: objects[drive.object_path]}
    early_drive = _build_drives(without_block)[0]
    early = _media_token(early_drive.object_path, without_block, early_drive)

    assert early != complete
    assert early_drive.device == ""
    assert drive.device == "/dev/sr2"


def test_non_optical_drives_are_ignored() -> None:
    objects = managed_objects()
    drive_path = next(path for path in objects if "/drives/" in path)
    objects[drive_path][UDISKS_DRIVE_INTERFACE]["Optical"] = False
    objects[drive_path][UDISKS_DRIVE_INTERFACE]["MediaCompatibility"] = ["flash"]
    block_path = next(path for path in objects if "/block_devices/" in path)
    objects[block_path][UDISKS_BLOCK_INTERFACE]["PreferredDevice"] = list(b"/dev/sda\0")

    assert _build_drives(objects) == []


def test_udisks_byte_arrays_are_decoded_without_a_trailing_nul() -> None:
    assert _decode_udisks_bytes(b"/dev/sr0\0") == "/dev/sr0"
    assert _decode_udisks_bytes(list(b"/dev/sr1\0")) == "/dev/sr1"
