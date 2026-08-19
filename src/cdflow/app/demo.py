"""Deterministic demo media used for UI development without optical hardware."""

from __future__ import annotations

from cdflow.models import Album, Disc, DiscKind, Drive, Track

_TRACKS = (
    ("Papercut", 185),
    ("One Step Closer", 157),
    ("With You", 203),
    ("Points of Authority", 200),
    ("Crawling", 209),
    ("Runaway", 184),
    ("By Myself", 190),
    ("In the End", 216),
    ("A Place for My Head", 185),
    ("Forgotten", 194),
    ("Cure for the Itch", 157),
    ("Pushing Me Away", 191),
)


def demo_audio_disc() -> Disc:
    start = 0
    tracks: list[Track] = []
    for number, (title, seconds) in enumerate(_TRACKS, start=1):
        frames = seconds * 75
        tracks.append(
            Track(
                number=number,
                title=title,
                artist="Linkin Park",
                start_frame=start,
                frame_count=frames,
            )
        )
        start += frames
    drive = Drive(
        object_path="/org/freedesktop/UDisks2/drives/CDFlow_Demo",
        block_path="/org/freedesktop/UDisks2/block_devices/sr0",
        device="/dev/sr0",
        vendor="HL-DT-ST",
        model="DVDRAM GH24NSD1",
        connection_bus="sata",
        media_available=True,
        media_name="optical_cd",
        audio_tracks=len(tracks),
    )
    album = Album(
        disc_id="demo-hybrid-theory",
        title="Hybrid Theory",
        artist="Linkin Park",
        year="2000",
        genre="Rock",
        label="Warner Bros.",
        tracks=tracks,
    )
    return Disc(kind=DiscKind.AUDIO, drive=drive, disc_id=album.disc_id, album=album)


def demo_data_disc() -> Disc:
    drive = Drive(
        object_path="/org/freedesktop/UDisks2/drives/CDFlow_Demo",
        block_path="/org/freedesktop/UDisks2/block_devices/sr0",
        device="/dev/sr0",
        vendor="HL-DT-ST",
        model="DVDRAM GH24NSD1",
        connection_bus="sata",
        media_available=True,
        media_name="optical_cd",
        data_tracks=1,
    )
    return Disc(
        kind=DiscKind.DATA,
        drive=drive,
        disc_id="demo-data-disc",
        label="CDFlow Demo",
        filesystem_type="iso9660",
        mount_points=("/tmp",),
        capacity=734_003_200,
    )
