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

Pasted markdown.md
File
make this cd flows welcome thing, include nice graphics, and a manual on how to use and setup, include  the appimage setup and everything, make it not look ai aswell. 

Once the new README is actually copied into your CDFlow project as README.md, run:

cd "/home/jsbw/Documents/VScode projects/CDflow"

git add README.md
git commit -m "Update CDFlow README and user guide"
git push origin main

If you also changed/added other files and want to push everything:

git add .
git commit -m "Update CDFlow documentation"
git push origin main

Then refresh your GitHub repo page and the new README should appear automatically.

nonono, make it for the customer side not me, dont have the stuff on how to build it its for the people that want to download it not the developer

Yep — I misunderstood the audience. The GitHub README should be the product/download page for normal CDFlow users, not developer documentation.

I’d remove all of this from the main README:

    PyInstaller instructions

    appimagetool build instructions

    Python virtual environments

    Ruff/pytest

    project structure

    publishing releases

    developer commands

    source build instructions

    internal hardware test checklist

And make it flow more like:

CDFlow → screenshots → what it does → Download → Install → First-time setup → Using CDs → Ripping → Metadata → Troubleshooting → Privacy → License.

I’ll remake the README specifically as an end-user manual.

okay remake it

Done — I remade it entirely for people downloading and using CDFlow, not developers.

The new README focuses on the actual customer/user journey: what CDFlow is, features, AppImage download and setup, adding it to the application menu, required Fedora packages, first launch, playing CDs, metadata/artwork setup, ripping and format explanations, collection/data CDs, privacy, troubleshooting, and FAQs.

All the PyInstaller, Ruff, pytest, source-building, AppImage-building, release publishing, architecture and developer internals are gone.

Once you've replaced your project's README.md, push it with:

cd "/home/jsbw/Documents/VScode projects/CDflow"

git add README.md
git commit -m "Redesign README for CDFlow users"
git push origin main

One thing I'd add next is real screenshots. The README already expects:

docs/screenshots/cdflow-main.png

A proper CDFlow hero screenshot plus maybe Now Playing, Rip CD, and Collection screenshots would make the GitHub page look much more finished.


Library
/README_CDFlow_users.md

<div align="center">

<img src="src/cdflow/assets/io.github.cdflow.CDFlow.svg" width="120" alt="CDFlow logo">
CDFlow
A modern home for your physical CDs on Linux.

Play your discs. Identify your albums. Rip your music. Keep your collection local.





Download CDFlow
  •  
Setup Guide
  •  
How to use it
  •  
Help

</div>

CDFlow is a lightweight Linux desktop app built around something simple: using a physical CD should still feel good on a modern computer.

Insert an audio CD and CDFlow can recognise it, show the album and tracks, fetch artwork, play it, and rip your music to local files.

Insert a data CD and CDFlow gives you a simple read-only browser for its contents.

There is no CDFlow account, no subscription, no local web server and no required cloud service. Your collection and ripped music stay on your computer.

    Current release: v0.1.0
    CDFlow is currently intended primarily for modern x86_64 Linux systems and has been tested on Fedora KDE Plasma / Wayland.

Preview

<p align="center"> <img src="docs/screenshots/cdflow-main.png" width="900" alt="CDFlow showing an audio CD"> </p>

    If the image above is not visible yet, the repository owner still needs to add the application screenshot at docs/screenshots/cdflow-main.png.

What can CDFlow do?

	
	
💿	Automatic CD detection	Insert or eject a disc and CDFlow reacts automatically.
🎵	Play audio CDs	Browse tracks and control playback from the app.
🏷️	Identify albums	Fetch album, artist, track and release information from MusicBrainz.
🖼️	Album artwork	Display cover artwork when it is available.
📥	Rip CDs	Save tracks to your computer as FLAC, WAV or MP3.
📁	Browse data CDs	Open folders and files from mounted data discs.
🗃️	Remember albums	Previously recognised discs can be kept in your local collection.
📴	Work offline	Core disc features do not require an internet connection.
🔒	Stay local	No account or CDFlow server is required.
Installation
Download the AppImage

The easiest way to use CDFlow is the standalone AppImage.
Step 1 — Download

Go to:
Download the latest CDFlow release

Under Assets, download the file ending in:

x86_64.AppImage

For example:

CDFlow-0.1.0-x86_64.AppImage

Step 2 — Allow the AppImage to run

Open a terminal in your Downloads folder:

cd ~/Downloads

Then:

chmod +x CDFlow-0.1.0-x86_64.AppImage

If you downloaded a newer version, replace the filename with the one you downloaded.
Step 3 — Open CDFlow

./CDFlow-0.1.0-x86_64.AppImage

That's it.

There is no traditional installer required to try CDFlow.
Download from the terminal

You can also download v0.1.0 directly:

curl -fL \
  "https://github.com/scoobystwitchs/CDFlow/releases/download/v0.1.0/CDFlow-0.1.0-x86_64.AppImage" \
  -o CDFlow.AppImage

chmod +x CDFlow.AppImage
./CDFlow.AppImage

Add CDFlow to your application menu

If the repository provides install.sh, you can install CDFlow for your Linux user so that it behaves more like a normal desktop application.

Download the installer:

curl -fsSL \
  https://raw.githubusercontent.com/scoobystwitchs/CDFlow/main/install.sh \
  -o install.sh

You can inspect it before running it:

less install.sh

Then install:

chmod +x install.sh
./install.sh

After installation, look for CDFlow in your desktop's application launcher.
Requirements

CDFlow currently targets:

    Linux

    x86_64 / 64-bit Intel or AMD

    a working internal or USB CD/DVD optical drive

CDFlow has primarily been tested on:

    Fedora Linux

    KDE Plasma

    Wayland

Other modern Linux distributions may work, but are not yet the primary tested target.
Recommended Fedora packages

The AppImage contains the CDFlow application itself, but CD playback and ripping also rely on normal Linux optical-disc and multimedia components.

On Fedora, install the recommended packages with:

sudo dnf install \
  udisks2 \
  libcdio \
  cdparanoia \
  ffmpeg-free \
  gstreamer1 \
  gstreamer1-plugins-base \
  gstreamer1-plugins-good \
  python3-gobject

You only need to do this once.

    Do not run CDFlow as root.

Using CDFlow
Starting the app

Open CDFlow from your application menu or launch the AppImage.

If your optical drive is empty, CDFlow will wait for a disc.

Insert a CD normally.

CDFlow should detect it automatically.
Playing an audio CD

Insert a standard audio CD into your optical drive.

CDFlow will read the disc and show its tracks.

If metadata is available, you can also see:

    album name

    artist

    track titles

    release information

    album artwork

Use the playback controls to:

    play

    pause

    go to the previous track

    go to the next track

    change volume

    mute

You can eject the disc from CDFlow when you are finished.
Album names, tracks and artwork

A normal audio CD does not necessarily contain all of the rich album information you see in streaming apps.

CDFlow can optionally use MusicBrainz to identify the physical disc.
Enable metadata

Open:

Settings → Metadata

Enter either:

    an email address you control, or

    a project/contact URL

Then enable metadata and artwork lookup.

MusicBrainz asks applications using its service to provide contact information in their requests. CDFlow does not require you to create a MusicBrainz account.

When a disc is recognised, CDFlow can retrieve:

    album title

    artist

    track titles

    track artists

    release date

    release information

    cover artwork

Recognised information is cached locally, so CDFlow does not need to download the same information every time you insert the disc.
If metadata is unavailable

The CD still works.

You may temporarily see:

Unknown Album

Track 01
Track 02
Track 03
...

Playback and ripping are not dependent on MusicBrainz.

If the metadata service is temporarily busy, CDFlow will retry automatically.
Ripping a CD

Ripping means copying the audio from your physical CD onto your computer.

It does not erase, alter or damage the CD.

Your original disc remains completely usable afterward.

       Physical CD
            │
            ▼
         CDFlow
       ╱     │     ╲
      ▼      ▼      ▼
    FLAC    WAV    MP3

Rip an album

Insert an audio CD and open Rip CD.

Choose the tracks you want to save, select the format and destination, then start the rip.

CDFlow performs the extraction away from the main interface so the app can remain responsive.
Which format should I choose?
FLAC

Recommended for most CD collections.

FLAC keeps the original audio quality while using less storage than uncompressed WAV.

Use FLAC if you want a high-quality local archive of your CDs.
MP3

MP3 uses much less storage and works with almost everything, but it achieves this by discarding some audio information.

Use MP3 when compatibility or file size matters more than keeping a lossless copy.
WAV

WAV stores uncompressed audio and creates much larger files.

It can be useful for particular editing or compatibility needs, but FLAC is usually a better choice for a personal music collection.
Where does ripped music go?

By default:

~/Music/CDFlow/

A recognised album may look like:

Music/
└── CDFlow/
    └── Artist/
        └── Album/
            ├── 01 - Track Name.flac
            ├── 02 - Track Name.flac
            ├── 03 - Track Name.flac
            └── ...

You can change the destination from CDFlow's ripping settings.
Your collection

CDFlow can remember discs it has previously recognised.

This gives you a simple local view of your physical music collection without turning CDFlow into an online music service.

Collection information is stored on your computer.
Data CDs

CDFlow can also recognise mounted data CDs.

Instead of the music player, you can browse the files and folders on the disc.

CDFlow's data-disc browser is intentionally read-only.

You can:

    browse folders

    inspect files

    open files with your normal Linux applications

    view disc information

    eject the disc

CDFlow does not offer file editing or writing to the disc.
Your data

CDFlow stores its information in normal Linux user directories.
What	Location
Settings	~/.config/cdflow/
Album metadata & artwork cache	~/.cache/cdflow/
Remembered collection	~/.local/share/cdflow/
Ripped music	~/Music/CDFlow/

There is no CDFlow user account.

Metadata and artwork lookup can be disabled.

With those features disabled, CDFlow's local disc functionality remains available.
Troubleshooting
CDFlow does not open

Make sure the AppImage is executable:

chmod +x CDFlow-0.1.0-x86_64.AppImage

Then:

./CDFlow-0.1.0-x86_64.AppImage

AppImage / FUSE error

Some systems may not have the FUSE compatibility library required by AppImage.

On Fedora:

sudo dnf install fuse-libs

Then try CDFlow again.

You can also use AppImage's extract-and-run mode:

./CDFlow-0.1.0-x86_64.AppImage --appimage-extract-and-run

My CD/DVD drive does not appear

First check whether Linux can see the drive:

udisksctl status

You can also run:

lsblk -o NAME,TYPE,RM,RO,MODEL,FSTYPE,LABEL,MOUNTPOINTS

An optical drive commonly appears as something similar to:

sr0

If Linux itself cannot see the drive, CDFlow cannot use it.
The drive appears, but the audio CD does not

Check whether the disc can be read outside CDFlow.

For a drive at /dev/sr0:

cdparanoia -d /dev/sr0 -Q

Your drive may use a different device path. Use the one shown by udisksctl status.

If cdparanoia also cannot read the CD, check:

    the condition of the disc

    the optical drive

    drive cables/connections

    Linux device permissions

Do not use broad permission workarounds such as:

chmod 666 /dev/sr0

and do not run CDFlow as root.
The album is not being recognised

Make sure you have configured:

Settings → Metadata

and entered a contact email or project URL.

Then eject and reinsert the CD.

Not every physical pressing is guaranteed to exist in MusicBrainz. If no match can be found, CDFlow will continue using the locally available track information.
“Metadata service is temporarily unavailable”

MusicBrainz may occasionally be busy or rate limited.

CDFlow automatically retries temporary service errors.

You do not need to eject the CD or restart the computer.

Playback and ripping continue to work without online metadata.
I can't rip a CD

On Fedora, make sure the recommended extraction/encoding tools are installed:

sudo dnf install cdparanoia ffmpeg-free

You can check them with:

command -v cdparanoia
command -v ffmpeg

A data CD appears but I can't browse it

Linux may not have mounted it yet.

Find the device:

udisksctl status

Then, for example:

udisksctl mount -b /dev/sr0

Replace /dev/sr0 with your actual optical drive.
Something still isn't working

Open an issue on GitHub:
Report a CDFlow problem

When reporting an optical-drive issue, it helps to include:

    Linux distribution

    desktop environment

    CD/DVD drive model

    whether the drive is internal or USB

    what kind of disc you inserted

    what CDFlow displayed

    any relevant error message

Do not post private information such as your metadata contact email.
Frequently asked questions
Does ripping damage the CD?

No. CDFlow only reads the disc.
Do I need an account?

No.
Do I need an internet connection?

No for normal local CD features. Internet access is only needed for optional metadata and artwork retrieval.
Can I use the CD after ripping it?

Yes. Ripping does not change the physical CD.
Does CDFlow upload my ripped music?

No.
Where is my ripped music?

By default:

~/Music/CDFlow/

Can CDFlow browse normal data CDs?

Yes, provided Linux can mount the disc.
Does CDFlow work on Windows?

The current CDFlow release is designed for Linux.
Does CDFlow work on macOS?

The current CDFlow release is designed for Linux.
What Linux distribution should I use?

CDFlow is currently developed and tested primarily on Fedora KDE Plasma. Other modern Linux distributions may work, but have not necessarily received the same testing.
About CDFlow

Physical media still has something digital libraries do not: you own the disc, you can hold it, lend it, collect it and keep it without depending on a service.

CDFlow is simply a modern Linux interface around that experience.

No subscription.

No account.

No browser-based desktop shell.

Just your CDs.
License

CDFlow is released under the MIT License.

<div align="center">
CDFlow

Physical music. Modern Linux.

Download
  •  
Report an issue

</div>
