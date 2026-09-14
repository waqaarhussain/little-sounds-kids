# Little Learners

A private, mobile-friendly family learning site.

## Included activities

- Fun Phonics: A to Z picture book and Find the Picture challenge
- Fun Tracing: letters, nine shapes and numbers 1 to 100
- Count & Choose: ten counting challenges
- Match the Pairs: six picture pairs
- Sort & Learn: ten colour and shape challenges
- Separate child sticker albums and parent-PIN profile switching
- Ad-hoc good-behaviour sticker rewards
- Sticker generation monitor at `/allstickers/`

This version is intentionally voice-free. It has no bundled MP3 files and the installer does not download or generate speech.

## Reward rules

A full phonics alphabet, full letter set, full shape set, each ten-number tracing level, or a complete learning game earns one sticker choice. The sticker is peeled, revealed and saved without leaving the activity.

Normal themes show a stable random selection of up to 20 unused stickers for the pending reward. Alphablocks shows up to 26, with one unused sticker for each available letter from A to Z.

Sticker use is stored separately for each child. A sticker remains available to the other child until both children have used it. The refill helper retires a sticker only after both children have used it.

Incomplete activity progress resets after ten minutes without interaction. Completed rewards and sticker albums never expire.

## Installation

Run `install.sh` as root on a fresh Ubuntu VPS and provide the parent profile, two child profiles and four-digit switch PIN when prompted. The installer restores the reusable sticker pack from the `sticker-pack` GitHub Release automatically.

## Sticker commands

- `generate` securely asks for an OpenAI API key, shows progress at `/allstickers/`, and fills each theme to 100 active stickers.
- `backup-stickers` packages the current catalogue, anonymised child albums and used-sticker state, then publishes the release asset using a GitHub token.

Generated sticker images are stored under `/root/stickers/catalog` and served copies under `/var/www/little-sounds/sticker-images`.

## Services

- Nginx serves the site on port 80.
- Gunicorn serves the local profile, progress and reward API on `127.0.0.1:8787`.
- SQLite data is stored in `/var/lib/little-sounds/little-sounds.sqlite3`.
