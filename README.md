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

<p align="center">
  <img src="docs/screenshots/cdflow-main.png" width="900" alt="CDFlow main window">
</p>

The screenshot path above is ready for the repository. Add your preferred CDFlow screenshot as docs/screenshots/cdflow-main.png and GitHub will display it here automatically.

Features



Feature

What it does

💿

Automatic disc detection

Reacts to optical-drive insert/eject events through UDisks2 rather than constantly polling the drive.

🎵

Audio CD playback

View tracks and use play, pause, previous, next, volume and mute controls.

🏷️

Album metadata

Optionally identifies albums and tracks using MusicBrainz and caches the result locally.

🖼️

Cover artwork

Retrieves artwork when available and keeps a local cache for recognised discs.

📥

CD ripping

Extract selected tracks or a full album to FLAC, WAV or MP3.

📁

Data CD browser

Browse mounted data discs read-only and open files using your desktop defaults.

🗃️

Local collection

Remembers previously recognised physical albums without requiring an account.

📴

Offline-friendly

Playback, disc information, browsing and ripping do not depend on metadata services.

🪶

Lightweight by design

Qt 6 UI, event-driven hardware handling and no embedded browser engine.

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

Package

Purpose

udisks2

Optical drive/media discovery and desktop integration

libcdio

CD information and TOC utilities

cdparanoia

Reliable CD digital-audio extraction

gstreamer1*

Audio CD playback path

ffmpeg-free

Local encoding/conversion support

python3-gobject

GStreamer/PyGObject integration

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
