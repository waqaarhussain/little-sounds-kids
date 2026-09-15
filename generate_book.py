#!/usr/bin/env python3

import base64
import io
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image

from narrate_books import BASE_BOOK, narrate_book


BOOK_ROOT = Path("/var/www/little-sounds/generated-books")
MANIFEST = BOOK_ROOT / "books.json"
TEXT_MODEL = os.environ.get("LITTLE_SOUNDS_TEXT_MODEL", "gpt-5-mini")
IMAGE_MODEL = os.environ.get("LITTLE_SOUNDS_IMAGE_MODEL", "gpt-image-2")
THEMES = "Bluey, PJ Masks, SuperKitties, Paw Patrol, Numberblocks, Alphablocks and Colourblocks"


def clean_slug(title):
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return value or "little-learners-story"


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


def normalised(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def previous_story_notes(books):
    notes = []
    for book in books[-24:]:
        pages = book.get("pages", []) if isinstance(book, dict) else []
        story = " ".join(
            str(page.get("text", ""))
            for page in pages
            if isinstance(page, dict) and page.get("text")
        )
        notes.append({"title": str(book.get("title", "")), "story": story[:1200]})
    return json.dumps(notes, ensure_ascii=False)


def existing_values(books, field):
    values = set()
    for book in books:
        for page in book.get("pages", []) if isinstance(book, dict) else []:
            if isinstance(page, dict):
                value = normalised(page.get(field, ""))
                if value:
                    values.add(value)
    return values


def story_plan(client, number, previous_books):
    used_titles = {normalised(book.get("title", "")) for book in previous_books if isinstance(book, dict)}
    used_texts = existing_values(previous_books, "text")
    used_pictures = existing_values(previous_books, "alt")
    previous_notes = previous_story_notes(previous_books)
    last_problem = ""
    for attempt in range(1, 5):
        prompt = f"""
Create one original 16-page picture-book plan for children aged 3 to 5 in UK English.
It must be a playful crossover using friendly characters from all seven themes: {THEMES}.
Use familiar character names, kindness, counting, letters and colours. Keep it safe, warm and funny.
Reading level: like a very early school reader. Each scene must have two to four short sentences and
24 to 34 words total. Use common words. Never use hard words such as beneath, suddenly,
discovered, magnificent, enormous, exclaimed, journey or mysterious.
Return JSON only with: title, ending, and scenes. ending must be a unique 12 to 22 word final message.
scenes must contain exactly 7 objects with heading, text, and picture. picture is a clear visual description
for one landscape illustration. Every picture must show a different moment, setting or group action.
Scene 7 must finish the main action. Do not copy any title, plot, page wording or picture from earlier books.
Use a new problem, setting, action order and ending. This is generated book number {number}.
Earlier books to avoid repeating: {previous_notes}
Previous attempt problem to fix: {last_problem or "none"}
"""
        try:
            response = request_with_retry(
                f"Story plan attempt {attempt}",
                lambda: client.responses.create(model=TEXT_MODEL, input=prompt),
            )
            raw = response.output_text.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
            data = json.loads(raw)
            title = str(data.get("title", "")).strip()[:80]
            ending = " ".join(str(data.get("ending", "")).split())
            scenes = data.get("scenes", [])
            if not title or not isinstance(scenes, list) or len(scenes) != 7:
                raise ValueError("return one title and exactly seven scenes")
            if normalised(title) in used_titles:
                raise ValueError("use a title that has never been used before")
            if not 10 <= len(ending.split()) <= 24 or normalised(ending) in used_texts:
                raise ValueError("write a new ending using 12 to 22 simple words")
            cleaned = []
            new_texts = set()
            new_pictures = set()
            for scene in scenes:
                heading = str(scene.get("heading", "")).strip()[:60]
                text = " ".join(str(scene.get("text", "")).split())
                picture = " ".join(str(scene.get("picture", "")).split())
                words = len(text.split())
                text_key = normalised(text)
                picture_key = normalised(picture)
                if not heading or not text or not picture:
                    raise ValueError("complete every heading, text and picture field")
                if not 20 <= words <= 40:
                    raise ValueError("write 24 to 34 simple words for every scene")
                if text_key in used_texts or text_key in new_texts:
                    raise ValueError("do not repeat page wording from any book")
                if picture_key in used_pictures or picture_key in new_pictures:
                    raise ValueError("make every page picture different")
                new_texts.add(text_key)
                new_pictures.add(picture_key)
                cleaned.append({"heading": heading, "text": text, "picture": picture})
            return {"title": title, "ending": ending, "scenes": cleaned}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_problem = str(error)
            print(f"Story plan attempt {attempt} needs another try: {last_problem}", flush=True)
    raise RuntimeError(f"The story model could not make a unique valid plan: {last_problem}")


def image_bytes(client, prompt):
    response = request_with_retry(
        "Illustration",
        lambda: client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size="1536x1024",
            quality="low",
            output_format="png",
        ),
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI returned no illustration data.")
    return base64.b64decode(response.data[0].b64_json)


def save_webp(raw, destination):
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((960, 640), Image.Resampling.LANCZOS)
    image.save(destination, "WEBP", quality=72, method=4)


def read_manifest():
    if not MANIFEST.is_file():
        return {"format": 1, "books": []}
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if isinstance(data.get("books"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"format": 1, "books": []}


def create_book(client, number):
    manifest = read_manifest()
    plan = story_plan(client, number, [BASE_BOOK, *manifest["books"]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = f"{clean_slug(plan['title'])}-{stamp}-{random.randrange(1000, 9999)}"
    directory = BOOK_ROOT / slug
    directory.mkdir(parents=True, exist_ok=False)
    style = (
        "Friendly polished preschool picture-book illustration, bright clean colours, soft 3D cartoon look, "
        "landscape scene, clear happy faces, simple uncluttered background, no written words, no logos, no watermark. "
        f"Faithful friendly crossover characters from {THEMES}. "
    )
    print(f"Creating cover for: {plan['title']}", flush=True)
    cover_prompt = style + "Book-cover picture only, with the main friends together. " + plan["scenes"][0]["picture"]
    save_webp(image_bytes(client, cover_prompt), directory / "cover.webp")
    for index, scene in enumerate(plan["scenes"], 1):
        print(f"Creating picture {index} of 7 for: {plan['title']}", flush=True)
        save_webp(image_bytes(client, style + scene["picture"]), directory / f"scene-{index}.webp")
    pages = [{"type": "image", "src": f"/generated-books/{slug}/cover.webp", "alt": f"Cover of {plan['title']}"}]
    for index, scene in enumerate(plan["scenes"], 1):
        page_type = "title" if index == 1 else "text"
        pages.append({"type": page_type, "title": plan["title"] if index == 1 else scene["heading"], "text": scene["text"]})
        pages.append({"type": "image", "src": f"/generated-books/{slug}/scene-{index}.webp", "alt": scene["picture"][:180]})
    pages.append({"type": "end", "title": "The End", "text": plan["ending"]})
    if len(pages) != 16:
        raise RuntimeError("Book page safety check failed.")
    book = {
        "slug": slug,
        "title": plan["title"],
        "cover": f"/generated-books/{slug}/cover.webp",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": pages,
    }
    (directory / "book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["books"].append(book)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)
    try:
        narrate_book(client, book)
    except Exception as error:
        print(f"Book saved, but its narration was not ready: {error}", flush=True)
        print("Run narrate-books later to create only the missing audio.", flush=True)
    print(f"Finished: {plan['title']} (16 pages)", flush=True)


def main():
    key = os.environ.get("OPENAI_API_KEY", "")
    count = int(os.environ.get("BOOK_COUNT", "0"))
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    if not 1 <= count <= 10:
        raise RuntimeError("BOOK_COUNT must be from 1 to 10.")
    BOOK_ROOT.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=key, timeout=240.0, max_retries=0)
    request_with_retry("API key check", lambda: client.models.list())
    for number in range(1, count + 1):
        try:
            create_book(client, number)
        except Exception as error:
            print(f"Book {number} failed safely: {error}", flush=True)
    print("Book generation finished. Open /books/ to see completed books.", flush=True)


if __name__ == "__main__":
    main()
