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
- Book shelf placeholder at `/books/`
- Separate child sticker albums and parent-PIN profile switching
- Ad-hoc good-behaviour sticker rewards
- Sticker generation monitor at `/allstickers/`

This version is intentionally voice-free. It has no bundled MP3 files and the installer does not download or generate speech.

## Reward rules

A full phonics alphabet, full letter set, full shape set, each ten-number tracing level, or a complete learning game earns one sticker choice. The sticker is peeled, revealed and saved without leaving the activity.

Normal themes show a stable random selection of up to 20 unused stickers for the pending reward. Alphablocks shows up to 26, with one unused sticker for each available letter from A to Z.

Sticker use is stored separately for each child. A sticker remains available to the other child until both children have used it. The refill helper retires a sticker only after both children have used it.

Incomplete activity progress resets after ten minutes without interaction. Each new game cycle gets a freshly shuffled plan, and exact completed plans are remembered so they are not served again. Completed rewards and sticker albums never expire.

## Live and test workflow

The live site is served at `/`. The isolated test clone is served at `/test/` with its own SQLite database and cookie. Sticker image files are shared read-only, while album choices, achievements and used-sticker state are copied into the test database and can be changed safely.

- Future approved development is published to the GitHub `test` branch.
- Run `update-test` to load that branch into `/test/` without changing live.
- Test the build.
- Run `live` and paste a GitHub token with Contents write access.
- The helper health-checks the test build, promotes its code to live and GitHub `main`, preserves the live database, then deletes and recreates the test state from the latest live state.
- Run `refresh-test` at any time to discard test activity and clone the current live state again.

The test database is a snapshot. It deliberately stops mirroring live while testing, because sharing one database would allow test rewards to alter the children's real albums.

## Installation

Run `install.sh` as root on a fresh Ubuntu VPS and provide the parent profile, two child profiles and four-digit switch PIN when prompted. The installer restores the reusable sticker pack from the `sticker-pack` GitHub Release automatically.

## Sticker commands

- `generate` securely asks for an OpenAI API key, shows progress at `/allstickers/`, and fills each theme to 100 active stickers.
- `update-test` installs the current GitHub `test` branch only on `/test/`.
- `live` promotes the tested code to the VPS live site and GitHub `main`, without replacing live user data.
- `refresh-test` discards the test database and rebuilds it from the current live site.
- `backup-stickers` packages the current catalogue, anonymised child albums, used-sticker state and randomized-game memory, then publishes the release asset using a GitHub token.

Generated sticker images are stored under `/root/stickers/catalog` and served copies under `/var/www/little-sounds/sticker-images`.

## Services

- Nginx serves the site on port 80.
- Gunicorn serves the local profile, progress and reward API on `127.0.0.1:8787`.
- SQLite data is stored in `/var/lib/little-sounds/little-sounds.sqlite3`.
