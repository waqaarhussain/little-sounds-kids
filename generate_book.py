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


def story_plan(client, number):
    prompt = f"""
Create one original 16-page picture-book plan for children aged 3 to 5 in UK English.
It must be a playful crossover using friendly characters from all seven themes: {THEMES}.
Use familiar character names, kindness, counting, letters and colours. Keep it safe, warm and funny.
Reading level: like a very early school reader. Each scene must have one or two short sentences,
no more than 18 words total. Use common words. Never use hard words such as beneath, suddenly,
discovered, magnificent, enormous, exclaimed, journey or mysterious.
Return JSON only with: title, and scenes. scenes must contain exactly 7 objects with heading, text,
and picture. picture is a clear visual description for one landscape illustration. Scene 7 must end the story.
This is generated book number {number}; make its story and title different from earlier books.
"""
    response = request_with_retry(
        "Story plan",
        lambda: client.responses.create(model=TEXT_MODEL, input=prompt),
    )
    raw = response.output_text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
    data = json.loads(raw)
    title = str(data.get("title", "")).strip()
    scenes = data.get("scenes", [])
    if not title or not isinstance(scenes, list) or len(scenes) != 7:
        raise RuntimeError("The story model did not return seven valid scenes.")
    cleaned = []
    for scene in scenes:
        heading = str(scene.get("heading", "")).strip()[:60]
        text = " ".join(str(scene.get("text", "")).split())
        picture = " ".join(str(scene.get("picture", "")).split())
        if not heading or not text or not picture:
            raise RuntimeError("The story model returned an incomplete scene.")
        cleaned.append({"heading": heading, "text": text, "picture": picture})
    return {"title": title[:80], "scenes": cleaned}


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
    plan = story_plan(client, number)
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
    pages.append({"type": "end", "title": "The End", "text": "The friends smiled. They had fun and helped each other."})
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
    manifest = read_manifest()
    manifest["books"].append(book)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)
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
