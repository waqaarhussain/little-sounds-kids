# Little Sounds Kids

A mobile-friendly phonics, tracing and achievement site designed for a private family VPS.

## Included

- A–Z talking phonics book with the site owner's UK pure-sound recording
- Fixed natural British narration packaged as mobile-safe MP3 files
- Find the Picture progress for every A–Z letter
- Finger, Apple Pencil and mouse tracing for A–Z, 1–9 and nine shapes
- Three remembered profiles with PIN-protected switching
- Saved activity progress for all three profiles, with separate child sticker albums
- A physical-style sticker sheet: choose an exact sticker, peel it off and leave its numbered space behind
- A PIN-protected gift button for awarding a Good Behaviour sticker without completing an activity
- One shared rotating catalogue of 100 active designs per theme, with independent rewards for each child
- Six final themes: Bluey, PJ Masks, SuperKitties, Paw Patrol, Numberblocks and Alphablocks
- A reusable `generate` helper that fills shortages without deleting earned stickers
- An unlinked `/allstickers/` live catalogue, grouped by theme and refreshed every 30 seconds
- A `backup-stickers` helper plus automatic fresh-install restore from a GitHub Release
- Nginx, Gunicorn, SQLite and systemd setup for Ubuntu

## Fresh Ubuntu installation

Run `install.sh` as root from a complete checkout. Set the four private values in the shell rather than committing them to this repository:

```bash
LITTLE_SOUNDS_PARENT='Parent name' \
LITTLE_SOUNDS_CHILD_1='First child' \
LITTLE_SOUNDS_CHILD_2='Second child' \
LITTLE_SOUNDS_PIN='1234' \
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

Once the first generation has completed, save the reusable 600-sticker pack to a GitHub Release:

```bash
backup-stickers
```

The helper creates `/root/stickers/little-sounds-sticker-pack.tar.gz`, then optionally uploads it to the repository's `sticker-pack` Release. It asks for a GitHub token with Contents write access. Because this repository is public, the generated sticker images in that Release are public too. The archive contains only the 600 sticker assets and anonymous design fingerprints. It never includes profile names, PINs, API keys, progress or earned-sticker records.

Future fresh installations automatically download that Release asset. If no pack has been published yet, installation continues normally and tells you to run `generate`. A different download location can be supplied with `LITTLE_SOUNDS_STICKER_BACKUP_URL`.

Useful commands:

```bash
generate status
generate watch
generate logs
```

## Notes

The profile PIN is child-level switching protection, not hardened authentication. Clearing a browser's site data makes that browser look like a first-time device.

The two children start with the same 100 choices in each theme. Their earned albums remain independent. A design used by either child is retired from both selectable sheets on the next `generate` run; the fixed space remains visible and a new design is appended.

The parent profile saves activity progress for testing, but completing a whole activity there does not issue a child reward. A fresh VPS restore brings back the generated sticker collection, not browsing profiles, learning progress or earned albums. Normal in-place updates preserve those records.

OpenAI image generation is billed separately from a ChatGPT subscription. The generator uses low-quality 1024×1024 output and stores smaller WebP copies for phones and iPads.

Third-party licences and attribution are documented in `site/THIRD_PARTY_NOTICES.txt` and installed with the site.
