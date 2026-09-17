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
LETTER_AUDIO_ROOT = Path("/var/www/little-sounds/phonics-audio/letters")
WORD_AUDIO_ROOT = Path("/var/www/little-sounds/phonics-audio/words")
TTS_MODEL = os.environ.get("LITTLE_SOUNDS_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("LITTLE_SOUNDS_TTS_VOICE", "marin")
VOICE_PROFILE = (
    "Use the Marin voice in a warm, friendly, feminine-sounding modern Southern British English accent. "
    "Keep the same gentle pitch, pace, energy and studio sound used for the Little Sounds book Read Aloud voice. "
    "Use a clean, dry, close-microphone sound with no echo, reverb, music or background noise."
)
WORD_CACHE_VERSION = "phonics-object-uk-marin-dry-v2"
LETTER_CACHE_VERSION = "phonics-letter-uk-marin-pure-v2"
WORD_INSTRUCTIONS = (
    f"{VOICE_PROFILE} Say only the supplied object name, exactly once. Pronounce it naturally in British English "
    "for a four-year-old child. Do not introduce it, spell it, define it, place it in a sentence or add a sound effect."
)

# UK early-years pure sounds. The example guides pronunciation but is never spoken.
PHONEMES = {
    "a": ("æ", "apple"), "b": ("b", "bat"), "c": ("k", "cat"),
    "d": ("d", "dog"), "e": ("ɛ", "egg"), "f": ("f", "fish"),
    "g": ("ɡ", "goat"), "h": ("h", "hat"), "i": ("ɪ", "insect"),
    "j": ("dʒ", "jam"), "k": ("k", "kite"), "l": ("l", "leg"),
    "m": ("m", "moon"), "n": ("n", "nest"), "o": ("ɒ", "octopus"),
    "p": ("p", "pig"), "q": ("kw", "queen"), "r": ("r", "rabbit"),
    "s": ("s", "sun"), "t": ("t", "tap"), "u": ("ʌ", "umbrella"),
    "v": ("v", "van"), "w": ("w", "web"), "x": ("ks", "box"),
    "y": ("j", "yes"), "z": ("z", "zip"),
}


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


def create_letter(client, letter, ipa, example, number, total):
    instructions = (
        f"{VOICE_PROFILE} This is a UK early-years pure-phonics recording. The input is the IPA phoneme /{ipa}/, "
        f"heard at the start of the British word '{example}'. Produce that phoneme alone exactly once. Do not say "
        f"the letter name, the word '{example}', the IPA notation or any other word. Do not add an 'uh' or schwa "
        "after a consonant. Make continuant sounds gently sustainable and stop sounds short and crisp."
    )
    return create_clip(
        client,
        label=f"letter {letter.upper()} /{ipa}/",
        input_text=f"[{ipa}]",
        instructions=instructions,
        cache_version=LETTER_CACHE_VERSION,
        destination=LETTER_AUDIO_ROOT / f"{letter}.mp3",
        audio_filter=(
            "silenceremove=start_periods=1:start_duration=0.01:start_threshold=-55dB:start_silence=0.04,"
            "areverse,silenceremove=start_periods=1:start_duration=0.01:start_threshold=-55dB:"
            "start_silence=0.08,areverse,loudnorm=I=-18:TP=-2:LRA=7,apad=pad_dur=0.14"
        ),
        max_duration=2.5,
        number=number,
        total=total,
    )


def create_word(client, word, number, total):
    return create_clip(
        client,
        label=f"object word: {word}",
        input_text=word,
        instructions=WORD_INSTRUCTIONS,
        cache_version=WORD_CACHE_VERSION,
        destination=WORD_AUDIO_ROOT / f"{slug(word)}.mp3",
        audio_filter="loudnorm=I=-18:TP=-2:LRA=7,apad=pad_dur=0.18",
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

    LETTER_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    WORD_AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    LETTER_AUDIO_ROOT.chmod(0o755)
    WORD_AUDIO_ROOT.chmod(0o755)
    words = load_words()
    client = OpenAI(api_key=key, timeout=180.0, max_retries=0)
    request_with_retry("API key check", lambda: client.models.list())

    made_letters = 0
    for number, (letter, (ipa, example)) in enumerate(PHONEMES.items(), 1):
        made_letters += int(create_letter(client, letter, ipa, example, number, len(PHONEMES)))

    made_words = 0
    for number, word in enumerate(words, 1):
        made_words += int(create_word(client, word, number, len(words)))

    print(
        f"Phonics audio cache ready: {made_letters} new letter sound(s), "
        f"{made_words} new object word(s), {len(words)} object word(s) available locally.",
        flush=True,
    )


if __name__ == "__main__":
    main()
