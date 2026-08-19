Generated image: CDFlow Hybrid Theory Player

Generated image: Neon Pink Hybrid Theory Music Player

Generated image: CDFLOW Dark UI Design Specification

For Codex, I’d have it reason about architecture and failure cases, but not over-engineer it. The key areas are Linux optical-drive events, audio-CD handling, non-blocking ripping/playback, Qt state management, and keeping dependencies/resources minimal.

You are building a complete, lightweight Linux desktop application for personal use called CDFlow.

The application is a modern CD player, CD ripper, disc information viewer, and simple data-CD browser. It must run locally with no account system, no backend, no cloud infrastructure, and no required server.

The primary target system is:

    Fedora Linux

    KDE Plasma

    Wayland

    x86_64

    Modern Linux optical CD/DVD drive

The application should ultimately be distributable as a standalone Linux application, preferably an AppImage, while also being easy to run from source during development.
Primary Goal

Build a polished desktop application that automatically detects optical drives and reacts when a CD is inserted or removed.

When no disc is inserted, the application should sit essentially idle and consume as few resources as practical.

When an audio CD is inserted, CDFlow should:

    detect it automatically

    identify the optical drive

    read the CD table of contents

    determine track count

    determine track lengths

    calculate total album duration

    display the tracks

    allow playback

    allow seeking where technically reliable

    provide volume controls

    allow the user to rip selected tracks

    allow ripping of the full CD

    eject the disc

    display disc information

    optionally retrieve metadata and artwork

    cache metadata locally

When a data CD is inserted, CDFlow should:

    detect it

    identify it as a data disc rather than audio CD

    show its mounted filesystem

    provide a lightweight read-only file browser

    allow files/folders to be opened using the system

    show disc capacity and filesystem information where possible

    allow ejecting the disc

The application must remain useful when completely offline.
Technology

Prefer:

    Python 3.12+

    PySide6 / Qt 6

    Linux UDisks2 over D-Bus for optical-drive discovery and media insertion/removal events

    Qt Multimedia, GStreamer, libcdio, or another appropriate Linux-native method for playback

    cdparanoia, libcdio, or another reliable Linux CDDA solution for digital audio extraction

    FFmpeg only where useful for encoding/conversion

    MusicBrainz for optional album metadata

    Cover Art Archive for optional artwork

Do NOT use:

    Electron

    Chromium/WebView based UI

    a local HTTP server

    React

    Node.js unless absolutely unavoidable

    Docker

    databases requiring a running service

    polling loops that repeatedly hammer /dev/sr0

The goal is low CPU usage, low memory use, instant launch, and near-zero idle overhead.
Architecture

Use a clean modular structure approximately like:

cdflow/
├── main.py
├── app/
│   ├── application.py
│   ├── state.py
│   └── constants.py
├── ui/
│   ├── main_window.py
│   ├── widgets/
│   ├── pages/
│   │   ├── now_playing.py
│   │   ├── tracks.py
│   │   ├── rip_cd.py
│   │   ├── browse_files.py
│   │   ├── disc_info.py
│   │   ├── collection.py
│   │   └── settings.py
│   └── styles/
├── services/
│   ├── drive_monitor.py
│   ├── disc_reader.py
│   ├── audio_player.py
│   ├── ripper.py
│   ├── metadata.py
│   ├── artwork.py
│   └── library.py
├── models/
│   ├── disc.py
│   ├── track.py
│   └── album.py
├── assets/
└── packaging/

Do not blindly follow that structure if a better separation becomes obvious, but keep UI, Linux hardware integration, playback, ripping, and metadata independent.
Optical Drive Detection

This is one of the most important parts of the application.

Use UDisks2 / D-Bus notifications rather than continuously polling drives.

The app should:

    enumerate existing optical drives when starting

    subscribe to UDisks2 object/interface changes

    detect media insertion

    detect media removal

    detect tray eject

    handle drives being connected/disconnected while CDFlow is running

    identify /dev/sr* or the actual backing device

    update the GUI immediately

    safely cancel playback/ripping if the media disappears

Correctly distinguish where possible between:

    no media

    audio CD / CDDA

    data CD

    mixed-mode CD

    unsupported optical media

Do not assume the drive is always /dev/sr0.
Application State

Use a central application state model.

Possible states:

NO_DRIVE
EMPTY_DRIVE
LOADING_DISC
AUDIO_CD
DATA_CD
RIPPING
EJECTING
ERROR

The GUI should react to state changes instead of individual widgets independently querying the hardware.

Avoid race conditions if a disc is inserted/ejected quickly.
Audio CD

Read the CD TOC and create track objects.

Each track should contain at least:

track_number
title
artist
start_sector/frame
duration
selected_for_ripping

Metadata titles may initially be:

Track 01
Track 02
Track 03

until metadata is available.

CD playback should work without first ripping the entire disc.

If direct CDDA playback through the chosen multimedia stack is unreliable, implement a sensible Linux-native alternative while keeping latency low.

The user should be able to:

    play

    pause

    stop

    next track

    previous track

    click a track to play it

    change volume

    mute

    see elapsed time

    see track duration

    use a progress control if seeking is supported reliably

Playback processing must never block the GUI thread.
CD Ripping

Create a proper ripping worker.

Ripping must run away from the UI thread.

The Rip CD page should allow:

    selecting/deselecting individual tracks

    Select All

    output folder

    output format

    compression/quality where applicable

    filename pattern

    metadata embedding

    artwork embedding where supported

    start ripping

    cancel ripping

Initial supported formats:

    FLAC

    WAV

    MP3

Prefer accurate extraction over maximum ripping speed.

Show:

    current track

    individual track progress

    overall progress

    elapsed time

    destination

    completion/error state

Suggested default destination:

~/Music/CDFlow/

Suggested organization:

Artist/
    Album/
        01 - Track Name.flac

Sanitize filenames safely.

Never overwrite an existing file silently.
Metadata

Metadata fetching is optional and must never be required for the application to function.

When internet access is available:

    calculate an appropriate disc identifier

    query MusicBrainz

    handle zero, one, or multiple possible releases

    use the most sensible match automatically when confidence is strong

    retrieve album/artist/year/track names

    retrieve Cover Art Archive artwork when available

    cache the result locally

When offline or lookup fails:

    show generic track names

    continue functioning normally

    never present a blocking error dialog just because metadata failed

Respect public API rate limits.

Do not repeatedly request metadata that is already cached.
Local Collection

Since this is a personal app, keep the collection simple.

Remember CDs that have previously been recognized.

Store locally:

    disc ID

    album title

    artist

    year

    artwork cache path

    track information

    last inserted date

    ripped/not-ripped state where useful

SQLite is acceptable because it is embedded and requires no server.

A small JSON-based cache is also acceptable if it keeps implementation simpler.

Choose whichever is more robust without meaningfully increasing resource usage.
GUI

Use the provided visual references as the design source.

The application should look like a polished modern music application rather than a default Qt utility.

Primary visual language:

    near-black background

    slightly lighter cards/panels

    thin subtle borders

    modest rounded corners

    restrained shadows

    bright pink/magenta accent

    white primary text

    muted grey secondary text

    clean modern icons

    compact but comfortable spacing

Approximate accent:

#F43F86

Do not hardcode that everywhere. Use centralized theme variables.

The GUI should retain KDE/Linux window behaviour and should not imitate Windows window chrome.

Avoid excessive transparency and blur because lightweight performance matters more.
Sidebar

Pages:

    Now Playing

    Tracks

    Rip CD

    Browse Files

    Disc Info

    Collection

    Settings

Under navigation show detected optical drive(s).

At the bottom show drive/disc status.

Provide an Eject button when appropriate.
Now Playing Page

Use the supplied main reference closely.

Top section:

    large album/disc artwork

    album title

    artist

    track count

    total duration

    media-type badge

    Rip CD action

    Disc Info area

Middle:

    complete track list

    playing track highlighted using pink accent

    track number

    title

    duration

Bottom persistent playback bar:

    small artwork

    track title

    artist

    shuffle if implemented

    previous

    play/pause

    next

    repeat if implemented

    progress

    current time

    duration

    volume

Do not duplicate a playlist panel unless it genuinely adds useful functionality; prioritize a clean layout over copying unnecessary visual elements from the concept exactly.
Tracks Page

Dedicated table view for all tracks.

Include:

    track number

    title

    artist

    duration

    optional rip status

Search/filter is optional but acceptable.

Double-clicking a track should play it.

Right-click menu may contain:

    Play

    Rip this track

    Show track information

Rip CD Page

Use a two-column design.

Left:

    format

    quality

    destination

    filename pattern

    metadata/artwork options

    Rip button

Right:

    checkable track list

When ripping begins, transition cleanly into a progress view rather than creating another window.
Browse Files Page

Only useful for data CDs.

Use a native-style file browser with:

    breadcrumb/current path

    folders/files

    name

    type

    size

    modified date where available

Treat the optical disc as read-only.

Opening a file should delegate to the user's default Linux application when appropriate.

Do not implement file editing.
Disc Info Page

Show:

    media type

    label

    artist

    album

    year

    genre

    track count

    total duration

    drive model

    device path

    disc identifier

    mount point for data media

    filesystem type

    capacity where available

Hide fields that do not apply instead of displaying meaningless blanks everywhere.
Collection Page

Show previously recognized albums as a simple artwork grid.

Each card:

    artwork

    album

    artist

Selecting one opens its locally cached information.

Do not make this into a full music-library manager.

The purpose is simply to remember the user's physical CD collection.
Settings

Keep settings minimal.

Sections:
Appearance

    dark theme

    accent color

Default accent is pink.

Optionally allow several accent presets, but do not spend excessive engineering effort on full theming.
Metadata

    enable metadata fetching

    metadata provider

    enable artwork fetching

Ripping

    default format

    default quality

    default destination

    filename pattern

Playback

    default volume

    remember volume

Behaviour

    remember window geometry

    automatically load inserted discs

    optionally begin metadata lookup automatically

Settings must be saved locally.
No Disc State

When no disc is present:

Display a very simple centered empty state:

No Disc Inserted

Insert an Audio CD or Data CD
to get started.

Include a thin pink optical-disc icon.

The application should consume essentially no CPU in this state beyond normal Qt event handling.
Performance Requirements

Treat performance as a feature.

Do not:

    continuously redraw animations

    run aggressive timers

    poll D-Bus constantly

    decode artwork repeatedly

    execute blocking subprocess calls on the UI thread

    create unnecessary worker threads

    load all application pages repeatedly

    ship a browser engine

Targets are not strict benchmarks, but optimize toward:

    very low idle CPU

    low memory footprint

    responsive startup

    instant page switching

    no UI freezes while reading/ripping discs

Use Qt signals/slots cleanly.

Long operations should use appropriate worker objects, QThread, QThreadPool, or asynchronous process handling.
Error Handling

Handle gracefully:

    no optical drive

    drive disappears

    disc removed while playing

    disc removed while ripping

    unreadable disc

    scratched disc

    permission failure

    UDisks2 unavailable

    command/tool unavailable

    metadata lookup failure

    artwork lookup failure

    unsupported disc

    output folder unwritable

    insufficient disk space

    encoder unavailable

Use non-intrusive messages inside the UI where possible.

Do not spam modal dialogs.
Logging

Use Python logging.

Support:

cdflow --debug

Normal operation should not flood stdout.

Debug logs should make hardware and ripping problems diagnosable.

Do not log personal filesystem information unnecessarily.
Dependency Handling

At startup, detect optional external dependencies.

Clearly distinguish:

    required dependency missing

    optional feature unavailable

For example, if MP3 encoding requires an installed encoder but FLAC works, do not prevent CDFlow from launching.

Where practical use Python/native libraries rather than shelling out.

Where established Linux tools are substantially more reliable, using subprocesses is acceptable.
Fedora Development Environment

Provide development setup instructions suitable for Fedora KDE.

Include required dnf and Python package commands.

Be aware that system package names may differ from Debian/Ubuntu.

Do not assume apt.
Packaging

Create packaging support after the application works from source.

Preferred target:

AppImage

The end result should ideally allow:

chmod +x CDFlow-x86_64.AppImage
./CDFlow-x86_64.AppImage

Avoid requiring the user to manually install Python dependencies after packaging.

If AppImage packaging presents genuine issues with optical-drive/system integration, document them and use the closest sensible standalone Linux packaging approach.

Do not compromise access to UDisks2, /dev/sr*, or multimedia devices merely to force a packaging method.
Development Process

Work incrementally, but continue through the entire application rather than stopping after scaffolding.

Recommended implementation order:

    project structure

    Qt application shell and theme

    central app/disc state

    UDisks2 optical-drive detection

    insert/eject detection

    audio/data-disc distinction

    audio CD TOC reading

    track-model UI

    playback

    Rip CD functionality

    data-CD browser

    metadata

    artwork

    collection/cache

    settings

    error handling

    packaging

    tests and cleanup

At each stage, run the app and fix integration problems before moving on.

Do not leave core functions as pseudocode or placeholder buttons.
Engineering Reasoning Required

Before implementing a subsystem, reason about its externally observable behaviour and edge cases.

In particular, determine:

    the most reliable UDisks2 interfaces/properties for identifying optical drives and media

    how Fedora exposes audio CDs versus mounted data CDs

    whether an audio CD gets mounted at all

    the safest way to read a CD TOC without requiring root

    the best playback mechanism available under modern Fedora

    how to ensure CD reads do not block Qt's event loop

    how to cancel an in-progress rip safely

    what happens if the disc is ejected during an operation

    how to avoid multiple metadata requests from duplicate insertion events

    how to represent disc identity consistently for cache lookup

    how to handle multiple optical drives

    what external tools are present on a clean Fedora installation versus what needs explicit installation

    how AppImage affects access to system D-Bus, optical devices, GStreamer plugins, and external commands

Do not over-engineer hypothetical problems. Prefer well-supported Linux mechanisms and simple robust code.

When uncertain about a library/API, inspect its current documentation or installed interfaces rather than inventing an API.
Testing

Implement tests where practical, particularly for code that does not require physical hardware.

Test:

    state transitions

    track duration calculations

    metadata parsing

    filename sanitization

    filename patterns

    cache/database operations

    settings persistence

    rip-job state

    missing dependencies

    removal events

Abstract the optical-drive interface enough that simulated drive/disc events can be tested without requiring a real CD for every test.

Also provide a manual hardware-test checklist for:

    inserting audio CD

    ejecting audio CD

    inserting data CD

    playback

    switching tracks

    ripping one track

    ripping entire disc

    cancelling a rip

    ejecting while playing

    ejecting while ripping

    closing and reopening the application

    offline operation

Code Quality

Use:

    type hints

    small focused classes

    descriptive names

    docstrings where behaviour is non-obvious

    centralized constants

    clean Qt signal/slot connections

Avoid:

    gigantic main.py

    global mutable state

    duplicated styles

    hardcoded filesystem paths

    busy waiting

    unnecessary abstractions

    broad except Exception: pass

    generated-looking placeholder comments everywhere

Make the repository understandable by a human.
Deliverables

The completed repository should contain:

README.md
LICENSE
requirements.txt or pyproject.toml
source code
assets
tests
Fedora setup instructions
run/build scripts
AppImage packaging configuration

Provide:

./run.sh

or an equally simple development launch command.

Provide a build command that produces the distributable artifact.

Use an MIT license unless there is a dependency/licensing reason requiring something different.
UI Reference Priority

Treat the supplied reference images as design direction, not screenshots that must be reproduced pixel-for-pixel.

Preserve:

    dark aesthetic

    pink accent

    compact polished sidebar

    large album/disc identity area

    clean track lists

    persistent playback controls

    rounded dark panels

    subtle borders

    consistent spacing

Improve anything that causes unnecessary duplication or harms usability.

The finished application should look intentionally designed, not like default Qt widgets with a stylesheet pasted on top.
Final Standard

Do not stop at a visual mockup.

The final result must be a functioning Linux application with real optical-drive detection and real CD behaviour.

Prioritize, in this order:

    reliability

    lightweight resource use

    correct Linux/Fedora integration

    responsive UI

    visual polish

    optional metadata conveniences

For the agent’s “reasoning”, that Engineering Reasoning Required section is what I’d use. It gives Codex the decisions it actually needs to investigate without asking it to produce pages of internal reasoning.

I’d also feed Codex the pink Now Playing image you approved plus the reference board. I’m adding separate tab references now so it can match spacing, hierarchy, controls and states rather than guessing from text alone.

Pasted text.txt
Document

That 9-byte download means GitHub returned a tiny “Not Found” response instead of the AppImage.

The most likely reason is: your CDFlow repo is private, so a normal anonymous curl to the release asset won’t work. I can see the repo is currently private.

For your own logged-in machine, use GitHub CLI so it authenticates:

gh release download v0.1.0 \
  --repo scoobystwitchs/CDFlow \
  --pattern "CDFlow-0.1.0-x86_64.AppImage"

Then:

chmod +x CDFlow-0.1.0-x86_64.AppImage
./CDFlow-0.1.0-x86_64.AppImage

If you want other users to install it with a simple curl command, the easiest option is to make the GitHub repository/release public. Then this direct URL can work without authentication:

curl -fL \
"https://github.com/scoobystwitchs/CDFlow/releases/download/v0.1.0/CDFlow-0.1.0-x86_64.AppImage" \
-o CDFlow.AppImage

The -f is useful because it makes curl fail on a 404 instead of saving "Not Found" as if it were an AppImage.

Also delete the broken 9-byte file first:

rm -f CDFlow.AppImage

If you want, I’d make CDFlow public now, then we can test the exact one-command installer that another Fedora user would run.

how can i make  github public

On GitHub, open your CDFlow repository, then go to Settings. Scroll all the way down to Danger Zone, find Change repository visibility, click Change visibility, choose Public, then confirm the warnings and click Make this repository public. GitHub notes that once it’s public, anyone can view and fork the code, and Actions history/logs become public too.

Before you do that, make sure you haven’t committed anything sensitive like API keys, passwords, private emails, tokens, or personal config files. Your .gitignore already excludes the obvious development folders, but it’s worth checking the repo contents once before making it public.

After you switch it to public, the direct curl download command for your AppImage should work without GitHub authentication.

Pasted markdown.md
File
make this cd flows welcome thing, include nice graphics, and a manual on how to use and setup, include  the appimage setup and everything, make it not look ai aswell. 

I turned your current README into a much more polished GitHub welcome page + full user manual. It keeps the technical details from your existing documentation—Fedora setup, AppImage build, privacy paths, optical-drive permissions, troubleshooting, and hardware checks —but puts the normal-user experience first.

It now includes a proper hero section, release/download buttons, feature table, installation instructions, AppImage setup, Konsole download commands, metadata setup, ripping explanation, data-CD instructions, privacy section, troubleshooting, developer setup, AppImage build guide, release guide, and a cleaner project philosophy. I also added a screenshot slot at docs/screenshots/cdflow-main.png, so once you drop a screenshot there the README will show it automatically.

Replace your existing README.md with it, then push:

cp "/path/to/README_CDFlow_polished.md" README.md
git add README.md
git commit -m "Redesign CDFlow README and user guide"
git push

For the actual graphics, I’d make one proper wide CDFlow GitHub banner plus 2–3 clean screenshots with the pink UI rather than filling the README with generic icons. That will make it look much more like a real open-source app page and much less templated.


Library
/README_CDFlow_polished.md

<div align="center">

<img src="src/cdflow/assets/io.github.cdflow.CDFlow.svg" width="118" alt="CDFlow logo">
CDFlow
Your physical CD collection, brought into a clean Linux desktop app.

Play · Browse · Identify · Rip · Remember






Download CDFlow
  •  
Installation
  •  
User Guide
  •  
Troubleshooting

</div>

CDFlow is a lightweight, local-first Linux application for using physical compact discs without the dated interface of traditional CD utilities.

Insert a disc and CDFlow reacts automatically. Audio CDs can be identified, played and ripped; data CDs can be browsed read-only; previously recognised albums can be remembered locally.

There are no accounts, no local web server, no Electron/Chromium layer, and no required cloud service. The core application remains useful offline.

    Current release: v0.1.0
    CDFlow is currently developed and tested primarily on Fedora KDE Plasma / Wayland, x86_64.

What it looks like

CDFlow uses a dark, compact interface with a pink accent and is designed to feel at home on a modern KDE desktop.

<p align="center"> <img src="docs/screenshots/cdflow-main.png" width="900" alt="CDFlow main window"> </p>

    The screenshot path above is ready for the repository. Add your preferred CDFlow screenshot as docs/screenshots/cdflow-main.png and GitHub will display it here automatically.

Features

	Feature	What it does
💿	Automatic disc detection	Reacts to optical-drive insert/eject events through UDisks2 rather than constantly polling the drive.
🎵	Audio CD playback	View tracks and use play, pause, previous, next, volume and mute controls.
🏷️	Album metadata	Optionally identifies albums and tracks using MusicBrainz and caches the result locally.
🖼️	Cover artwork	Retrieves artwork when available and keeps a local cache for recognised discs.
📥	CD ripping	Extract selected tracks or a full album to FLAC, WAV or MP3.
📁	Data CD browser	Browse mounted data discs read-only and open files using your desktop defaults.
🗃️	Local collection	Remembers previously recognised physical albums without requiring an account.
📴	Offline-friendly	Playback, disc information, browsing and ripping do not depend on metadata services.
🪶	Lightweight by design	Qt 6 UI, event-driven hardware handling and no embedded browser engine.

CDFlow does not assume your optical drive is /dev/sr0; it uses the actual device reported by the system.
Install CDFlow
Option 1 — AppImage

This is the recommended way to use CDFlow.
1. Download the latest release

Open:

github.com/scoobystwitchs/CDFlow/releases/latest

Download the file named similar to:

CDFlow-0.1.0-x86_64.AppImage

2. Make it executable

Open Konsole in the folder containing the download:

chmod +x CDFlow-0.1.0-x86_64.AppImage

3. Launch it

./CDFlow-0.1.0-x86_64.AppImage

That is enough to run the application.
Download from Konsole

For v0.1.0:

curl -fL \
  "https://github.com/scoobystwitchs/CDFlow/releases/download/v0.1.0/CDFlow-0.1.0-x86_64.AppImage" \
  -o CDFlow.AppImage

chmod +x CDFlow.AppImage
./CDFlow.AppImage

Using -f is intentional: if GitHub returns an error page, curl stops instead of saving it as a fake AppImage.
Option 2 — Install into your application menu

If the repository contains install.sh, download and inspect it first:

curl -fsSL \
  https://raw.githubusercontent.com/scoobystwitchs/CDFlow/main/install.sh \
  -o install.sh

less install.sh

Then:

chmod +x install.sh
./install.sh

A normal per-user install can keep the AppImage in:

~/.local/bin/CDFlow.AppImage

and the desktop entry in:

~/.local/share/applications/io.github.cdflow.CDFlow.desktop

After that, CDFlow should appear in your KDE application launcher.
System requirements

CDFlow currently targets:

    Fedora Linux

    KDE Plasma

    Wayland

    x86_64

    A supported internal or USB optical CD/DVD drive

The AppImage bundles CDFlow's Python and Qt application libraries, but optical-drive applications still rely on parts of the host Linux system.

On Fedora, these packages provide the recommended CD functionality:

sudo dnf install \
  udisks2 \
  libcdio \
  cdparanoia \
  ffmpeg-free \
  gstreamer1 \
  gstreamer1-plugins-base \
  gstreamer1-plugins-good \
  python3-gobject

What they are used for:
Package	Purpose
udisks2	Optical drive/media discovery and desktop integration
libcdio	CD information and TOC utilities
cdparanoia	Reliable CD digital-audio extraction
gstreamer1*	Audio CD playback path
ffmpeg-free	Local encoding/conversion support
python3-gobject	GStreamer/PyGObject integration

    CDFlow should never need to be run as root.

Using CDFlow
First launch

Start CDFlow from your application launcher or AppImage.

With an empty optical drive, the application waits for media without repeatedly scanning the device.

Insert a CD and CDFlow should automatically move to the appropriate disc view.
Audio CDs

When an audio CD is detected, CDFlow reads the table of contents and displays the available tracks.

You can then:

    play and pause

    move between tracks

    change volume or mute

    inspect the disc and drive

    retrieve album information

    rip selected tracks

    rip the full disc

    eject the disc

If online metadata has not loaded yet, tracks can initially appear as:

Track 01
Track 02
Track 03
...

The CD itself is still fully usable.
Metadata and album artwork

CDFlow can use MusicBrainz to identify a physical CD and the Cover Art Archive for artwork.

This is optional.

Open:

Settings → Metadata

Enter either:

    an email address you control, or

    a project/contact URL

MusicBrainz asks API clients to identify themselves responsibly. CDFlow uses the contact only as part of requests to the metadata services.

Then enable metadata/artwork lookup.

When a disc is inserted, CDFlow:

CD
 │
 ├─ reads disc ID + TOC
 │
 ▼
MusicBrainz disc match
 │
 ▼
best matching release
 │
 ├─ album / artist / tracks / date
 │
 └─ artwork
 │
 ▼
local cache

Successful metadata is cached by disc ID, so recognised albums do not need to be looked up every time.

Temporary 429, 502, 503 and 504 responses are retried automatically with rate limiting and backoff. Metadata failure does not prevent playback or ripping.
Ripping a CD

Ripping means copying the audio from the physical CD to music files on your computer.

It does not alter or damage the CD.

Physical CD
     │
     ▼
   CDFlow
     │
     ├────► FLAC
     ├────► WAV
     └────► MP3

The original disc remains unchanged and can still be used normally afterward.
Which format should I use?
FLAC — recommended

Lossless audio with substantially less storage use than WAV.

Choose FLAC when you want to preserve the CD's audio quality.
WAV

Uncompressed PCM audio.

Useful when you specifically need WAV, but files are considerably larger.
MP3

Smaller files with lossy compression.

Useful for devices or situations where storage size matters more than preserving the exact original audio.
Default library location

CDFlow normally writes ripped music beneath:

~/Music/CDFlow/

For example:

~/Music/CDFlow/
└── Artist/
    └── Album/
        ├── 01 - First Track.flac
        ├── 02 - Second Track.flac
        └── 03 - Third Track.flac

Existing files should never be silently overwritten.
Data CDs

When a mounted data CD is inserted, CDFlow provides a lightweight, read-only browser.

You can:

    navigate folders

    inspect files

    see basic file information

    open files using the default KDE/Linux application

    inspect the disc and drive

    eject the disc

CDFlow intentionally does not offer write/edit operations for optical media.
Local data and privacy

CDFlow follows Linux XDG conventions.
Data	Default location
Preferences	~/.config/cdflow/
Metadata and artwork cache	~/.cache/cdflow/
Remembered collection	~/.local/share/cdflow/
Ripped music	~/Music/CDFlow/

There is no CDFlow account.

Turning metadata/artwork lookup off leaves the main local features independent of the network.
Troubleshooting
No drive appears

Check whether Linux itself sees the optical drive:

udisksctl status

Then:

lsblk -o NAME,TYPE,RM,RO,MODEL,FSTYPE,LABEL,MOUNTPOINTS

You are looking for an optical device commonly named something like:

sr0

but CDFlow does not require that exact name.

Check UDisks2:

systemctl status udisks2.service

The drive appears but the CD does not

Check the actual optical device reported by udisksctl:

cd-info /dev/sr0

or for an audio CD:

cdparanoia -d /dev/sr0 -Q

Replace /dev/sr0 with the real device path on your system.

Do not fix permissions by doing:

chmod 666 /dev/sr0

and do not run CDFlow as root.
Album shows but metadata does not

Make sure Settings → Metadata contains a contact email/project URL and metadata lookup is enabled.

For development diagnostics:

./run.sh --debug

Metadata is optional; the CD can still be played or ripped without it.
MusicBrainz is temporarily unavailable

If MusicBrainz is busy, CDFlow can receive a response such as HTTP 503.

CDFlow retries temporary errors automatically.

If retries are exhausted, the app should display:

Metadata service is temporarily unavailable.

The disc remains available locally.
Ripping is unavailable

Check:

command -v cdparanoia
command -v ffmpeg

Then:

cdparanoia --version
ffmpeg -version

On Fedora:

sudo dnf install cdparanoia ffmpeg-free

Data CD is visible but cannot be browsed

It may not yet be mounted.

Try:

udisksctl mount -b /dev/sr0

using your actual optical device.

CDFlow intentionally browses the mounted filesystem rather than bypassing normal Linux permissions.
AppImage does not launch

Make sure it is executable:

chmod +x CDFlow-0.1.0-x86_64.AppImage

If the system lacks FUSE 2 compatibility, Fedora users can install:

sudo dnf install fuse-libs

or use:

./CDFlow-0.1.0-x86_64.AppImage --appimage-extract-and-run

Qt / Wayland problems

A normal Plasma Wayland session should be detected automatically.

For a source checkout, compare:

QT_QPA_PLATFORM=wayland ./run.sh --debug

with the XWayland fallback:

QT_QPA_PLATFORM=xcb ./run.sh --debug

If Qt cannot initialize a platform plugin:

QT_DEBUG_PLUGINS=1 ./run.sh

Do not copy random Qt plugins from other Qt installations into CDFlow.
Run from source

The AppImage is recommended for normal use. This section is for development.
Fedora development packages

sudo dnf install \
  python3 python3-pip python3-gobject \
  udisks2 libcdio cdparanoia ffmpeg-free \
  gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good

CDFlow requires Python 3.12 or newer.

Create the environment:

python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

Run:

./run.sh

Useful development commands:

./run.sh --demo audio
./run.sh --demo data
./run.sh --demo empty
./run.sh --debug
./run.sh --diagnose

--diagnose checks which required and optional local components are available without opening the main interface.
Building the AppImage

CDFlow's packaged build has two stages:

CDFlow source
     │
     ▼
PyInstaller
     │
     ▼
CDFlow AppDir
     │
     ▼
appimagetool
     │
     ▼
CDFlow-x86_64.AppImage

Build dependencies

sudo dnf install binutils patchelf
.venv/bin/python -m pip install -e '.[appimage]'

Download appimagetool

curl -L \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage \
  -o appimagetool-x86_64.AppImage

chmod +x appimagetool-x86_64.AppImage

Build CDFlow

From the project root:

APPIMAGETOOL="$PWD/appimagetool-x86_64.AppImage" ./build-appimage.sh

The finished release is written to:

dist/CDFlow-0.1.0-x86_64.AppImage

Test the packaged application rather than only the source build:

./dist/CDFlow-0.1.0-x86_64.AppImage

Publishing a release

Create a Git tag:

git tag -a v0.1.0 -m "CDFlow v0.1.0"
git push origin v0.1.0

Create a GitHub Release for v0.1.0 and attach:

dist/CDFlow-0.1.0-x86_64.AppImage

Users can then download the standalone application from the Releases page.
Development checks

Install the developer extras:

.venv/bin/python -m pip install -e '.[dev]'

Run tests:

.venv/bin/python -m pytest

Run Ruff:

.venv/bin/python -m ruff check src tests

The automated suite focuses on deterministic application behavior. Physical optical-drive behavior should still be checked on the hardware and distribution you intend to support.
Hardware test checklist

Before publishing a build for other systems, verify:

    CDFlow launches with an empty optical drive.

    An audio CD is detected automatically.

    Track count and durations are correct.

    Metadata and artwork populate when enabled.

    Play, pause, previous, next, volume and mute work.

    Eject during playback returns safely to the empty state.

    One track can be ripped to FLAC.

    Full-disc ripping works.

    WAV and MP3 output work when their dependencies are available.

    Cancelling a rip does not freeze the UI.

    Removing the disc while ripping is handled safely.

    A data CD can be browsed read-only.

    Cached album metadata works after reinserting a known disc.

    Offline use still provides local disc information and ripping.

    The AppImage passes the same hardware checks as the source checkout.

Project structure

src/cdflow/
├── app/        # application controller, state and settings
├── models/     # disc, album and track data
├── services/   # UDisks2, playback, ripping, metadata and cache
├── ui/         # Qt pages, widgets and styling
└── assets/     # CDFlow artwork and icons

packaging/      # desktop metadata, PyInstaller and AppImage files
tests/          # automated tests

Philosophy

CDFlow exists for a simple reason: using a physical CD on a modern Linux desktop should not feel like opening a utility from twenty years ago.

It keeps the physical part of the experience — inserting a disc, browsing an album, building a collection — while using a clean desktop interface and modern Linux services underneath.

No account required.
No browser pretending to be a desktop app.
No always-running server.

Just your discs.
License

CDFlow is available under the MIT License.

<div align="center">

CDFlow

Made for physical music on Linux.

Download ·
Source ·
Issues

</div>
