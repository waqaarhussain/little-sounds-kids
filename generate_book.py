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
HISTORY = BOOK_ROOT / "story-history.json"
TEXT_MODEL = os.environ.get("LITTLE_SOUNDS_TEXT_MODEL", "gpt-5-mini")
IMAGE_MODEL = os.environ.get("LITTLE_SOUNDS_IMAGE_MODEL", "gpt-image-2")
VISION_MODEL = os.environ.get("LITTLE_SOUNDS_VISION_MODEL", TEXT_MODEL)
STORY_THEMES = os.environ.get("LITTLE_SOUNDS_STORY_THEMES", "Bluey, PJ Masks, SuperKitties and Paw Patrol")
BANNED_STORY_NAMES = {"alphablock", "alphablocks", "colourblock", "colourblocks", "numberblock", "numberblocks"}
SOUND_EFFECT_WORDS = {"bang", "beep", "boom", "click", "crash", "ding", "pop", "pow", "splash", "whoosh", "zap"}
HARD_STORY_WORDS = {
    "adventure", "amazed", "astonished", "beautiful", "beneath", "carefully", "celebrated",
    "discovered", "enormous", "exclaimed", "excitedly", "gathered", "journey", "magnificent",
    "mysterious", "noticed", "puzzled", "sparkling", "suddenly", "whispered", "wonderful",
}
LONG_NAME_WORDS = {"superkitties"}
IMAGE_ATTEMPTS = 3
STORY_PLAN_ATTEMPTS = 8
STORY_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "ending": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 6,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["heading", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "intro", "ending", "scenes"],
    "additionalProperties": False,
}
IMAGE_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["matches", "reason"],
    "additionalProperties": False,
}


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


def has_standalone_sound_effect(text):
    words = re.findall(r"[a-z]+", str(text).lower())
    return any(word in SOUND_EFFECT_WORDS for word in words)


def difficult_story_words(text):
    words = re.findall(r"[a-z]+", str(text).lower())
    return sorted({
        word for word in words
        if word in HARD_STORY_WORDS or (len(word) > 8 and word not in LONG_NAME_WORDS)
    })


def banned_story_names(text):
    words = set(re.findall(r"[a-z]+", str(text).lower()))
    return sorted(words & BANNED_STORY_NAMES)


def has_long_sentence(text):
    sentences = [part.strip() for part in re.split(r"[.!?]+", str(text)) if part.strip()]
    return any(len(re.findall(r"[A-Za-z]+", sentence)) > 11 for sentence in sentences)


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
    previous_notes = previous_story_notes(previous_books)
    last_problem = ""
    for attempt in range(1, STORY_PLAN_ATTEMPTS + 1):
        prompt = f"""
Create one original 16-page picture-book plan for children aged 3 to 5 in UK English.
It must be a playful crossover using friendly characters from two or more of these themes: {STORY_THEMES}.
Never use, name or show Numberblocks, Alphablocks or Colourblocks. They are not allowed in these books.
Use familiar character names, kindness, counting, letters and colours. Keep it safe, warm and funny.
Reading level: for a four-year-old who is just starting school. Each scene must have four or five very
short sentences and 24 to 34 words total. No sentence may have more than 11 words. Use only words a
four-year-old hears often, such as look, find, help, play, happy, big, small, red, run and jump.
Use a simple title of two to five words and simple headings of one to four words. Apart from character
and theme names, avoid words longer than eight letters. Never use hard words such as adventure,
amazed, astonished, beautiful, beneath, carefully, celebrated, discovered, enormous, exclaimed,
excitedly, gathered, journey, magnificent, mysterious, noticed, puzzled, sparkling, suddenly,
whispered or wonderful. If there is an easier word, always use it.
Write complete spoken sentences only. Do not write sound effects or standalone sound words such as
Bang!, Whoosh!, Pop!, Click!, Beep! or Crash!. Describe the action naturally in a proper sentence instead.
Return JSON only with: title, intro, ending, and scenes. intro and ending must each use 24 to 34 words
made from four or five very short sentences. The intro must begin the story. The ending must finish it.
Name every character shown in the intro and ending so their matching pictures can be made from those words.
scenes must contain exactly 6 objects with heading and text. Every scene must work on its own. Name every
character who appears in that scene so its picture can be made from those exact words. Do not rely on a
previous page to identify a character. Every scene must show a different moment, setting or group action.
Scene 6 must lead clearly into the ending. Do not copy any title, plot, page wording or picture from earlier books.
Use a new problem, setting, action order and ending. This is generated book number {number}.
Earlier books to avoid repeating: {previous_notes}
Previous attempt problem to fix: {last_problem or "none"}
"""
        try:
            response = request_with_retry(
                f"Story plan attempt {attempt}",
                lambda: client.responses.create(
                    model=TEXT_MODEL,
                    input=prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "little_sounds_story_plan",
                            "strict": True,
                            "schema": STORY_PLAN_SCHEMA,
                        }
                    },
                ),
            )
            raw = response.output_text.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S)
            data = json.loads(raw)
            title = str(data.get("title", "")).strip()[:80]
            intro = " ".join(str(data.get("intro", "")).split())
            ending = " ".join(str(data.get("ending", "")).split())
            scenes = data.get("scenes", [])
            if not title or not isinstance(scenes, list) or len(scenes) != 6:
                raise ValueError("return one title and exactly six scenes")
            if not 2 <= len(title.split()) <= 5 or difficult_story_words(title) or banned_story_names(title):
                raise ValueError("use a short title made from easy words for a four-year-old")
            if normalised(title) in used_titles:
                raise ValueError("use a title that has never been used before")
            for label, text in (("intro", intro), ("ending", ending)):
                if not 24 <= len(text.split()) <= 34 or normalised(text) in used_texts:
                    raise ValueError(f"write a new {label} using 24 to 34 simple words")
                if difficult_story_words(text) or banned_story_names(text) or has_long_sentence(text):
                    raise ValueError(f"make the {label} much easier for a four-year-old")
                if has_standalone_sound_effect(text):
                    raise ValueError(f"replace sound effects in the {label} with complete spoken sentences")
            cleaned = []
            new_texts = {normalised(intro), normalised(ending)}
            for scene in scenes:
                heading = str(scene.get("heading", "")).strip()[:60]
                text = " ".join(str(scene.get("text", "")).split())
                words = len(text.split())
                text_key = normalised(text)
                if not heading or not text:
                    raise ValueError("complete every heading and text field")
                if len(heading.split()) > 4 or difficult_story_words(heading) or banned_story_names(heading):
                    raise ValueError("use short, easy page headings")
                if not 24 <= words <= 34:
                    raise ValueError("write 24 to 34 simple words for every scene")
                hard_words = difficult_story_words(text)
                if hard_words:
                    raise ValueError(f"replace hard or long story words: {', '.join(hard_words)}")
                blocked_names = banned_story_names(text)
                if blocked_names:
                    raise ValueError(f"remove blocked characters: {', '.join(blocked_names)}")
                if has_long_sentence(text):
                    raise ValueError("keep every spoken sentence to 11 words or fewer")
                if has_standalone_sound_effect(text):
                    raise ValueError("replace standalone sound effects with complete spoken sentences")
                if text_key in used_texts or text_key in new_texts:
                    raise ValueError("do not repeat page wording from any book")
                new_texts.add(text_key)
                cleaned.append({"heading": heading, "text": text})
            return {"title": title, "intro": intro, "ending": ending, "scenes": cleaned}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            last_problem = str(error)
            if attempt < STORY_PLAN_ATTEMPTS:
                print(f"Story plan attempt {attempt} was incomplete. Retrying automatically: {last_problem}", flush=True)
            else:
                print(f"Story plan attempt {attempt} was still incomplete: {last_problem}", flush=True)
    raise RuntimeError(f"The story model could not make a unique valid plan: {last_problem}")


def image_bytes(client, prompt):
    response = request_with_retry(
        "Illustration",
        lambda: client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size="1024x1536",
            quality="low",
            output_format="png",
        ),
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI returned no illustration data.")
    return base64.b64decode(response.data[0].b64_json)


def image_matches_page(client, raw, page_text, label):
    encoded = base64.b64encode(raw).decode("ascii")
    check_prompt = f"""
You are checking one preschool storybook picture against its exact page words.
Exact page words: {page_text}
Return matches=true only if the picture clearly shows the same named characters, main action, setting,
colours, number of important objects and outcome. Return false if it adds a different named character,
changes the action, misses an important object, or shows Numberblocks, Alphablocks or Colourblocks.
Small background details do not matter. Do not require written words in the picture.
"""
    response = request_with_retry(
        f"{label} check",
        lambda: client.responses.create(
            model=VISION_MODEL,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": check_prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}", "detail": "low"},
                ],
            }],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "storybook_picture_check",
                    "strict": True,
                    "schema": IMAGE_CHECK_SCHEMA,
                }
            },
        ),
    )
    result = json.loads(response.output_text)
    return bool(result.get("matches")), str(result.get("reason", "Picture did not match the page."))


def matching_image_bytes(client, label, prompt, page_text):
    last_reason = ""
    for attempt in range(1, IMAGE_ATTEMPTS + 1):
        raw = image_bytes(client, prompt)
        matches, reason = image_matches_page(client, raw, page_text, label)
        if matches:
            print(f"{label} passed its page-picture check.", flush=True)
            return raw
        last_reason = reason
        print(f"{label} did not match on attempt {attempt}: {reason}", flush=True)
    raise RuntimeError(f"{label} could not be matched to its words after {IMAGE_ATTEMPTS} attempts: {last_reason}")


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


def read_history():
    if not HISTORY.is_file():
        return {"format": 1, "books": []}
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
        if isinstance(data.get("books"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"format": 1, "books": []}


def write_json_atomic(destination, data):
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def merge_history(history, books):
    known = {
        normalised(book.get("title", ""))
        for book in history["books"]
        if isinstance(book, dict) and normalised(book.get("title", ""))
    }
    changed = False
    for book in books:
        if not isinstance(book, dict):
            continue
        title = normalised(book.get("title", ""))
        if title and title not in known:
            history["books"].append(book)
            known.add(title)
            changed = True
    return changed


def create_book(client, number):
    manifest = read_manifest()
    history = read_history()
    if merge_history(history, manifest["books"]):
        write_json_atomic(HISTORY, history)
    plan = story_plan(client, number, [BASE_BOOK, *history["books"], *manifest["books"]])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = f"{clean_slug(plan['title'])}-{stamp}-{random.randrange(1000, 9999)}"
    directory = BOOK_ROOT / slug
    directory.mkdir(parents=True, exist_ok=False)
    style = (
        "Friendly polished preschool picture-book illustration, bright clean colours, soft 3D cartoon look, "
        "portrait storybook page, clear happy faces, simple uncluttered background, no written words, no logos, no watermark. "
        f"Faithful friendly characters only from these allowed worlds: {STORY_THEMES}. "
        "Never show Numberblocks, Alphablocks or Colourblocks. Show only characters named in the exact page words. "
        "Match every stated action, colour, count, object and setting. Do not add a different main action or extra hero. "
    )
    print(f"Creating cover for: {plan['title']}", flush=True)
    cover_words = f"Title: {plan['title']}. First page: {plan['intro']}"
    cover_prompt = style + "Create book-cover art for this exact title and first story moment. " + cover_words
    save_webp(matching_image_bytes(client, "Cover", cover_prompt, cover_words), directory / "cover.webp")
    for index, scene in enumerate(plan["scenes"], 1):
        print(f"Creating picture {index} of 7 for: {plan['title']}", flush=True)
        page_words = f"{scene['heading']}. {scene['text']}"
        scene_prompt = style + "Illustrate this exact page and nothing else. Exact page words: " + page_words
        save_webp(
            matching_image_bytes(client, f"Picture {index} of 7", scene_prompt, page_words),
            directory / f"scene-{index}.webp",
        )
    final_words = f"The final story page. {plan['ending']}"
    final_prompt = style + "Illustrate this exact happy ending and nothing else. Exact page words: " + final_words
    print(f"Creating picture 7 of 7 for: {plan['title']}", flush=True)
    save_webp(
        matching_image_bytes(client, "Picture 7 of 7", final_prompt, final_words),
        directory / "scene-7.webp",
    )
    pages = [
        {"type": "image", "src": f"/generated-books/{slug}/cover.webp", "alt": f"Cover of {plan['title']}"},
        {"type": "title", "title": plan["title"], "text": plan["intro"]},
    ]
    for index, scene in enumerate(plan["scenes"], 1):
        pages.append({"type": "image", "src": f"/generated-books/{slug}/scene-{index}.webp", "alt": f"Picture for: {scene['text']}"})
        pages.append({"type": "text", "title": scene["heading"], "text": scene["text"]})
    pages.extend([
        {"type": "image", "src": f"/generated-books/{slug}/scene-7.webp", "alt": f"Picture for: {plan['ending']}"},
        {"type": "end", "title": "The End", "text": plan["ending"]},
    ])
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
    merge_history(history, [book])
    write_json_atomic(HISTORY, history)
    manifest["books"].append(book)
    write_json_atomic(MANIFEST, manifest)
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
    completed = 0
    failures = []
    for number in range(1, count + 1):
        try:
            create_book(client, number)
            completed += 1
        except Exception as error:
            print(f"Book {number} failed safely: {error}", flush=True)
            failures.append(number)
    print(f"Book generation finished: {completed} of {count} completed.", flush=True)
    if failures:
        failed_numbers = ", ".join(str(number) for number in failures)
        print(f"FAILED book number(s): {failed_numbers}. Nothing incomplete was published.", flush=True)
        raise SystemExit(1)
    print("SUCCESS: every requested book is ready. Open /books/ to see them.", flush=True)


if __name__ == "__main__":
    main()
