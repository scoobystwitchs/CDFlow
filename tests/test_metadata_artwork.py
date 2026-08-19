from __future__ import annotations

import threading
import urllib.error
import urllib.parse
from io import BytesIO
from types import SimpleNamespace

import pytest

from cdflow.app.application import ApplicationController
from cdflow.app.constants import network_user_agent
from cdflow.app.state import ApplicationState, AppStatus
from cdflow.models import Album, Track
from cdflow.services.artwork import ArtworkError, ArtworkService, _front_image_url, _image_extension
from cdflow.services.disc_reader import DiscTOC, TocEntry
from cdflow.services.library import LibraryRepository
from cdflow.services.metadata import (
    MetadataLookupError,
    MetadataService,
    MetadataTemporarilyUnavailable,
    build_musicbrainz_discid_url,
    build_musicbrainz_release_url,
    parse_musicbrainz_response,
)


class _JSONResponse:
    def __init__(self, payload: bytes = b'{"releases":[]}') -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}

    def __enter__(self) -> _JSONResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, maximum: int = -1) -> bytes:
        return self.payload if maximum < 0 else self.payload[:maximum]


class _RecordingCancelEvent:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def wait(self, delay: float) -> bool:
        self.waits.append(delay)
        return False

    def is_set(self) -> bool:
        return False


def _http_503() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://musicbrainz.org/ws/2/test",
        503,
        "Service Unavailable",
        {},
        BytesIO(b'{"error":"The MusicBrainz web server is currently busy. Please try again later."}'),
    )


def local_album() -> Album:
    return Album(
        disc_id="disc-id",
        tracks=[
            Track(1, "Track 01", start_frame=0, frame_count=7_500),
            Track(2, "Track 02", start_frame=7_500, frame_count=8_000),
        ],
    )


def release_payload(*, second_release: bool = False) -> dict:
    release = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "A Real Album",
        "date": "2004-05-06",
        "country": "GB",
        "status": "Official",
        "artist-credit": [{"name": "Alpha", "joinphrase": " & "}, {"name": "Beta"}],
        "cover-art-archive": {"front": True},
        "release-group": {
            "id": "22222222-2222-2222-2222-222222222222",
            "genres": [{"name": "alternative rock", "count": 8}],
        },
        "label-info": [{"label": {"name": "Small Label"}}],
        "media": [
            {
                "position": 1,
                "format": "CD",
                "track-count": 2,
                "discs": [{"id": "disc-id"}],
                "tracks": [
                    {"title": "First", "artist-credit": [{"name": "Singer"}]},
                    {"recording": {"title": "Second"}},
                ],
            }
        ],
    }
    releases = [release]
    if second_release:
        other = {**release, "id": "33333333-3333-3333-3333-333333333333"}
        releases.append(other)
    return {"releases": releases}


def test_musicbrainz_response_maps_and_ranks_an_exact_release() -> None:
    result = parse_musicbrainz_response(release_payload(), disc_id="disc-id", local_album=local_album())

    assert result.confident
    assert result.selected is not None
    assert result.selected.exact_disc_match
    album = result.selected.album
    assert (album.title, album.artist, album.year, album.genre, album.label) == (
        "A Real Album",
        "Alpha & Beta",
        "2004",
        "Alternative Rock",
        "Small Label",
    )
    assert [(track.title, track.artist) for track in album.tracks] == [
        ("First", "Singer"),
        ("Second", "Alpha & Beta"),
    ]
    assert album.tracks[0].frame_count == 7_500


def test_equally_plausible_releases_are_not_selected_silently() -> None:
    result = parse_musicbrainz_response(
        release_payload(second_release=True),
        disc_id="disc-id",
        local_album=local_album(),
    )

    assert len(result.candidates) == 2
    assert not result.confident
    assert result.selected is None


def test_malformed_or_empty_metadata_response_is_nonfatal() -> None:
    result = parse_musicbrainz_response({"releases": "wrong"}, disc_id="disc-id", local_album=local_album())
    assert result.candidates == ()
    assert result.selected is None


def test_front_artwork_prefers_approved_front_thumbnail() -> None:
    payload = {
        "images": [
            {"front": True, "approved": False, "image": "https://example.test/unapproved.jpg"},
            {
                "front": True,
                "approved": True,
                "thumbnails": {"500": "https://example.test/approved-500.jpg"},
            },
        ]
    }
    assert _front_image_url(payload) == "https://example.test/approved-500.jpg"
    assert _front_image_url({"images": []}) == ""


@pytest.mark.parametrize(
    ("data", "content_type", "extension"),
    [
        (b"\xff\xd8\xffanything", "image/jpeg", ".jpg"),
        (b"\x89PNG\r\n\x1a\nanything", "image/png", ".png"),
        (b"RIFFxxxxWEBPanything", "image/webp", ".webp"),
    ],
)
def test_artwork_type_is_verified_from_magic_bytes(data: bytes, content_type: str, extension: str) -> None:
    assert _image_extension(data, content_type) == extension


def test_artwork_rejects_an_unrecognized_payload() -> None:
    with pytest.raises(ArtworkError, match="unsupported artwork"):
        _image_extension(b"not-an-image", "text/plain")


def test_network_user_agent_requires_and_normalizes_contact() -> None:
    assert network_user_agent("  maintainer@example.test\n") == "CDFlow/0.1.0 (maintainer@example.test)"
    with pytest.raises(ValueError, match="contact"):
        network_user_agent("   ")
    with pytest.raises(ValueError, match="email address"):
        network_user_agent("not-contact-information")


def test_online_services_refuse_anonymous_requests() -> None:
    metadata = MetadataService(minimum_request_interval=1)
    artwork = ArtworkService(minimum_request_interval=1)
    toc = DiscTOC((TocEntry(1, 150),), 10_000)
    try:
        with pytest.raises(MetadataLookupError, match="contact email or URL"):
            metadata._fetch(toc.disc_id, toc, threading.Event(), "")
        with pytest.raises(ArtworkError, match="contact email or URL"):
            artwork._download("https://example.test/image", 1024, threading.Event(), accept="image/*")
    finally:
        metadata.shutdown()
        artwork.shutdown()


def test_musicbrainz_disc_lookup_url_matches_v2_specification() -> None:
    disc_id = "I5l9cCSFccLKFEKS.7wqSZAorPU-"
    offsets = (150, 22_767, 41_887, 58_317, 72_102, 91_375, 104_652, 115_380, 132_165, 143_932, 159_870, 174_597)
    toc = DiscTOC(tuple(TocEntry(number, offset) for number, offset in enumerate(offsets, 1)), 267_257)

    url = build_musicbrainz_discid_url(disc_id, toc)
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)

    assert parsed.path == f"/ws/2/discid/{disc_id}"
    assert query == {
        "toc": ["1+12+267257+150+22767+41887+58317+72102+91375+104652+115380+132165+143932+159870+174597"],
        "cdstubs": ["no"],
        "fmt": ["json"],
    }
    assert "%2B" in parsed.query


def test_musicbrainz_disc_lookup_never_sends_inc() -> None:
    toc = DiscTOC((TocEntry(1, 150),), 10_000)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(build_musicbrainz_discid_url(toc.disc_id, toc)).query)

    assert "inc" not in query


def test_musicbrainz_release_lookup_uses_only_release_level_includes() -> None:
    release_id = "7b1a2b36-84e6-4c95-91bf-216e89f56720"
    parsed = urllib.parse.urlsplit(build_musicbrainz_release_url(release_id))
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)

    assert parsed.path == f"/ws/2/release/{release_id}"
    assert query == {
        "inc": ["artist-credits+labels+recordings+release-groups+media+discids"],
        "fmt": ["json"],
    }


def test_realistic_discid_response_maps_release_and_all_tracks() -> None:
    disc_id = "3wW8FXSMsGsOtGbBdQys7IlU.bE-"
    offsets = (
        150,
        17_065,
        32_723,
        49_449,
        67_348,
        85_910,
        99_464,
        117_472,
        139_739,
        155_941,
        172_809,
        187_347,
        203_994,
    )
    leadout = 229_568
    toc = DiscTOC(tuple(TocEntry(number, offset) for number, offset in enumerate(offsets, 1)), leadout)
    local_tracks = [
        Track(
            number,
            f"Track {number:02d}",
            start_frame=offset - 150,
            frame_count=(offsets[number] if number < len(offsets) else leadout) - offset,
        )
        for number, offset in enumerate(offsets, 1)
    ]
    payload = {
        "id": disc_id,
        "releases": [
            {
                "id": "7b1a2b36-84e6-4c95-91bf-216e89f56720",
                "title": "Night Signals",
                "status": "Official",
                "date": "2017-09-22",
                "country": "GB",
                "artist-credit": [
                    {
                        "name": "The Example Ensemble",
                        "artist": {
                            "id": "fe93a620-1d1f-43b5-b7de-45a5a9082ed1",
                            "name": "The Example Ensemble",
                        },
                    }
                ],
                "release-group": {
                    "id": "ae0ad86c-1667-464f-8a6a-f5626ddf4a32",
                    "primary-type": "Album",
                },
                "label-info": [{"label": {"name": "Example Records"}}],
                "media": [
                    {
                        "position": 1,
                        "format": "CD",
                        "track-count": 13,
                        "discs": [{"id": disc_id, "sectors": leadout - 150}],
                        "tracks": [
                            {
                                "id": f"00000000-0000-0000-0000-{number:012d}",
                                "number": str(number),
                                "position": number,
                                "title": f"Movement {number}",
                                "recording": {
                                    "id": f"10000000-0000-0000-0000-{number:012d}",
                                    "title": f"Movement {number}",
                                    "artist-credit": [
                                        {"name": "Guest Vocalist" if number == 2 else "The Example Ensemble"}
                                    ],
                                },
                            }
                            for number in range(1, 14)
                        ],
                    }
                ],
            }
        ],
    }

    result = parse_musicbrainz_response(
        payload,
        disc_id=disc_id,
        local_album=Album(disc_id=disc_id, tracks=local_tracks),
        toc=toc,
    )

    assert result.confident
    assert result.selected is not None
    assert result.selected.release_group_id == "ae0ad86c-1667-464f-8a6a-f5626ddf4a32"
    album = result.selected.album
    assert (album.title, album.artist, album.year, album.label) == (
        "Night Signals",
        "The Example Ensemble",
        "2017",
        "Example Records",
    )
    assert len(album.tracks) == 13
    assert album.tracks[0].title == "Movement 1"
    assert album.tracks[1].artist == "Guest Vocalist"
    assert album.tracks[-1].frame_count == leadout - offsets[-1]


def _discovery_release(
    release_id: str,
    disc_id: str,
    toc: DiscTOC,
    *,
    status: str = "Official",
    disambiguation: str = "",
    front_artwork: bool = False,
) -> dict:
    return {
        "id": release_id,
        "title": "A Real Album",
        "status": status,
        "date": "2004-05-06",
        "country": "GB",
        "disambiguation": disambiguation,
        "cover-art-archive": {"front": front_artwork},
        "media": [
            {
                "position": 1,
                "format": "CD",
                "track-count": len(toc.entries),
                "discs": [
                    {
                        "id": disc_id,
                        "offsets": [entry.offset_frame for entry in toc.entries],
                        "offset-count": len(toc.entries),
                        "sectors": toc.leadout_frame,
                    }
                ],
            }
        ],
    }


def _release_detail(release_id: str, disc_id: str) -> dict:
    detail = release_payload()["releases"][0]
    detail["id"] = release_id
    detail["media"][0]["discs"] = [{"id": disc_id}]
    return detail


def test_staged_lookup_identifies_one_release_then_fetches_its_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toc = DiscTOC((TocEntry(1, 150), TocEntry(2, 14_025)), 27_000)
    disc_id = toc.disc_id
    release_id = "7b1a2b36-84e6-4c95-91bf-216e89f56720"
    service = MetadataService(contact="maintainer@example.test")
    requested_urls: list[str] = []

    def request(url: str, *args: object, **kwargs: object) -> tuple[dict, str, bool]:
        requested_urls.append(url)
        if "/discid/" in url:
            return {"releases": [_discovery_release(release_id, disc_id, toc)]}, "", False
        return _release_detail(release_id, disc_id), '"release-etag"', False

    monkeypatch.setattr(service, "_request_json", request)
    try:
        result = service.lookup(disc_id, toc, local_album())
    finally:
        service.shutdown()

    assert result.selected is not None
    assert result.selected.release_id == release_id
    assert result.selected.album.title == "A Real Album"
    assert len(requested_urls) == 2
    assert f"/discid/{disc_id}" in requested_urls[0]
    assert f"/release/{release_id}" in requested_urls[1]
    assert "inc=" not in requested_urls[0]
    assert "inc=artist-credits%2Blabels%2Brecordings%2Brelease-groups%2Bmedia%2Bdiscids" in requested_urls[1]


def test_staged_lookup_deterministically_selects_best_of_multiple_releases(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    toc = DiscTOC((TocEntry(1, 150), TocEntry(2, 14_025)), 27_000)
    disc_id = toc.disc_id
    signed_id = "11111111-1111-4111-8111-111111111111"
    standard_id = "22222222-2222-4222-8222-222222222222"
    bootleg_id = "33333333-3333-4333-8333-333333333333"
    discovery = {
        "releases": [
            _discovery_release(signed_id, disc_id, toc, disambiguation="signed"),
            _discovery_release(bootleg_id, disc_id, toc, status="Bootleg", front_artwork=True),
            _discovery_release(standard_id, disc_id, toc),
        ]
    }
    service = MetadataService(contact="maintainer@example.test")

    def request(url: str, *args: object, **kwargs: object) -> tuple[dict, str, bool]:
        if "/discid/" in url:
            return discovery, "", False
        assert f"/release/{standard_id}" in url
        return _release_detail(standard_id, disc_id), "", False

    monkeypatch.setattr(service, "_request_json", request)
    try:
        with caplog.at_level("DEBUG", logger="cdflow.services.metadata"):
            result = service.lookup(disc_id, toc, local_album())
    finally:
        service.shutdown()

    assert result.selected is not None
    assert result.selected.release_id == standard_id
    assert "MusicBrainz candidates:" in caplog.text
    assert f"Selected MusicBrainz release {standard_id}" in caplog.text
    assert "standard variant" in caplog.text


def test_staged_lookup_uses_fuzzy_toc_when_exact_disc_is_not_found(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    toc = DiscTOC((TocEntry(1, 150), TocEntry(2, 14_025)), 27_000)
    disc_id = toc.disc_id
    nearby_disc_id = "I5l9cCSFccLKFEKS.7wqSZAorPU-"
    release_id = "44444444-4444-4444-8444-444444444444"
    requested_urls: list[str] = []
    service = MetadataService(contact="maintainer@example.test")

    def request(url: str, *args: object, **kwargs: object) -> tuple[dict, str, bool]:
        requested_urls.append(url)
        if f"/discid/{disc_id}" in url:
            return {"releases": []}, "", False
        if "/discid/-" in url:
            release = _discovery_release(release_id, nearby_disc_id, toc)
            release["media"][0]["discs"][0]["offsets"][1] += 3
            return {"releases": [release]}, "", False
        return _release_detail(release_id, nearby_disc_id), "", False

    monkeypatch.setattr(service, "_request_json", request)
    try:
        with caplog.at_level("DEBUG", logger="cdflow.services.metadata"):
            result = service.lookup(disc_id, toc, local_album())
    finally:
        service.shutdown()

    assert result.selected is not None
    assert result.selected.release_id == release_id
    assert len(requested_urls) == 3
    assert "/discid/-?" in requested_urls[1]
    assert "using fuzzy TOC fallback" in caplog.text


def test_artwork_failure_does_not_discard_successful_album_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = parse_musicbrainz_response(release_payload(), disc_id="disc-id", local_album=local_album())
    assert lookup.selected is not None
    album = lookup.selected.album
    artwork = ArtworkService(contact="maintainer@example.test")

    def fail_artwork(*args: object, **kwargs: object) -> None:
        raise ArtworkError("Cover Art Archive is unavailable")

    monkeypatch.setattr(artwork, "_download", fail_artwork)
    try:
        with pytest.raises(ArtworkError, match="unavailable"):
            artwork.fetch("11111111-1111-1111-1111-111111111111")
    finally:
        artwork.shutdown()

    assert album.title == "A Real Album"
    assert [track.title for track in album.tracks] == ["First", "Second"]


@pytest.mark.parametrize("disc_id", ["", "disc-id", "contains/slash-and-is-too-long"])
def test_musicbrainz_disc_lookup_rejects_invalid_disc_ids(disc_id: str) -> None:
    toc = DiscTOC((TocEntry(1, 150),), 10_000)

    with pytest.raises(ValueError, match="invalid MusicBrainz disc ID"):
        build_musicbrainz_discid_url(disc_id, toc)


def test_musicbrainz_http_error_body_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = MetadataService(contact="maintainer@example.test", minimum_request_interval=1)
    toc = DiscTOC((TocEntry(1, 150),), 10_000)
    disc_id = toc.disc_id

    def fail_request(*args: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "https://musicbrainz.org/test",
            400,
            "Bad Request",
            {},
            BytesIO(b'{"error":"Invalid inc parameter"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail_request)
    try:
        with (
            caplog.at_level("DEBUG", logger="cdflow.services.metadata"),
            pytest.raises(MetadataLookupError, match="HTTP 400"),
        ):
            service._fetch(disc_id, toc, threading.Event(), "")
        assert "fmt=json" in caplog.text
        assert 'HTTP 400 response: {"error":"Invalid inc parameter"}' in caplog.text
        assert "maintainer@example.test" not in caplog.text
    finally:
        service.shutdown()


def test_musicbrainz_503_then_success_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MetadataService(
        contact="maintainer@example.test",
        retry_base_delay=0,
        retry_jitter=0,
    )
    calls = 0

    def request(*args: object, **kwargs: object) -> _JSONResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_503()
        return _JSONResponse()

    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr(service, "_wait_for_request_slot", lambda event: None)
    try:
        payload, _etag, _not_modified = service._request_json(
            "https://musicbrainz.org/ws/2/test?fmt=json",
            threading.Event(),
            request_description="test lookup",
        )
    finally:
        service.shutdown()

    assert payload == {"releases": []}
    assert calls == 2


def test_musicbrainz_consecutive_503s_use_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MetadataService(
        contact="maintainer@example.test",
        retry_base_delay=1,
        retry_jitter=0,
    )
    event = _RecordingCancelEvent()
    calls = 0

    def request(*args: object, **kwargs: object) -> _JSONResponse:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise _http_503()
        return _JSONResponse()

    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr(service, "_wait_for_request_slot", lambda ignored: None)
    try:
        service._request_json(
            "https://musicbrainz.org/ws/2/test?fmt=json",
            event,  # type: ignore[arg-type]
            request_description="test lookup",
        )
    finally:
        service.shutdown()

    assert calls == 3
    assert event.waits == [1.0, 2.0]


def test_musicbrainz_retry_limit_reports_temporary_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = MetadataService(
        contact="maintainer@example.test",
        maximum_transient_retries=3,
        retry_base_delay=0,
        retry_jitter=0,
    )
    calls = 0

    def request(*args: object, **kwargs: object) -> _JSONResponse:
        nonlocal calls
        calls += 1
        raise _http_503()

    monkeypatch.setattr("urllib.request.urlopen", request)
    monkeypatch.setattr(service, "_wait_for_request_slot", lambda event: None)
    try:
        with (
            caplog.at_level("DEBUG", logger="cdflow.services.metadata"),
            pytest.raises(MetadataTemporarilyUnavailable, match="temporarily unavailable"),
        ):
            service._request_json(
                "https://musicbrainz.org/ws/2/test?fmt=json",
                threading.Event(),
                request_description="test lookup",
            )
    finally:
        service.shutdown()

    assert calls == 4
    assert "retry attempt 3/3" in caplog.text
    assert "temporarily unavailable after 4 attempts" in caplog.text
    assert "maintainer@example.test" not in caplog.text


def test_musicbrainz_request_limiter_enforces_minimum_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MetadataService(contact="maintainer@example.test", minimum_request_interval=1.0)
    event = _RecordingCancelEvent()
    clock = iter((100.0, 100.1, 100.3, 101.2))

    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _JSONResponse())
    try:
        for _ in range(2):
            service._request_json(
                "https://musicbrainz.org/ws/2/test?fmt=json",
                event,  # type: ignore[arg-type]
                request_description="test lookup",
            )
    finally:
        service.shutdown()

    assert event.waits == [pytest.approx(0.8)]


def test_metadata_cache_hit_avoids_network_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    library = LibraryRepository(":memory:")
    library.put_metadata_cache("disc-id", release_payload())
    service = MetadataService(library, contact="maintainer@example.test")
    monkeypatch.setattr(service, "_fetch", lambda *args, **kwargs: pytest.fail("network should not be called"))
    try:
        result = service.lookup(
            "disc-id",
            DiscTOC((TocEntry(1, 150), TocEntry(2, 14_025)), 27_000),
            local_album(),
        )
    finally:
        service.shutdown()
        library.close()

    assert result.from_cache
    assert result.selected is not None


def test_duplicate_async_metadata_lookups_are_coalesced(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MetadataService(contact="maintainer@example.test")
    toc = DiscTOC((TocEntry(1, 150), TocEntry(2, 14_025)), 27_000)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def lookup(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(2)
        return parse_musicbrainz_response(release_payload(), disc_id="disc-id", local_album=local_album())

    monkeypatch.setattr(service, "lookup", lookup)
    try:
        assert service.lookup_async("disc-id", toc, local_album(), generation=1)
        assert started.wait(1)
        assert not service.lookup_async("disc-id", toc, local_album(), generation=2)
        release.set()
    finally:
        release.set()
        service.shutdown(wait=True)

    assert calls == 1


def test_temporary_metadata_failure_does_not_change_ripping_or_playback_state() -> None:
    state = ApplicationState()
    state.transition(AppStatus.LOADING_DISC)
    state.transition(AppStatus.AUDIO_CD)
    state.transition(AppStatus.RIPPING)
    messages: list[tuple[str, str, int]] = []
    controller = SimpleNamespace(
        _active_metadata_request=(7, "disc-id", False),
        _shutting_down=False,
        state=state,
        player=SimpleNamespace(state="playing"),
        window=SimpleNamespace(
            show_message=lambda message, level, timeout_ms: messages.append((message, level, timeout_ms))
        ),
    )

    ApplicationController._on_metadata_failed(  # type: ignore[arg-type]
        controller, "Metadata service is temporarily unavailable.", 7
    )

    assert state.snapshot.status == AppStatus.RIPPING
    assert controller.player.state == "playing"
    assert messages == [("Metadata service is temporarily unavailable.", "warning", 6000)]
