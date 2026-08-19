"""Optical-disc inspection and CD table-of-contents parsing."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import threading
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cdflow.models.album import Album
from cdflow.models.disc import Disc, DiscKind, Drive
from cdflow.models.track import CD_FRAMES_PER_SECOND, Track

from ._qt import QObject, Signal
from .library import LibraryRepository
from .subprocess_env import host_process_environment

CD_LEAD_IN_FRAMES = 2 * CD_FRAMES_PER_SECOND
CDROMREADTOCHDR = 0x5305
CDROMREADTOCENTRY = 0x5306
CDROM_MSF = 0x02
CDROM_LEADOUT = 0xAA
CDROM_DATA_TRACK = 0x04


class DiscReadError(RuntimeError):
    pass


class DiscReadCancelled(DiscReadError):
    pass


@dataclass(frozen=True, slots=True)
class TocEntry:
    number: int
    offset_frame: int
    is_audio: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 99:
            raise ValueError("CD track number must be between 1 and 99")
        if self.offset_frame < 0:
            raise ValueError("CD track offset cannot be negative")


@dataclass(frozen=True, slots=True)
class DiscTOC:
    """A Red Book-style TOC using absolute offsets including the lead-in."""

    entries: tuple[TocEntry, ...]
    leadout_frame: int

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("a CD TOC must contain at least one track")
        numbers = [entry.number for entry in self.entries]
        offsets = [entry.offset_frame for entry in self.entries]
        if numbers != list(range(numbers[0], numbers[-1] + 1)):
            raise ValueError("CD track numbers must be consecutive")
        if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
            raise ValueError("CD track offsets must increase")
        if self.leadout_frame <= offsets[-1]:
            raise ValueError("leadout must follow the final track")

    @property
    def first_track(self) -> int:
        return self.entries[0].number

    @property
    def last_track(self) -> int:
        return self.entries[-1].number

    @property
    def disc_id(self) -> str:
        return musicbrainz_disc_id(
            self.first_track,
            self.last_track,
            self.leadout_frame,
            tuple(entry.offset_frame for entry in self.entries),
        )

    @property
    def musicbrainz_toc(self) -> str:
        # MusicBrainz expects the number of tracks here, not the last track
        # number (the two only happen to be equal for the usual track-1 TOC).
        values = [self.first_track, len(self.entries), self.leadout_frame]
        values.extend(entry.offset_frame for entry in self.entries)
        return "+".join(str(value) for value in values)

    @property
    def audio_track_count(self) -> int:
        return sum(entry.is_audio for entry in self.entries)

    @property
    def data_track_count(self) -> int:
        return len(self.entries) - self.audio_track_count

    def to_tracks(self) -> list[Track]:
        tracks: list[Track] = []
        for index, entry in enumerate(self.entries):
            if not entry.is_audio:
                continue
            next_offset = self.entries[index + 1].offset_frame if index + 1 < len(self.entries) else self.leadout_frame
            tracks.append(
                Track(
                    number=entry.number,
                    title=f"Track {entry.number:02d}",
                    start_frame=max(0, entry.offset_frame - CD_LEAD_IN_FRAMES),
                    frame_count=max(0, next_offset - entry.offset_frame),
                )
            )
        return tracks


@dataclass(frozen=True, slots=True)
class DiscInspection:
    disc: Disc
    toc: DiscTOC | None = None
    toc_source: str = ""
    raw_toc: str = ""


@dataclass(frozen=True, slots=True)
class DataDiscInfo:
    label: str = ""
    filesystem_type: str = ""
    uuid: str = ""
    capacity: int = 0
    mount_points: tuple[str, ...] = ()


def musicbrainz_disc_id(
    first_track: int,
    last_track: int,
    leadout_frame: int,
    track_offsets: tuple[int, ...] | list[int],
) -> str:
    """Calculate the MusicBrainz/libdiscid SHA-1 identifier for a CD TOC."""

    if not 1 <= first_track <= last_track <= 99:
        raise ValueError("invalid first/last track numbers")
    expected = last_track - first_track + 1
    if len(track_offsets) != expected:
        raise ValueError(f"expected {expected} track offsets, received {len(track_offsets)}")
    offsets = [0] * 100
    offsets[0] = leadout_frame
    for number, offset in zip(range(first_track, last_track + 1), track_offsets, strict=True):
        offsets[number] = int(offset)
    digest_input = f"{first_track:02X}{last_track:02X}" + "".join(f"{offsets[index]:08X}" for index in range(100))
    digest = hashlib.sha1(digest_input.encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii").replace("+", ".").replace("/", "_").replace("=", "-")


_CD_INFO_TRACK = re.compile(
    r"^\s*(?P<number>\d{1,3})\s*:\s*"
    r"(?P<minute>\d{1,3}):(?P<second>\d{1,2}):(?P<frame>\d{1,2})"
    r"(?:\s+(?P<lsn>-?\d+))?\s*(?P<description>.*)$",
    re.IGNORECASE,
)


def parse_cd_info_output(output: str) -> DiscTOC:
    """Parse the stable track table emitted by libcdio's ``cd-info``."""

    entries: list[TocEntry] = []
    leadout: int | None = None
    for line in output.splitlines():
        match = _CD_INFO_TRACK.match(line)
        if match is None:
            continue
        minute = int(match.group("minute"))
        second = int(match.group("second"))
        frame = int(match.group("frame"))
        absolute_msf = (minute * 60 + second) * CD_FRAMES_PER_SECOND + frame
        lsn_text = match.group("lsn")
        absolute = int(lsn_text) + CD_LEAD_IN_FRAMES if lsn_text is not None else absolute_msf
        description = match.group("description").casefold()
        number = int(match.group("number"))
        if "leadout" in description or number > 99:
            leadout = absolute
            continue
        if not 1 <= number <= 99:
            continue
        is_audio = "audio" in description and "data" not in description
        # libcdio has used "mode 1/2" as well as "data" in different releases.
        if not description.strip():
            is_audio = True
        entries.append(TocEntry(number, absolute, is_audio))
    if not entries or leadout is None:
        raise DiscReadError("cd-info did not return a complete track table")
    entries.sort(key=lambda entry: entry.number)
    return DiscTOC(tuple(entries), leadout)


class DiscReader(QObject):
    """Inspect inserted media off the GUI thread.

    ``inspect`` is useful to command-line callers.  Qt code should normally use
    ``inspect_async`` and consume ``inspection_ready``.
    """

    inspection_started = Signal(object, int)
    inspection_ready = Signal(object, int)
    inspection_failed = Signal(str, int)
    inspection_cancelled = Signal(int)

    def __init__(
        self,
        library: LibraryRepository | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cdflow-disc-reader")
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._future: Future[DiscInspection] | None = None
        self._process: subprocess.Popen[str] | None = None

    def inspect(self, drive: Drive, cancel_event: threading.Event | None = None) -> DiscInspection:
        cancelled = cancel_event or threading.Event()
        if cancelled.is_set():
            raise DiscReadCancelled("disc inspection was cancelled")
        if not drive.media_available:
            return DiscInspection(Disc(kind=DiscKind.NONE, drive=drive))

        warnings: list[str] = []
        toc: DiscTOC | None = None
        raw_toc = ""
        toc_source = ""
        if drive.audio_tracks > 0 or drive.media_name.startswith("optical_cd"):
            try:
                toc, raw_toc, toc_source = self._read_toc(drive.device, cancelled)
            except DiscReadCancelled:
                raise
            except (DiscReadError, OSError) as error:
                warnings.append(str(error))

        audio_count = drive.audio_tracks or (toc.audio_track_count if toc else 0)
        data_count = drive.data_tracks or (toc.data_track_count if toc else 0)
        data_info = DataDiscInfo()
        if data_count or audio_count == 0:
            try:
                data_info = read_data_disc_info(drive.device, cancelled)
            except DiscReadCancelled:
                raise
            except (DiscReadError, OSError) as error:
                warnings.append(str(error))
        if cancelled.is_set():
            raise DiscReadCancelled("disc inspection was cancelled")

        if audio_count and data_count:
            kind = DiscKind.MIXED
        elif audio_count:
            kind = DiscKind.AUDIO
        elif data_count or data_info.filesystem_type:
            kind = DiscKind.DATA
        else:
            kind = DiscKind.UNSUPPORTED

        disc_id = toc.disc_id if toc and audio_count else data_info.uuid
        album: Album | None = None
        if toc and audio_count:
            cached = self._library.get_album(disc_id) if self._library and disc_id else None
            album = _merge_cached_album(cached, toc.to_tracks(), disc_id)
            if self._library and album:
                self._library.upsert_album(album)
        disc = Disc(
            kind=kind,
            drive=drive,
            disc_id=disc_id,
            label=data_info.label,
            filesystem_type=data_info.filesystem_type,
            mount_points=data_info.mount_points,
            capacity=data_info.capacity,
            album=album,
            warnings=warnings,
        )
        return DiscInspection(disc=disc, toc=toc, toc_source=toc_source, raw_toc=raw_toc)

    def inspect_async(self, drive: Drive, *, generation: int = 0) -> None:
        self.cancel()
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_event = cancel_event
        self.inspection_started.emit(drive, generation)
        future = self._executor.submit(self.inspect, drive, cancel_event)
        with self._lock:
            self._future = future

        def completed(result: Future[DiscInspection]) -> None:
            try:
                inspection = result.result()
            except (CancelledError, DiscReadCancelled):
                self.inspection_cancelled.emit(generation)
            except Exception as error:  # errors become non-blocking UI state
                self.inspection_failed.emit(str(error), generation)
            else:
                self.inspection_ready.emit(inspection, generation)

        future.add_done_callback(completed)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_event.set()
            process = self._process
            future = self._future
        if process and process.poll() is None:
            process.terminate()
        if future:
            future.cancel()

    def shutdown(self, *, wait: bool = False) -> None:
        self.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _read_toc(self, device: str, cancel_event: threading.Event) -> tuple[DiscTOC, str, str]:
        if not device:
            raise DiscReadError("the optical drive has no device path")
        errors: list[str] = []
        cd_info = shutil.which("cd-info")
        if cd_info:
            command = [
                cd_info,
                "--no-header",
                "--no-device-info",
                "--no-cddb",
                f"--cdrom-device={device}",
            ]
            try:
                output = self._run_command(command, cancel_event, timeout=20)
                return parse_cd_info_output(output), output, "cd-info"
            except DiscReadCancelled:
                raise
            except DiscReadError as error:
                errors.append(str(error))
        try:
            return read_linux_cdrom_toc(device), "", "linux-cdrom-ioctl"
        except (OSError, DiscReadError) as error:
            errors.append(str(error))
        raise DiscReadError("unable to read CD TOC: " + "; ".join(errors))

    def _run_command(
        self,
        command: list[str],
        cancel_event: threading.Event,
        *,
        timeout: float,
    ) -> str:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=host_process_environment(),
            )
        except OSError as error:
            raise DiscReadError(f"could not start {Path(command[0]).name}: {error}") from error
        with self._lock:
            self._process = process
        try:
            elapsed = 0.0
            while True:
                if cancel_event.wait(0.1):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise DiscReadCancelled("disc inspection was cancelled")
                elapsed += 0.1
                if process.poll() is not None:
                    break
                if elapsed >= timeout:
                    process.kill()
                    process.wait()
                    raise DiscReadError(f"{Path(command[0]).name} timed out")
            stdout, stderr = process.communicate()
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        combined = "\n".join(part for part in (stdout, stderr) if part)
        if process.returncode and not combined.strip():
            raise DiscReadError(f"{Path(command[0]).name} exited with status {process.returncode}")
        return combined


def read_linux_cdrom_toc(device: str) -> DiscTOC:
    """Read a TOC through Linux's stable ``CDROMREADTOC*`` ioctl ABI."""

    descriptor = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    try:
        header = bytearray(2)
        fcntl.ioctl(descriptor, CDROMREADTOCHDR, header, True)
        first_track, last_track = header
        if not 1 <= first_track <= last_track <= 99:
            raise DiscReadError("the kernel returned an invalid CD TOC header")
        entries: list[TocEntry] = []
        for number in range(first_track, last_track + 1):
            offset, control = _read_toc_entry(descriptor, number)
            entries.append(TocEntry(number, offset, not bool(control & CDROM_DATA_TRACK)))
        leadout, _control = _read_toc_entry(descriptor, CDROM_LEADOUT)
        return DiscTOC(tuple(entries), leadout)
    finally:
        os.close(descriptor)


def _read_toc_entry(descriptor: int, track: int) -> tuple[int, int]:
    # linux/cdrom.h aligns the cdrom_addr union to four bytes; 12 bytes covers
    # both 32- and 64-bit Linux ABIs for this structure.
    buffer = bytearray(12)
    buffer[0] = track
    buffer[2] = CDROM_MSF
    fcntl.ioctl(descriptor, CDROMREADTOCENTRY, buffer, True)
    control = buffer[1] >> 4
    minute, second, frame = struct.unpack_from("BBB", buffer, 4)
    return (minute * 60 + second) * CD_FRAMES_PER_SECOND + frame, control


def read_data_disc_info(device: str, cancel_event: threading.Event | None = None) -> DataDiscInfo:
    if not device:
        raise DiscReadError("the optical drive has no device path")
    if cancel_event and cancel_event.is_set():
        raise DiscReadCancelled("disc inspection was cancelled")
    lsblk = shutil.which("lsblk")
    if not lsblk:
        raise DiscReadError("lsblk is required to inspect this data disc")
    command = [
        lsblk,
        "--json",
        "--bytes",
        "--output",
        "PATH,TYPE,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINTS",
        device,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            env=host_process_environment(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DiscReadError(f"could not inspect data disc: {error}") from error
    if cancel_event and cancel_event.is_set():
        raise DiscReadCancelled("disc inspection was cancelled")
    if result.returncode:
        message = result.stderr.strip() or f"lsblk exited with status {result.returncode}"
        raise DiscReadError(message)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DiscReadError("lsblk returned invalid JSON") from error
    nodes = list(_walk_block_devices(payload.get("blockdevices", [])))
    if not nodes:
        return DataDiscInfo()
    resolved_device = _safe_resolve(device)
    node = next(
        (item for item in nodes if _safe_resolve(str(item.get("path", ""))) == resolved_device),
        nodes[0],
    )
    mount_values = node.get("mountpoints") or []
    if isinstance(mount_values, str):
        mount_values = [mount_values]
    mounts = tuple(str(value) for value in mount_values if value)
    return DataDiscInfo(
        label=str(node.get("label") or ""),
        filesystem_type=str(node.get("fstype") or ""),
        uuid=str(node.get("uuid") or ""),
        capacity=int(node.get("size") or 0),
        mount_points=mounts,
    )


def _walk_block_devices(nodes: Any) -> Any:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node
        yield from _walk_block_devices(node.get("children", []))


def _safe_resolve(path: str) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve(strict=False))
    except OSError:
        return path


def _merge_cached_album(cached: Album | None, toc_tracks: list[Track], disc_id: str) -> Album:
    if cached is None:
        return Album(disc_id=disc_id, tracks=toc_tracks)
    by_number = {track.number: track for track in cached.tracks}
    merged = [
        Track(
            number=track.number,
            title=by_number.get(track.number, track).title,
            artist=by_number.get(track.number, track).artist,
            start_frame=track.start_frame,
            frame_count=track.frame_count,
            selected_for_ripping=by_number.get(track.number, track).selected_for_ripping,
            ripped=by_number.get(track.number, track).ripped,
        )
        for track in toc_tracks
    ]
    cached.tracks = merged
    cached.last_inserted = datetime.now(UTC)
    return cached


__all__ = [
    "CD_LEAD_IN_FRAMES",
    "DataDiscInfo",
    "DiscInspection",
    "DiscReadCancelled",
    "DiscReadError",
    "DiscReader",
    "DiscTOC",
    "TocEntry",
    "musicbrainz_disc_id",
    "parse_cd_info_output",
    "read_data_disc_info",
    "read_linux_cdrom_toc",
]
