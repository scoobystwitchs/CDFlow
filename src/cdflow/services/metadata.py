"""Optional MusicBrainz disc metadata lookup and candidate selection."""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from cdflow.app.constants import MUSICBRAINZ_BASE_URL, network_user_agent
from cdflow.models.album import Album
from cdflow.models.track import Track

from ._qt import QObject, Signal
from .disc_reader import DiscTOC
from .library import LibraryRepository

MUSICBRAINZ_RELEASE_INCLUDES = (
    "artist-credits",
    "labels",
    "recordings",
    "release-groups",
    "media",
    "discids",
)
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 64 * 1024
MUSICBRAINZ_DISC_ID = re.compile(r"^[A-Za-z0-9._-]{28}$")
TRANSIENT_HTTP_STATUS = frozenset({429, 502, 503, 504})
MAX_TRANSIENT_RETRIES = 3
LOGGER = logging.getLogger(__name__)


class MetadataLookupError(RuntimeError):
    pass


class MetadataLookupCancelled(MetadataLookupError):
    pass


class MetadataTemporarilyUnavailable(MetadataLookupError):
    pass


def build_musicbrainz_discid_url(disc_id: str, toc: DiscTOC) -> str:
    """Build a Stage 1 MusicBrainz disc identification URL."""

    if disc_id != "-" and not MUSICBRAINZ_DISC_ID.fullmatch(disc_id):
        raise ValueError("invalid MusicBrainz disc ID")
    if toc.first_track != 1:
        raise ValueError("MusicBrainz TOCs must begin with track 1")
    # Use a sequence of pairs so every value goes through urlencode and the
    # resulting query remains straightforward to inspect in tests and logs.
    query = urllib.parse.urlencode(
        (
            ("toc", toc.musicbrainz_toc),
            ("cdstubs", "no"),
            ("fmt", "json"),
        )
    )
    quoted_id = urllib.parse.quote(disc_id, safe="._-")
    return f"{MUSICBRAINZ_BASE_URL}/discid/{quoted_id}?{query}"


def build_musicbrainz_release_url(release_id: str) -> str:
    """Build a Stage 2 MusicBrainz release-detail URL."""

    try:
        normalized_id = str(uuid.UUID(release_id))
    except (ValueError, AttributeError) as error:
        raise ValueError("release ID must be a MusicBrainz UUID") from error
    query = urllib.parse.urlencode((("inc", "+".join(MUSICBRAINZ_RELEASE_INCLUDES)), ("fmt", "json")))
    return f"{MUSICBRAINZ_BASE_URL}/release/{normalized_id}?{query}"


@dataclass(frozen=True, slots=True)
class _DiscReleaseCandidate:
    release: dict[str, Any]
    release_id: str
    medium_position: int
    exact_disc_match: bool
    track_count_match: bool
    toc_match: bool
    official: bool
    has_front_artwork: bool
    has_disambiguation: bool
    reason: str


@dataclass(frozen=True, slots=True)
class MetadataCandidate:
    release_id: str
    release_group_id: str
    medium_position: int
    album: Album
    score: int
    exact_disc_match: bool
    country: str = ""
    status: str = ""
    barcode: str = ""
    has_front_artwork: bool = False


@dataclass(frozen=True, slots=True)
class MetadataLookup:
    disc_id: str
    candidates: tuple[MetadataCandidate, ...]
    confident: bool = False
    from_cache: bool = False

    @property
    def best(self) -> MetadataCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def selected(self) -> MetadataCandidate | None:
        return self.best if self.confident else None


def parse_musicbrainz_response(
    payload: dict[str, Any],
    *,
    disc_id: str,
    local_album: Album,
    toc: DiscTOC | None = None,
    from_cache: bool = False,
) -> MetadataLookup:
    """Convert a MusicBrainz disc lookup response into ranked local models."""

    releases = payload.get("releases")
    if not isinstance(releases, list):
        releases = []
    expected_count = len(local_album.tracks) or (toc.audio_track_count if toc else 0)
    candidates: list[MetadataCandidate] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        medium, exact_match = _select_medium(release, disc_id, expected_count)
        if medium is None:
            continue
        release_id = str(release.get("id") or "")
        if not release_id:
            continue
        album_artist = _artist_credit(release.get("artist-credit")) or local_album.artist
        title = str(release.get("title") or local_album.title)
        date = str(release.get("date") or "")
        year = date[:4] if len(date) >= 4 and date[:4].isdigit() else local_album.year
        release_group = release.get("release-group")
        release_group = release_group if isinstance(release_group, dict) else {}
        genre = _release_genre(release, release_group) or local_album.genre
        label = _release_label(release) or local_album.label
        tracks = _merge_tracks(medium, local_album.tracks, album_artist)
        cover_info = release.get("cover-art-archive")
        has_front_artwork = bool(isinstance(cover_info, dict) and cover_info.get("front", False))
        status = str(release.get("status") or "")
        score = 0
        if exact_match:
            score += 100
        medium_track_count = _as_int(medium.get("track-count")) or len(medium.get("tracks") or [])
        if expected_count and medium_track_count == expected_count:
            score += 40
        if str(medium.get("format") or "").casefold() == "cd":
            score += 10
        if status.casefold() == "official":
            score += 8
        if has_front_artwork:
            score += 3
        if year:
            score += 2
        album = Album(
            disc_id=disc_id,
            title=title,
            artist=album_artist,
            year=year,
            genre=genre,
            label=label,
            artwork_path=local_album.artwork_path,
            tracks=tracks,
            last_inserted=local_album.last_inserted,
            ripped=local_album.ripped,
        )
        candidates.append(
            MetadataCandidate(
                release_id=release_id,
                release_group_id=str(release_group.get("id") or ""),
                medium_position=_as_int(medium.get("position")) or 1,
                album=album,
                score=score,
                exact_disc_match=exact_match,
                country=str(release.get("country") or ""),
                status=status,
                barcode=str(release.get("barcode") or ""),
                has_front_artwork=has_front_artwork,
            )
        )
    candidates.sort(key=_candidate_sort_key)
    # A staged lookup has already selected one discovery candidate using its
    # disc/TOC evidence. This marker also permits a deliberately selected fuzzy
    # TOC match, whose release naturally cannot contain the current disc ID.
    preselected = payload.get("_cdflow-selected") is True
    confident = bool(candidates) if preselected else _is_confident(candidates)
    return MetadataLookup(disc_id, tuple(candidates), confident, from_cache)


class MetadataService(QObject):
    """Fetch MusicBrainz data serially with cache and public rate limiting."""

    lookup_started = Signal(str, int)
    lookup_ready = Signal(object, int)
    lookup_failed = Signal(str, int)
    lookup_cancelled = Signal(int)

    def __init__(
        self,
        library: LibraryRepository | None = None,
        *,
        request_timeout: float = 12.0,
        minimum_request_interval: float = 1.05,
        maximum_transient_retries: int = MAX_TRANSIENT_RETRIES,
        retry_base_delay: float = 1.0,
        retry_jitter: float = 0.2,
        contact: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._library = library
        self._timeout = max(request_timeout, 1.0)
        self._minimum_interval = max(minimum_request_interval, 1.0)
        self._maximum_transient_retries = max(0, min(int(maximum_transient_retries), 5))
        self._retry_base_delay = max(0.0, float(retry_base_delay))
        self._retry_jitter = max(0.0, float(retry_jitter))
        self._contact = contact
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cdflow-metadata")
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._future: Future[MetadataLookup] | None = None
        self._future_disc_id = ""

    def lookup(
        self,
        disc_id: str,
        toc: DiscTOC,
        local_album: Album,
        *,
        force: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> MetadataLookup:
        if not disc_id:
            raise ValueError("MusicBrainz lookup requires a disc ID")
        cancelled = cancel_event or threading.Event()
        if cancelled.is_set():
            raise MetadataLookupCancelled("metadata lookup was cancelled")
        cached = self._library.get_metadata_cache(disc_id) if self._library and not force else None
        if cached:
            LOGGER.debug("MusicBrainz metadata cache hit for disc %s", disc_id)
            return parse_musicbrainz_response(
                cached.payload,
                disc_id=disc_id,
                local_album=local_album,
                toc=toc,
                from_cache=True,
            )
        LOGGER.debug(
            "MusicBrainz metadata cache %s for disc %s",
            "bypassed by explicit refresh" if force else "miss",
            disc_id,
        )
        stale = self._library.get_metadata_cache(disc_id, max_age=None) if self._library else None
        payload, etag, not_modified = self._fetch(disc_id, toc, cancelled, stale.etag if stale else "")
        if not_modified and stale:
            payload = stale.payload
            etag = stale.etag
        if self._library:
            self._library.put_metadata_cache(disc_id, payload, etag=etag)
        result = parse_musicbrainz_response(
            payload,
            disc_id=disc_id,
            local_album=local_album,
            toc=toc,
            from_cache=not_modified,
        )
        if self._library and result.selected:
            self._library.upsert_album(result.selected.album)
        return result

    def lookup_async(
        self,
        disc_id: str,
        toc: DiscTOC,
        local_album: Album,
        *,
        generation: int = 0,
        force: bool = False,
    ) -> bool:
        with self._lock:
            if self._future is not None and not self._future.done() and self._future_disc_id == disc_id:
                LOGGER.debug("Coalesced duplicate MusicBrainz lookup for disc %s", disc_id)
                return False
            self._cancel_event.set()
            previous = self._future
            if previous is not None:
                previous.cancel()
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self.lookup_started.emit(disc_id, generation)
            future = self._executor.submit(
                self.lookup,
                disc_id,
                toc,
                local_album,
                force=force,
                cancel_event=cancel_event,
            )
            self._future = future
            self._future_disc_id = disc_id

        def completed(result: Future[MetadataLookup]) -> None:
            try:
                lookup = result.result()
            except (CancelledError, MetadataLookupCancelled):
                self.lookup_cancelled.emit(generation)
            except Exception as error:
                self.lookup_failed.emit(str(error), generation)
            else:
                self.lookup_ready.emit(lookup, generation)
            finally:
                with self._lock:
                    if self._future is result:
                        self._future = None
                        self._future_disc_id = ""

        future.add_done_callback(completed)
        return True

    def cancel(self) -> None:
        with self._lock:
            self._cancel_event.set()
            future = self._future
        if future:
            future.cancel()

    def shutdown(self, *, wait: bool = False) -> None:
        self.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def set_contact(self, contact: str) -> None:
        self._contact = " ".join(str(contact).split())[:256]

    def _fetch(
        self,
        disc_id: str,
        toc: DiscTOC,
        cancel_event: threading.Event,
        etag: str,
    ) -> tuple[dict[str, Any], str, bool]:
        try:
            disc_url = build_musicbrainz_discid_url(disc_id, toc)
        except ValueError as error:
            raise MetadataLookupError(str(error)) from error
        discovery, _discovery_etag, _ = self._request_json(
            disc_url,
            cancel_event,
            request_description="disc lookup",
            not_found_is_empty=True,
        )
        releases = _payload_releases(discovery)
        LOGGER.debug("MusicBrainz exact disc lookup returned %d release(s)", len(releases))
        used_fuzzy = False
        if not releases:
            used_fuzzy = True
            LOGGER.debug("No exact MusicBrainz disc match; using fuzzy TOC fallback")
            fuzzy_url = build_musicbrainz_discid_url("-", toc)
            discovery, _discovery_etag, _ = self._request_json(
                fuzzy_url,
                cancel_event,
                request_description="fuzzy disc lookup",
                not_found_is_empty=True,
            )
            releases = _payload_releases(discovery)
            LOGGER.debug("MusicBrainz fuzzy TOC lookup returned %d release(s)", len(releases))

        candidates = _rank_disc_releases(releases, disc_id, toc)
        if not candidates:
            return {"releases": []}, "", False
        selected = candidates[0]
        if len(candidates) > 1:
            LOGGER.debug(
                "MusicBrainz candidates: %s",
                "; ".join(f"{candidate.release_id} ({candidate.reason})" for candidate in candidates),
            )
        LOGGER.debug("Selected MusicBrainz release %s: %s", selected.release_id, selected.reason)
        try:
            release_url = build_musicbrainz_release_url(selected.release_id)
        except ValueError as error:
            raise MetadataLookupError(str(error)) from error
        release, response_etag, not_modified = self._request_json(
            release_url,
            cancel_event,
            request_description="release lookup",
            etag=etag,
        )
        if not_modified:
            return {}, etag, True
        if str(release.get("id") or "") != selected.release_id:
            raise MetadataLookupError("MusicBrainz returned an unexpected release response")
        return (
            {
                "releases": [release],
                "_cdflow-selected": True,
                "_cdflow-fuzzy": used_fuzzy,
            },
            response_etag,
            False,
        )

    def _request_json(
        self,
        url: str,
        cancel_event: threading.Event,
        *,
        request_description: str,
        etag: str = "",
        not_found_is_empty: bool = False,
    ) -> tuple[dict[str, Any], str, bool]:
        try:
            user_agent = network_user_agent(self._contact)
        except ValueError as error:
            raise MetadataLookupError(
                "Add a contact email or URL in Settings before using MusicBrainz metadata lookup"
            ) from error
        headers = {"Accept": "application/json", "User-Agent": user_agent}
        if etag:
            headers["If-None-Match"] = etag
        request = urllib.request.Request(url, headers=headers)
        parsed_request = urllib.parse.urlsplit(url)
        LOGGER.debug(
            "MusicBrainz %s request: %s?%s",
            request_description,
            urllib.parse.urlunsplit((parsed_request.scheme, parsed_request.netloc, parsed_request.path, "", "")),
            parsed_request.query,
        )
        with self._request_lock:
            for attempt in range(self._maximum_transient_retries + 1):
                self._wait_for_request_slot(cancel_event)
                try:
                    with urllib.request.urlopen(request, timeout=self._timeout) as response:
                        raw = response.read(MAX_RESPONSE_BYTES + 1)
                        response_etag = str(response.headers.get("ETag") or "")
                    self._last_request_at = time.monotonic()
                    break
                except urllib.error.HTTPError as error:
                    self._last_request_at = time.monotonic()
                    if error.code == 304:
                        return {}, etag, True
                    if error.code == 404 and not_found_is_empty:
                        return {"releases": []}, "", False
                    error_body = _http_error_body(error)
                    if error.code in TRANSIENT_HTTP_STATUS:
                        LOGGER.debug("MusicBrainz transient HTTP %s response: %s", error.code, error_body)
                        if attempt < self._maximum_transient_retries:
                            delay = self._transient_retry_delay(attempt, error)
                            LOGGER.debug(
                                "MusicBrainz retry attempt %d/%d in %.2f seconds after HTTP %s",
                                attempt + 1,
                                self._maximum_transient_retries,
                                delay,
                                error.code,
                            )
                            if cancel_event.wait(delay):
                                raise MetadataLookupCancelled("metadata lookup was cancelled") from error
                            continue
                        attempts = self._maximum_transient_retries + 1
                        LOGGER.info(
                            "MusicBrainz temporarily unavailable after %d attempts (HTTP %s)",
                            attempts,
                            error.code,
                        )
                        raise MetadataTemporarilyUnavailable("Metadata service is temporarily unavailable.") from error
                    LOGGER.error("MusicBrainz HTTP %s response: %s", error.code, error_body)
                    retry_after = error.headers.get("Retry-After") if error.headers else None
                    suffix = f"; retry after {retry_after} seconds" if retry_after else ""
                    raise MetadataLookupError(f"MusicBrainz returned HTTP {error.code}{suffix}") from error
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    self._last_request_at = time.monotonic()
                    raise MetadataLookupError(f"MusicBrainz is unavailable: {error}") from error
        if len(raw) > MAX_RESPONSE_BYTES:
            raise MetadataLookupError("MusicBrainz returned an unexpectedly large response")
        if cancel_event.is_set():
            raise MetadataLookupCancelled("metadata lookup was cancelled")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MetadataLookupError("MusicBrainz returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise MetadataLookupError("MusicBrainz returned an unexpected response")
        return payload, response_etag, False

    def _wait_for_request_slot(self, cancel_event: threading.Event) -> None:
        delay = self._minimum_interval - (time.monotonic() - self._last_request_at)
        if delay > 0 and cancel_event.wait(delay):
            raise MetadataLookupCancelled("metadata lookup was cancelled")
        if cancel_event.is_set():
            raise MetadataLookupCancelled("metadata lookup was cancelled")

    def _transient_retry_delay(self, attempt: int, error: urllib.error.HTTPError) -> float:
        delay = self._retry_base_delay * (2**attempt) + random.uniform(0.0, self._retry_jitter)
        retry_after = error.headers.get("Retry-After") if error.headers else None
        try:
            server_delay = float(retry_after) if retry_after is not None else 0.0
        except ValueError:
            server_delay = 0.0
        return max(delay, server_delay)


def _payload_releases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    releases = payload.get("releases")
    if not isinstance(releases, list):
        return []
    return [release for release in releases if isinstance(release, dict)]


def _http_error_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read(MAX_ERROR_BODY_BYTES).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return "<unavailable>"


def _rank_disc_releases(releases: list[dict[str, Any]], disc_id: str, toc: DiscTOC) -> list[_DiscReleaseCandidate]:
    candidates: list[_DiscReleaseCandidate] = []
    for release in releases:
        release_id = str(release.get("id") or "")
        try:
            uuid.UUID(release_id)
        except (ValueError, AttributeError):
            continue
        media = release.get("media")
        if not isinstance(media, list):
            continue
        medium_candidates: list[tuple[tuple[Any, ...], dict[str, Any], tuple[bool, bool, bool]]] = []
        for medium in media:
            if not isinstance(medium, dict):
                continue
            exact, toc_match = _medium_disc_matches(medium, disc_id, toc)
            track_count = _as_int(medium.get("track-count"))
            count_match = track_count == len(toc.entries)
            position = _as_int(medium.get("position")) or 1
            medium_key = (not exact, not toc_match, not count_match, position)
            medium_candidates.append((medium_key, medium, (exact, toc_match, count_match)))
        if not medium_candidates:
            continue
        _, medium, (exact, toc_match, count_match) = min(medium_candidates, key=lambda item: item[0])
        status = str(release.get("status") or "")
        official = status.casefold() == "official"
        cover_info = release.get("cover-art-archive")
        front = bool(isinstance(cover_info, dict) and cover_info.get("front", False))
        disambiguation = bool(str(release.get("disambiguation") or "").strip())
        position = _as_int(medium.get("position")) or 1
        reasons = []
        if exact:
            reasons.append("exact disc ID")
        if toc_match:
            reasons.append("exact TOC")
        if count_match:
            reasons.append("matching track count")
        if position == 1:
            reasons.append("first medium")
        if official:
            reasons.append("official release")
        if not disambiguation:
            reasons.append("standard variant")
        candidates.append(
            _DiscReleaseCandidate(
                release=release,
                release_id=release_id,
                medium_position=position,
                exact_disc_match=exact,
                track_count_match=count_match,
                toc_match=toc_match,
                official=official,
                has_front_artwork=front,
                has_disambiguation=disambiguation,
                reason=", ".join(reasons) or "stable release ID ordering",
            )
        )
    candidates.sort(
        key=lambda candidate: (
            not candidate.exact_disc_match,
            not candidate.toc_match,
            not candidate.track_count_match,
            candidate.medium_position,
            not candidate.official,
            candidate.has_disambiguation,
            not candidate.has_front_artwork,
            str(candidate.release.get("date") or "9999-99-99"),
            str(candidate.release.get("country") or ""),
            candidate.release_id,
        )
    )
    return candidates


def _medium_disc_matches(medium: dict[str, Any], disc_id: str, toc: DiscTOC) -> tuple[bool, bool]:
    expected_offsets = [entry.offset_frame for entry in toc.entries]
    discs = medium.get("discs")
    if not isinstance(discs, list):
        return False, False
    exact = False
    toc_match = False
    for disc in discs:
        if not isinstance(disc, dict):
            continue
        exact = exact or disc.get("id") == disc_id
        offsets = disc.get("offsets")
        sectors = _as_int(disc.get("sectors"))
        toc_match = toc_match or (offsets == expected_offsets and sectors == toc.leadout_frame)
    return exact, toc_match


def _select_medium(release: dict[str, Any], disc_id: str, expected_count: int) -> tuple[dict[str, Any] | None, bool]:
    media = release.get("media")
    if not isinstance(media, list):
        return None, False
    fallback: dict[str, Any] | None = None
    for medium in media:
        if not isinstance(medium, dict):
            continue
        discs = medium.get("discs") or []
        exact = any(isinstance(disc, dict) and disc.get("id") == disc_id for disc in discs)
        if exact:
            return medium, True
        count = _as_int(medium.get("track-count")) or len(medium.get("tracks") or [])
        if fallback is None and (not expected_count or count == expected_count):
            fallback = medium
    return fallback, False


def _merge_tracks(medium: dict[str, Any], local_tracks: list[Track], album_artist: str) -> list[Track]:
    metadata_tracks = medium.get("tracks")
    if not isinstance(metadata_tracks, list):
        metadata_tracks = []
    merged: list[Track] = []
    for index, local in enumerate(local_tracks):
        metadata = metadata_tracks[index] if index < len(metadata_tracks) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        recording = metadata.get("recording")
        recording = recording if isinstance(recording, dict) else {}
        title = str(metadata.get("title") or recording.get("title") or local.title)
        artist = (
            _artist_credit(metadata.get("artist-credit"))
            or _artist_credit(recording.get("artist-credit"))
            or album_artist
            or local.artist
        )
        merged.append(
            Track(
                number=local.number,
                title=title,
                artist=artist,
                start_frame=local.start_frame,
                frame_count=local.frame_count,
                selected_for_ripping=local.selected_for_ripping,
                ripped=local.ripped,
            )
        )
    return merged


def _artist_credit(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        artist = item.get("artist")
        artist = artist if isinstance(artist, dict) else {}
        name = str(item.get("name") or artist.get("name") or "")
        if name:
            parts.append(name)
        join_phrase = str(item.get("joinphrase") or "")
        if join_phrase:
            parts.append(join_phrase)
    return "".join(parts).strip()


def _release_label(release: dict[str, Any]) -> str:
    label_info = release.get("label-info")
    if not isinstance(label_info, list):
        return ""
    for item in label_info:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if isinstance(label, dict) and label.get("name"):
            return str(label["name"])
    return ""


def _release_genre(release: dict[str, Any], release_group: dict[str, Any]) -> str:
    for container in (release_group, release):
        genres = container.get("genres")
        if isinstance(genres, list) and genres:
            ranked = sorted(
                (item for item in genres if isinstance(item, dict) and item.get("name")),
                key=lambda item: -_as_int(item.get("count")),
            )
            if ranked:
                return str(ranked[0]["name"]).title()
    return ""


def _candidate_sort_key(candidate: MetadataCandidate) -> tuple[Any, ...]:
    # Prefer the strongest match, then official/dated releases, then stable ID
    # ordering so cached and online results never shuffle unexpectedly.
    return (
        -candidate.score,
        candidate.album.year or "9999",
        candidate.country,
        candidate.release_id,
    )


def _is_confident(candidates: list[MetadataCandidate]) -> bool:
    if not candidates or not candidates[0].exact_disc_match or candidates[0].score < 140:
        return False
    if len(candidates) == 1:
        return True
    return candidates[0].score - candidates[1].score >= 8


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "MetadataCandidate",
    "MetadataLookup",
    "MetadataLookupCancelled",
    "MetadataLookupError",
    "MetadataTemporarilyUnavailable",
    "MetadataService",
    "build_musicbrainz_discid_url",
    "build_musicbrainz_release_url",
    "parse_musicbrainz_response",
]
