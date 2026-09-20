# Little Learners

A private, mobile-friendly family learning site.

## Included activities

- Fun Phonics: A to Z picture book and Find the Picture challenge
- Fun Tracing: letters, 15 shapes and numbers 1 to 100
- Count & Choose: 20 shuffled counting challenges
- Match the Pairs: six picture pairs, previewed for three seconds first
- Sort & Learn: 20 mixed colour and shape challenges
- Finish the Pattern: 20 changing visual sequences
- Odd One Out: 20 changing picture puzzles
- Which Has More?: 20 changing comparison challenges
- Character Dot-to-Dot: 35 to 60 ordered dots around a random themed character
- Character Maze: procedurally generated touch and Apple Pencil mazes
- Character Jigsaw: random themed pictures with 12, 20 or 24 pieces
- Spot the Difference: two fresh themed characters with five to eight visual changes
- Book shelf placeholder at `/books/`
- Separate child sticker albums and parent-PIN profile switching
- Ad-hoc good-behaviour sticker rewards
- Sticker generation monitor at `/allstickers/`

This version is intentionally voice-free. It has no bundled MP3 files and the installer does not download or generate speech.

The site includes an installable web app manifest, iPhone/iPad icons and a safe app-shell service worker. Profiles, rewards, sticker pictures and generated books are never cached by the service worker. A secure HTTPS address is required for service-worker installation outside localhost.

## Reward rules

A full phonics alphabet, full letter set, full shape set, each ten-number tracing level, or a complete learning game earns one sticker choice. The sticker is peeled, revealed and saved without leaving the activity.

Normal themes show a stable random selection of up to 20 unused stickers for the pending reward. Alphablocks shows up to 26, with one unused sticker for each available letter from A to Z.

Sticker use is stored separately for each child. A sticker remains available to the other child until both children have used it. The refill helper retires a sticker only after both children have used it.

Incomplete activity progress resets after ten minutes without interaction. Each new game cycle gets a freshly shuffled plan, and exact completed plans are remembered so they are not served again. Completed rewards and sticker albums never expire.

## Live workflow

The live site is served at `/`. Run `update-live` to download `main`, offer a rollback snapshot, install the code, preserve sticker images and generated books, then health-check the service. Run `rollback-live` if a live update needs to be reversed.

## Installation

Run `install.sh` as root on a fresh Ubuntu VPS and provide the parent profile, two child profiles and four-digit switch PIN when prompted. The installer restores the reusable sticker pack from the `sticker-pack` GitHub Release automatically.

## Sticker commands

- `generate-stickers` fills each theme to 100 active stickers.
- `backup` includes stickers, albums, game-plan memory and generated books.
- `backup no-books` includes stickers, albums and game-plan memory but excludes generated books.
- `update-live` installs the latest `main` build while preserving live data.
- `rollback-live` restores the latest saved code snapshot.
- `reset-vps` verifies the published sticker backup, removes only the Little Learners installation and performs a clean reinstall.

Generated sticker images are stored under `/root/stickers/catalog` and served copies under `/var/www/little-sounds/sticker-images`.

## Services

- Nginx serves the site on port 80.
- Gunicorn serves the local profile, progress and reward API on `127.0.0.1:8787`.
- SQLite data is stored in `/var/lib/little-sounds/little-sounds.sqlite3`.
