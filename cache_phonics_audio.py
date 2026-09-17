#!/usr/bin/env python3

import hashlib
import json
import os
import random
import re
import subprocess
import time
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError


WORD_BANK = Path("/var/www/little-sounds/phonicsbook/words.json")
WORD_AUDIO_ROOT = Path("/var/www/little-sounds/phonics-audio/words")
TTS_MODEL = os.environ.get("LITTLE_SOUNDS_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("LITTLE_SOUNDS_TTS_VOICE", "marin")
VOICE_PROFILE = (
    "Use the Marin voice in the same warm, friendly, feminine-sounding British English style as the Little Sounds book Read Aloud voice. "
    "Speak slowly and clearly for children aged three to five. Keep exactly the same voice character, speaking pace, energy, "
    "microphone distance and volume for every object name. Use natural British vocabulary and pronunciation, never American wording."
)
WORD_CACHE_VERSION = "object-words-uk-marin-v4"
WORD_INSTRUCTIONS = (
    f"{VOICE_PROFILE} Say only the supplied object name, exactly once. Pronounce it naturally in British English "
    "for a four-year-old child. Do not introduce it, spell it, define it, place it in a sentence or add a sound effect."
)

def slug(word):
    return re.sub(r"[^a-z0-9]+", "-", word.lower()).strip("-")


def request_with_retry(label, action):
    last_error = None
    for attempt in range(6):
        try:
            return action()
        except (RateLimitError, APITimeoutError, APIConnectionError) as error:
            last_error = error
        except APIStatusError as error:
            last_error = error
            if error.status_code < 500 and error.status_code != 429:
                raise
        delay = min(45, 5 * (attempt + 1)) + random.random() * 2
        print(f"{label}: waiting {delay:.0f} seconds before trying again.", flush=True)
        time.sleep(delay)
    raise RuntimeError(f"{label} failed: {last_error}")


def signature(input_text, instructions, cache_version):
    value = "\n".join((TTS_MODEL, TTS_VOICE, instructions, cache_version, input_text))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_clip(
    client,
    *,
    label,
    input_text,
    instructions,
    cache_version,
    destination,
    audio_filter,
    max_duration,
    number,
    total,
):
    destination.parent.mkdir(parents=True, exist_ok=True)
    filename = destination.stem
    hash_path = destination.with_suffix(".sha256")
    expected = signature(input_text, instructions, cache_version)
    existing = hash_path.read_text(encoding="utf-8").strip() if hash_path.is_file() else ""
    if destination.is_file() and destination.stat().st_size > 1024 and existing == expected:
        return False

    raw = destination.parent / f".{filename}.raw.mp3"
    normalised = destination.parent / f".{filename}.normalised.mp3"
    raw.unlink(missing_ok=True)
    normalised.unlink(missing_ok=True)
    print(f"[{number}/{total}] Caching {label}…", flush=True)

    def create_audio():
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=input_text,
            instructions=instructions,
            response_format="mp3",
        ) as response:
            response.stream_to_file(raw)

    try:
        request_with_retry(label, create_audio)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                "-af", audio_filter, "-t", str(max_duration), "-ar", "44100",
                "-codec:a", "libmp3lame", "-b:a", "128k", str(normalised),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if not normalised.is_file() or normalised.stat().st_size <= 1024:
            raise RuntimeError(f"OpenAI returned empty audio for {label}.")
        normalised.replace(destination)
        destination.chmod(0o644)
        hash_path.write_text(expected + "\n", encoding="utf-8")
        hash_path.chmod(0o644)
        return True
    finally:
        raw.unlink(missing_ok=True)
        normalised.unlink(missing_ok=True)


def create_word(client, word, number, total):
    return create_clip(
        client,
        label=f"object word: {word}",
        input_text=word,
        instructions=WORD_INSTRUCTIONS,
        cache_version=WORD_CACHE_VERSION,
        destination=WORD_AUDIO_ROOT / f"{slug(word)}.mp3",
        audio_filter="loudnorm=I=-18:TP=-2:LRA=7",
        max_duration=3.5,
        number=number,
        total=total,
    )


def load_words():
    data = json.loads(WORD_BANK.read_text(encoding="utf-8"))
    words = []
    seen = set()
    for letter in data.get("letters", []):
        for entry in letter.get("items", []):
            if not isinstance(entry, list) or len(entry) != 2:
                continue
            word = str(entry[1]).strip()
            if word and word.casefold() not in seen:
                words.append(word)
                seen.add(word.casefold())
    if len(words) < 100:
        raise RuntimeError("The phonics word bank is incomplete.")
    return words


def main():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    if not WORD_BANK.is_file():
        raise RuntimeError("The phonics word bank is missing.")

    WORD_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    WORD_AUDIO_ROOT.chmod(0o755)
    words = load_words()
    client = OpenAI(api_key=key, timeout=180.0, max_retries=0)
    request_with_retry("API key check", lambda: client.models.list())

    made_words = 0
    for number, word in enumerate(words, 1):
        made_words += int(create_word(client, word, number, len(words)))

    print(
        f"Object-word cache ready: {made_words} new UK object word(s), "
        f"{len(words)} object word(s) available locally.",
        flush=True,
    )


if __name__ == "__main__":
    main()
