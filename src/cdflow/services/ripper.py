"""Cancellable secure CDDA extraction and audio encoding."""

from __future__ import annotations

import errno
import math
import os
import re
import shutil
import string
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from cdflow.app.constants import DEFAULT_FILENAME_PATTERN, DEFAULT_MUSIC_DIR, DEFAULT_RIP_FORMAT
from cdflow.models.album import Album
from cdflow.models.disc import Drive
from cdflow.models.track import Track

from ._qt import QObject, Signal, Slot
from .library import LibraryRepository
from .subprocess_env import host_process_environment


class RipFormat(StrEnum):
    FLAC = "flac"
    WAV = "wav"
    MP3 = "mp3"


class RipError(RuntimeError):
    pass


class RipCancelled(RipError):
    pass


@dataclass(frozen=True, slots=True)
class RipOptions:
    output_directory: Path = DEFAULT_MUSIC_DIR
    format: RipFormat = RipFormat(DEFAULT_RIP_FORMAT)
    quality: str = "lossless"
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    organize_by_album: bool = True
    embed_metadata: bool = True
    embed_artwork: bool = True
    artwork_path: Path | None = None
    paranoia_mode: str = "full"

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_directory", Path(self.output_directory).expanduser())
        object.__setattr__(self, "format", RipFormat(self.format))
        if self.artwork_path is not None:
            object.__setattr__(self, "artwork_path", Path(self.artwork_path).expanduser())
        if not self.filename_pattern.strip():
            raise ValueError("filename pattern cannot be empty")
        if len(self.filename_pattern) > 512:
            raise ValueError("filename pattern is too long")
        if self.paranoia_mode not in {"disable", "fragment", "overlap", "scratch", "repair", "full"}:
            raise ValueError("unsupported cdparanoiasrc paranoia mode")


@dataclass(frozen=True, slots=True)
class RipJob:
    device: str
    album: Album
    tracks: tuple[Track, ...]
    options: RipOptions = RipOptions()

    def __post_init__(self) -> None:
        if not self.device:
            raise ValueError("an optical device path is required")
        numbers = [track.number for track in self.tracks]
        if len(numbers) != len(set(numbers)):
            raise ValueError("rip job contains duplicate track numbers")

    @property
    def selected_tracks(self) -> tuple[Track, ...]:
        return tuple(track for track in self.tracks if track.selected_for_ripping)


@dataclass(frozen=True, slots=True)
class RipResult:
    job: RipJob
    paths: tuple[Path, ...]
    elapsed_seconds: float


def estimate_required_space(job: RipJob) -> int:
    """Conservatively estimate final output plus peak PCM working space."""

    track_sizes = [max(track.frame_count, 0) * 2352 + 44 for track in job.selected_tracks]
    if not track_sizes:
        return 0
    # Secure extraction first creates a full PCM WAV. During encoding that WAV
    # coexists with the output part and tracks already completed. Treat every
    # final format as PCM-sized, then leave room for container/filesystem slack.
    working_set = sum(track_sizes) + max(track_sizes)
    return math.ceil(working_set * 1.10) + 64 * 1024 * 1024


_FORBIDDEN_FILENAME = re.compile(r"[<>:\"/\\|?*\x00-\x1f\x7f]+")
_WHITESPACE = re.compile(r"\s+")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_FILENAME_FIELDS = frozenset({"track", "title", "artist", "album", "year", "disc_id"})
_FFMPEG_AUDIO_ENCODER = re.compile(r"^\s*A\S*\s+(?P<name>\S+)", re.MULTILINE)


def sanitize_filename_component(
    value: object,
    *,
    replacement: str = "_",
    max_bytes: int = 180,
) -> str:
    """Return a safe single path component without silently changing directory."""

    if not replacement or _FORBIDDEN_FILENAME.search(replacement) or replacement in {".", ".."}:
        raise ValueError("replacement must be a non-empty filename-safe string")
    if max_bytes < 8:
        raise ValueError("max_bytes must be at least 8")
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = "".join(
        " " if character.isspace() else replacement if unicodedata.category(character).startswith("C") else character
        for character in normalized
    )
    normalized = _FORBIDDEN_FILENAME.sub(replacement, normalized)
    normalized = re.sub(r"\.{2,}", replacement, normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip(" .")
    while replacement * 2 in normalized:
        normalized = normalized.replace(replacement * 2, replacement)
    if not normalized or not normalized.strip(f" .{replacement}") or normalized in {".", ".."}:
        normalized = "Untitled"
    if normalized.partition(".")[0].upper() in _WINDOWS_RESERVED:
        normalized = f"_{normalized}"
    encoded = normalized.encode("utf-8")
    if len(encoded) > max_bytes:
        encoded = encoded[:max_bytes]
        while True:
            try:
                normalized = encoded.decode("utf-8").rstrip(" .")
                break
            except UnicodeDecodeError as error:
                encoded = encoded[: error.start]
        normalized = normalized or "Untitled"
    return normalized


def render_filename(pattern: str, track: Track, album: Album) -> str:
    """Render the documented filename fields while rejecting format traversal tricks."""

    formatter = string.Formatter()
    for _literal, field_name, format_spec, conversion in formatter.parse(pattern):
        if field_name is None:
            continue
        if field_name not in _FILENAME_FIELDS:
            raise ValueError(f"unknown filename field: {field_name!r}")
        if "{" in format_spec or "}" in format_spec:
            raise ValueError("nested filename format fields are not supported")
        if format_spec and (field_name != "track" or format_spec not in {"d", "02d", "03d"}):
            raise ValueError(f"unsupported filename format for {field_name!r}: {format_spec!r}")
        if conversion not in (None, "s"):
            raise ValueError(f"unsupported filename conversion: !{conversion}")
    values = {
        "track": track.number,
        "title": track.title,
        "artist": track.artist or album.artist,
        "album": album.title,
        "year": album.year,
        "disc_id": album.disc_id,
    }
    try:
        rendered = formatter.vformat(pattern, (), values)
    except (KeyError, ValueError, IndexError) as error:
        raise ValueError(f"invalid filename pattern: {error}") from error
    return sanitize_filename_component(rendered)


def unique_output_path(path: str | Path, *, reserved: set[Path] | None = None) -> Path:
    """Choose a non-existing path using human-readable ``(2)`` suffixes."""

    candidate = Path(path)
    unavailable = reserved or set()
    if not candidate.exists() and candidate not in unavailable:
        return candidate
    counter = 2
    while True:
        numbered = candidate.with_name(f"{candidate.stem} ({counter}){candidate.suffix}")
        if not numbered.exists() and numbered not in unavailable:
            return numbered
        counter += 1


def parse_ffmpeg_audio_encoders(output: str) -> frozenset[str]:
    """Return the audio encoder names from ``ffmpeg -encoders`` output."""

    return frozenset(match.group("name") for match in _FFMPEG_AUDIO_ENCODER.finditer(output))


class Ripper(QObject):
    """Run one secure extraction job on a background thread."""

    job_started = Signal(object)
    track_started = Signal(int, str)
    track_progress = Signal(int, int)
    overall_progress = Signal(int)
    track_finished = Signal(int, str)
    warning_occurred = Signal(str)
    completed = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)
    running_changed = Signal(bool)

    def __init__(
        self,
        library: LibraryRepository | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._job: RipJob | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def current_job(self) -> RipJob | None:
        return self._job

    def start(self, job: RipJob) -> None:
        if not job.selected_tracks:
            raise ValueError("select at least one track to rip")
        with self._lock:
            if self.is_running:
                raise RuntimeError("a ripping job is already running")
            self._cancel_event = threading.Event()
            self._job = job
            self._thread = threading.Thread(
                target=self._run_job,
                args=(job, self._cancel_event),
                daemon=True,
                name="cdflow-ripper",
            )
            thread = self._thread
        self.running_changed.emit(True)
        self.job_started.emit(job)
        thread.start()

    @Slot()
    def cancel(self) -> None:
        with self._lock:
            self._cancel_event.set()
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    @Slot(object)
    def on_media_removed(self, drive: Drive) -> None:
        job = self._job
        if self.is_running and job and (not drive.device or drive.device == job.device):
            self.cancel()

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.is_running

    def _run_job(self, job: RipJob, cancel_event: threading.Event) -> None:
        started_at = time.monotonic()
        completed_paths: list[Path] = []
        temporary_paths: set[Path] = set()
        try:
            destination = _album_destination(job)
            _preflight_destination(destination, job)
            tracks = job.selected_tracks
            reserved: set[Path] = set()
            extractor = self._select_extractor()
            if job.options.format != RipFormat.WAV:
                self._verify_encoder(job.options.format)
                self._raise_if_cancelled(cancel_event)
            if job.options.format == RipFormat.WAV and job.options.embed_artwork and job.options.artwork_path:
                self.warning_occurred.emit(
                    "Cover artwork is not embedded in WAV output; textual metadata is still supported"
                )
            for index, track in enumerate(tracks):
                self._raise_if_cancelled(cancel_event)
                stem = render_filename(job.options.filename_pattern, track, job.album)
                for known_suffix in (".flac", ".wav", ".mp3"):
                    if stem.casefold().endswith(known_suffix):
                        stem = stem[: -len(known_suffix)]
                        break
                preferred = destination / f"{stem}.{job.options.format.value}"
                target = unique_output_path(preferred, reserved=reserved)
                reserved.add(target)
                self.track_started.emit(track.number, str(target))
                wav_path = _temporary_path(destination, ".wav")
                temporary_paths.add(wav_path)

                def extraction_progress(
                    fraction: float,
                    track_number: int = track.number,
                    track_index: int = index,
                    track_total: int = len(tracks),
                ) -> None:
                    self._emit_progress(track_number, track_index, track_total, fraction * 0.85)

                self._extract_track(extractor, job, track, wav_path, cancel_event, extraction_progress)
                self._raise_if_cancelled(cancel_event)
                if job.options.format == RipFormat.WAV and not job.options.embed_metadata:
                    encoded_path = wav_path
                elif job.options.format == RipFormat.WAV and not shutil.which("ffmpeg"):
                    self.warning_occurred.emit(
                        "ffmpeg is unavailable; the WAV file was saved without embedded metadata"
                    )
                    encoded_path = wav_path
                else:
                    encoded_path = _temporary_path(destination, f".{job.options.format.value}")
                    temporary_paths.add(encoded_path)
                    self._emit_progress(track.number, index, len(tracks), 0.9)
                    self._encode_track(job, track, wav_path, encoded_path, cancel_event)
                self._raise_if_cancelled(cancel_event)
                committed = _commit_without_overwrite(encoded_path, target)
                temporary_paths.discard(encoded_path)
                if wav_path != encoded_path:
                    wav_path.unlink(missing_ok=True)
                    temporary_paths.discard(wav_path)
                completed_paths.append(committed)
                if self._library and job.album.disc_id:
                    self._library.mark_track_ripped(job.album.disc_id, track.number)
                self._emit_progress(track.number, index, len(tracks), 1.0)
                self.track_finished.emit(track.number, str(committed))
            if self._library and job.album.disc_id and len(tracks) == len(job.tracks):
                self._library.mark_ripped(job.album.disc_id)
            result = RipResult(job, tuple(completed_paths), time.monotonic() - started_at)
            self.completed.emit(result)
        except RipCancelled:
            result = RipResult(job, tuple(completed_paths), time.monotonic() - started_at)
            self.cancelled.emit(result)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            for path in temporary_paths:
                with suppress(OSError):
                    path.unlink(missing_ok=True)
            with self._lock:
                self._process = None
                self._job = None
                self._thread = None
            self.running_changed.emit(False)

    def _select_extractor(self) -> str:
        gst_launch = shutil.which("gst-launch-1.0")
        gst_inspect = shutil.which("gst-inspect-1.0")
        if gst_launch and gst_inspect:
            try:
                available = all(
                    subprocess.run(
                        [gst_inspect, "--exists", plugin],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                        env=host_process_environment(gstreamer=True),
                    ).returncode
                    == 0
                    for plugin in ("cdparanoiasrc", "wavenc")
                )
            except (OSError, subprocess.SubprocessError):
                available = False
            if available:
                return gst_launch
        cdparanoia = shutil.which("cdparanoia")
        if cdparanoia:
            return cdparanoia
        raise RipError(
            "No secure CDDA-to-WAV extraction path is available; install cdparanoia or GStreamer's "
            "cdparanoiasrc and wavenc plug-ins"
        )

    @staticmethod
    def _verify_encoder(output_format: RipFormat) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RipError("ffmpeg is required to encode FLAC or MP3 files")
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                check=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                env=host_process_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RipError(f"could not inspect ffmpeg encoders: {error}") from error
        if result.returncode:
            detail = result.stderr.strip() or f"ffmpeg exited with status {result.returncode}"
            raise RipError(f"could not inspect ffmpeg encoders: {detail}")
        required = "flac" if output_format == RipFormat.FLAC else "libmp3lame"
        if required not in parse_ffmpeg_audio_encoders(result.stdout):
            label = "FLAC" if output_format == RipFormat.FLAC else "MP3 (libmp3lame)"
            raise RipError(f"This ffmpeg build does not provide the {label} encoder")

    def _extract_track(
        self,
        extractor: str,
        job: RipJob,
        track: Track,
        output: Path,
        cancel_event: threading.Event,
        progress: Callable[[float], None],
    ) -> None:
        if Path(extractor).name == "gst-launch-1.0":
            command = [
                extractor,
                "-q",
                "cdparanoiasrc",
                f"device={job.device}",
                f"track={track.number}",
                f"paranoia-mode={job.options.paranoia_mode}",
                "!",
                "audioconvert",
                "!",
                "audio/x-raw,format=S16LE,rate=44100,channels=2",
                "!",
                "wavenc",
                "!",
                "filesink",
                f"location={output}",
            ]
        else:
            command = [extractor, "-d", job.device, "-w", str(track.number), str(output)]
        expected_bytes = max(track.frame_count * 2352, 1)

        def file_progress() -> None:
            try:
                fraction = min(max(output.stat().st_size - 44, 0) / expected_bytes, 0.99)
            except OSError:
                fraction = 0.0
            progress(fraction)

        self._run_process(command, cancel_event, progress=file_progress)
        if not output.is_file() or output.stat().st_size <= 44:
            raise RipError(f"the extractor produced no audio for track {track.number}")
        progress(1.0)

    def _encode_track(
        self,
        job: RipJob,
        track: Track,
        source: Path,
        output: Path,
        cancel_event: threading.Event,
    ) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RipError("ffmpeg is required for this output format")
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(source)]
        artwork = job.options.artwork_path
        embed_artwork = bool(
            artwork
            and artwork.is_file()
            and job.options.embed_artwork
            and job.options.format in {RipFormat.FLAC, RipFormat.MP3}
        )
        if embed_artwork:
            command.extend(["-i", str(artwork)])
        command.extend(["-map", "0:a:0"])
        if embed_artwork:
            command.extend(["-map", "1:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"])
        if job.options.format == RipFormat.FLAC:
            command.extend(["-c:a", "flac", *_flac_quality_args(job.options.quality), "-f", "flac"])
        elif job.options.format == RipFormat.MP3:
            command.extend(
                ["-c:a", "libmp3lame", *_mp3_quality_args(job.options.quality), "-id3v2_version", "3", "-f", "mp3"]
            )
        else:
            command.extend(["-c:a", "pcm_s16le", "-f", "wav"])
        if job.options.embed_metadata:
            command.extend(_metadata_arguments(job.album, track, len(job.tracks)))
        command.append(str(output))
        self._run_process(command, cancel_event)
        if not output.is_file() or output.stat().st_size == 0:
            raise RipError(f"encoding track {track.number} produced no output")

    def _run_process(
        self,
        command: list[str],
        cancel_event: threading.Event,
        *,
        progress: Callable[[], None] | None = None,
    ) -> None:
        with tempfile.TemporaryFile(mode="w+b") as diagnostic:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=diagnostic,
                    stderr=subprocess.STDOUT,
                    env=host_process_environment(gstreamer=Path(command[0]).name.startswith("gst-")),
                )
            except OSError as error:
                raise RipError(f"could not start {Path(command[0]).name}: {error}") from error
            with self._lock:
                self._process = process
            try:
                while process.poll() is None:
                    if cancel_event.wait(0.2):
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise RipCancelled("ripping was cancelled")
                    if progress:
                        progress()
                if cancel_event.is_set():
                    raise RipCancelled("ripping was cancelled")
                if process.returncode:
                    diagnostic.seek(0)
                    detail = diagnostic.read().decode("utf-8", "replace").strip()[-4000:]
                    raise RipError(detail or f"{Path(command[0]).name} exited with status {process.returncode}")
            finally:
                with self._lock:
                    if self._process is process:
                        self._process = None

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise RipCancelled("ripping was cancelled")

    def _emit_progress(self, track_number: int, index: int, total: int, fraction: float) -> None:
        local = max(0.0, min(fraction, 1.0))
        self.track_progress.emit(track_number, round(local * 100))
        self.overall_progress.emit(round(((index + local) / total) * 100))


def _album_destination(job: RipJob) -> Path:
    root = job.options.output_directory
    if not job.options.organize_by_album:
        return root
    return root / sanitize_filename_component(job.album.artist) / sanitize_filename_component(job.album.title)


def _preflight_destination(destination: Path, job: RipJob) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise RipError(f"Cannot create rip destination {destination}: {error}") from error
    if not destination.is_dir():
        raise RipError(f"Rip destination is not a directory: {destination}")
    probe: Path | None = None
    try:
        descriptor, probe_name = tempfile.mkstemp(prefix=".cdflow-write-test-", dir=destination)
        os.close(descriptor)
        probe = Path(probe_name)
    except OSError as error:
        raise RipError(f"Rip destination is not writable: {destination}: {error}") from error
    finally:
        if probe is not None:
            with suppress(OSError):
                probe.unlink()
    required = estimate_required_space(job)
    try:
        available = shutil.disk_usage(destination).free
    except OSError as error:
        raise RipError(f"Cannot determine free space for {destination}: {error}") from error
    if available < required:
        raise RipError(
            "Insufficient free space for ripping: "
            f"approximately {_format_bytes(required)} required, {_format_bytes(available)} available"
        )


def _format_bytes(value: int) -> str:
    amount = float(max(value, 0))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def _temporary_path(directory: Path, suffix: str) -> Path:
    descriptor, path = tempfile.mkstemp(prefix=".cdflow-", suffix=suffix, dir=directory)
    os.close(descriptor)
    return Path(path)


def _commit_without_overwrite(source: Path, preferred: Path) -> Path:
    target = preferred
    while True:
        try:
            os.link(source, target)
        except FileExistsError:
            target = unique_output_path(preferred)
            continue
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EXDEV}:
                raise
            target = unique_output_path(preferred)
            try:
                with source.open("rb") as input_file, target.open("xb") as output_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
            except FileExistsError:
                continue
            except Exception:
                target.unlink(missing_ok=True)
                raise
        source.unlink()
        return target


def _metadata_arguments(album: Album, track: Track, track_total: int) -> list[str]:
    metadata = {
        "title": track.title,
        "artist": track.artist or album.artist,
        "album": album.title,
        "album_artist": album.artist,
        "track": f"{track.number}/{track_total}",
        "date": album.year,
        "genre": album.genre,
        "publisher": album.label,
        "musicbrainz_discid": album.disc_id,
    }
    arguments: list[str] = []
    for key, value in metadata.items():
        if value:
            arguments.extend(["-metadata", f"{key}={value}"])
    return arguments


def _flac_quality_args(value: str) -> list[str]:
    normalized = value.strip().casefold()
    level_match = re.search(r"(?:level\s*)?(\d{1,2})", normalized)
    if level_match:
        level = int(level_match.group(1))
    elif "maximum" in normalized or "best" in normalized:
        level = 12
    elif "fast" in normalized:
        level = 3
    else:
        level = 5
    return ["-compression_level", str(max(0, min(level, 12)))]


def _mp3_quality_args(value: str) -> list[str]:
    normalized = value.strip().casefold().replace(" ", "")
    bitrate_match = re.fullmatch(r"(\d{2,3})(?:k|kbps)?", normalized)
    if bitrate_match:
        bitrate = max(64, min(int(bitrate_match.group(1)), 320))
        return ["-b:a", f"{bitrate}k"]
    vbr_match = re.match(r"v([0-9])", normalized)
    quality = int(vbr_match.group(1)) if vbr_match else 2
    return ["-q:a", str(quality)]


__all__ = [
    "RipCancelled",
    "RipError",
    "RipFormat",
    "RipJob",
    "RipOptions",
    "RipResult",
    "Ripper",
    "estimate_required_space",
    "parse_ffmpeg_audio_encoders",
    "render_filename",
    "sanitize_filename_component",
    "unique_output_path",
]
