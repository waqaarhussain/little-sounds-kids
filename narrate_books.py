#!/usr/bin/env python3

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError


BOOK_ROOT = Path("/var/www/little-sounds/generated-books")
MANIFEST = BOOK_ROOT / "books.json"
NARRATION_ROOT = BOOK_ROOT / "narration"
TTS_MODEL = os.environ.get("LITTLE_SOUNDS_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("LITTLE_SOUNDS_TTS_VOICE", "marin")
TTS_INSTRUCTIONS = (
    "Read this children's story in a warm, friendly, feminine-sounding British English voice. "
    "Speak slowly and clearly for children aged three to five. Use gentle expression and natural pauses. "
    "Read every supplied word exactly once, in order. Do not add, remove, explain, or change any words."
)

BASE_BOOK = {
    "slug": "rainbow-rescue",
    "title": "The Rainbow Rescue",
    "pages": [
        {"type": "image"},
        {"type": "title", "title": "The Rainbow Rescue", "text": "A story about friends who help each other and bring the rainbow colours home."},
        {"type": "image"},
        {"type": "text", "title": "A windy day", "text": "Bluey and Bingo found a bright book near the tree. A strong wind opened it, and all the rainbow colours flew away."},
        {"type": "image"},
        {"type": "text", "title": "Let us help", "text": "Ginny ran over and saw the empty pages. “We can get the colours back,” she said. The friends sat together and made a clever plan."},
        {"type": "image"},
        {"type": "text", "title": "One, two, three", "text": "One, Two and Three made a strong bridge across a little stream. The friends counted their steps and walked safely to the other side."},
        {"type": "image"},
        {"type": "text", "title": "Up in the sky", "text": "Owlette and Skye flew high above the trees. They spotted red, blue and yellow lights hiding inside three soft, fluffy clouds."},
        {"type": "image"},
        {"type": "text", "title": "A, B, C", "text": "A, B and C found three colourful clues beside the path. Chase read each clue and put them in the right place. The last piece clicked into place!"},
        {"type": "image"},
        {"type": "text", "title": "The book is bright", "text": "The friends carried every colour back to the book. Red, blue and yellow jumped onto the pages, and a bright rainbow filled the sky."},
        {"type": "image"},
        {"type": "end", "title": "The End", "text": "The friends cheered under the rainbow. They had worked together, helped one another and brought every colour safely home."},
    ],
}


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
        delay = min(60, 8 * (attempt + 1)) + random.random() * 3
        print(f"{label}: waiting {delay:.0f} seconds before trying again.", flush=True)
        time.sleep(delay)
    raise RuntimeError(f"{label} failed: {last_error}")


def spoken_text(page):
    if not isinstance(page, dict) or page.get("type") == "image":
        return ""
    title = " ".join(str(page.get("title", "")).split())
    text = " ".join(str(page.get("text", "")).split())
    if page.get("type") in {"text", "end"}:
        return text
    return " ".join(part for part in (title, text) if part)


def spread_texts(book):
    pages = book.get("pages", [])
    if not isinstance(pages, list) or len(pages) != 16:
        return []
    return [" ".join(filter(None, (spoken_text(page) for page in pages[index:index + 2]))) for index in range(0, 16, 2)]


def valid_book(book):
    slug = str(book.get("slug", ""))
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", slug)) and len(spread_texts(book)) == 8


def audio_signature(text):
    source = "\n".join((TTS_MODEL, TTS_VOICE, TTS_INSTRUCTIONS, text))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def create_cached_audio(client, destination, filename, text, label):
    audio_path = destination / f"{filename}.mp3"
    hash_path = destination / f"{filename}.sha256"
    signature = audio_signature(text)
    existing_hash = hash_path.read_text(encoding="utf-8").strip() if hash_path.is_file() else ""
    if audio_path.is_file() and audio_path.stat().st_size > 1024 and existing_hash == signature:
        print(f"{label} is already cached.", flush=True)
        return 0
    temporary = destination / f".{filename}.mp3.tmp"
    temporary.unlink(missing_ok=True)
    print(f"Creating {label}...", flush=True)

    def create_audio():
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
        ) as response:
            response.stream_to_file(temporary)

    try:
        request_with_retry(label, create_audio)
        if not temporary.is_file() or temporary.stat().st_size <= 1024:
            raise RuntimeError("OpenAI returned an empty narration file.")
        temporary.replace(audio_path)
        audio_path.chmod(0o644)
        hash_path.write_text(signature + "\n", encoding="utf-8")
        hash_path.chmod(0o644)
        return 1
    finally:
        temporary.unlink(missing_ok=True)


def narrate_book(client, book):
    if not valid_book(book):
        raise RuntimeError("Book is not a valid 16-page story.")
    slug = book["slug"]
    destination = NARRATION_ROOT / slug
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o755)
    made = 0
    for spread, text in enumerate(spread_texts(book), 1):
        if not text:
            raise RuntimeError(f"Spread {spread} has no words to read.")
        made += create_cached_audio(
            client,
            destination,
            f"spread-{spread}",
            text,
            f"{book['title']}: narration {spread} of 8",
        )
    end_page = next((page for page in book["pages"] if page.get("type") == "end"), None)
    end_title = " ".join(str((end_page or {}).get("title", "The End")).split()) or "The End"
    made += create_cached_audio(
        client,
        destination,
        "spread-8-end",
        end_title,
        f"{book['title']}: final words",
    )
    return made


def generated_books():
    if not MANIFEST.is_file():
        return []
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    books = data.get("books", [])
    return [book for book in books if isinstance(book, dict) and valid_book(book)] if isinstance(books, list) else []


def main():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    BOOK_ROOT.mkdir(parents=True, exist_ok=True)
    NARRATION_ROOT.mkdir(parents=True, exist_ok=True)
    NARRATION_ROOT.chmod(0o755)
    client = OpenAI(api_key=key, timeout=240.0, max_retries=0)
    request_with_retry("API key check", lambda: client.models.list())
    books = [BASE_BOOK, *generated_books()]
    total = 0
    failures = 0
    for book in books:
        try:
            total += narrate_book(client, book)
        except Exception as error:
            failures += 1
            print(f"{book.get('title', 'Book')} failed safely: {error}", flush=True)
    print(f"Narration finished: {total} new audio clip(s), {len(books) - failures} book(s) ready.", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
