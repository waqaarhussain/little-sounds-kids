# Little Sounds Kids

A mobile-friendly phonics, tracing and achievement site designed for a private family VPS.

## Included

- A–Z talking phonics book with human-recorded letter sounds
- Fixed natural British narration packaged as mobile-safe MP3 files
- Find the Picture progress for every A–Z letter
- Finger, Apple Pencil and mouse tracing for A–Z, 1–9 and nine shapes
- Three remembered profiles with PIN-protected switching
- Separate child progress and sticker books
- Matching sticker positions for both children
- 100 genuinely different stickers in each of three school reward collections
- Nginx, Gunicorn, SQLite and systemd setup for Ubuntu

## Fresh Ubuntu installation

Run `install.sh` as root from a complete checkout. Set the four private values in the shell rather than committing them to this repository:

```bash
LITTLE_SOUNDS_PARENT='Parent' \
LITTLE_SOUNDS_CHILD_1='First child' \
LITTLE_SOUNDS_CHILD_2='Second child' \
LITTLE_SOUNDS_PIN='1234' \
bash install.sh
```

The install creates:

- `/var/www/little-sounds` for the website
- `/root/stickers` for the private sticker collection and source records
- `/var/lib/little-sounds/little-sounds.sqlite3` for profiles, progress and rewards
- `/opt/little-sounds` and `/opt/little-sounds-venv` for the local achievement service

## Notes

The profile PIN is child-level switching protection, not hardened authentication. Clearing a browser's site data makes that browser look like a first-time device.

Additional character sticker collections can be generated later without changing the base installation. The base installer deliberately creates only the reliable school reward collections.

Third-party licences and attribution are documented in `site/THIRD_PARTY_NOTICES.txt` and installed with the site.
