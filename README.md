# Little Sounds Kids

A mobile-friendly phonics, tracing and achievement site designed for a private family VPS.

## Included

- A–Z talking phonics book with human-recorded letter sounds
- Fixed natural British narration packaged as mobile-safe MP3 files
- Find the Picture progress for every A–Z letter
- Finger, Apple Pencil and mouse tracing for A–Z, 1–9 and nine shapes
- Three remembered profiles with PIN-protected switching
- Separate child progress and earned-sticker albums
- A physical-style sticker sheet: choose an exact sticker, peel it off and leave its numbered space behind
- A PIN-protected gift button for awarding a Good Behaviour sticker without completing an activity
- One shared rotating catalogue of 100 active designs per theme, with independent rewards for each child
- Six final themes: Bluey, PJ Masks, SuperKitties, Paw Patrol, Numberblocks and Alphablocks
- A reusable `generate` helper that fills shortages without deleting earned stickers
- Nginx, Gunicorn, SQLite and systemd setup for Ubuntu

## Fresh Ubuntu installation

Run `install.sh` as root from a complete checkout. Set the four private values in the shell rather than committing them to this repository:

```bash
LITTLE_SOUNDS_PARENT='Waqaar' \
LITTLE_SOUNDS_CHILD_1='Nevaeh' \
LITTLE_SOUNDS_CHILD_2='Inaara' \
LITTLE_SOUNDS_PIN='6806' \
bash install.sh
```

The install creates:

- `/var/www/little-sounds` for the website
- `/root/stickers/catalog` for permanent private PNG originals
- `/var/lib/little-sounds/little-sounds.sqlite3` for profiles, progress and rewards
- `/opt/little-sounds` and its virtual environments for the local service and generator

The base installation includes the complete sticker-book flow but does not spend API credit. After it finishes, run:

```bash
generate
```

Paste an OpenAI API key when asked. The helper masks the middle of the key in its confirmation, runs safely in the background and fills every shared theme to 100. Future runs retire designs used by either child, preserve the empty numbered spaces, keep every earned image, and generate only enough new distinct designs to restore the shared active collection to 100.

Useful commands:

```bash
generate status
generate watch
generate logs
```

## Notes

The profile PIN is child-level switching protection, not hardened authentication. Clearing a browser's site data makes that browser look like a first-time device.

The two children start with the same 100 choices in each theme. Their earned albums remain independent. A design used by either child is retired from both selectable sheets on the next `generate` run; the fixed space remains visible and a new design is appended.

OpenAI image generation is billed separately from a ChatGPT subscription. The generator uses low-quality 1024×1024 output and stores smaller WebP copies for phones and iPads.

Third-party licences and attribution are documented in `site/THIRD_PARTY_NOTICES.txt` and installed with the site.
