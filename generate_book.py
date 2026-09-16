#!/usr/bin/env python3

import base64
import io
import json
import os
import random
import re
import shutil
import tempfile
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
previous page to identify a character. Make every page easy to draw as one still picture. Give each page one
clear main moment, not a chain of actions. Do not make several characters each do a different action on the
same page. Small gestures such as waving, hugging, pointing or clapping may support the moment, but must
never be the only detail that makes the picture match the words. Every scene must show a different moment,
setting or group action.
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
            size="1536x1024",
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
You are checking whether one preschool storybook picture is a sensible illustration for its page words.
Exact page words: {page_text}
One still picture is not expected to show every sentence or every step that happens across the page. Return
matches=true when it clearly shows the same central story moment, named main characters, setting and key
objects, without contradicting the page. Do not reject it merely because a small gesture, pose, facial
expression or later action is not visible, such as waving, hugging, pointing, smiling, clapping or holding
hands. Exact colour or object count matters only when that colour or count is central to the page.
Return false if it shows a different central event, misses a key object, replaces a named main character with
a character from another world, gets a central learning colour or count wrong, or shows Numberblocks,
Alphablocks or Colourblocks.
Return false if the picture contains a story heading, caption, sentence, paragraph, speech bubble or page
wording. A single learning symbol such as A or 3 is allowed only when the page itself needs that object.
Small background details do not matter. Never require story words to be printed inside the picture.
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


def matching_image_bytes(client, label, prompt, page_text, attempts=IMAGE_ATTEMPTS):
    last_reason = ""
    retry_prompt = prompt
    for attempt in range(1, attempts + 1):
        raw = image_bytes(client, retry_prompt)
        matches, reason = image_matches_page(client, raw, page_text, label)
        if matches:
            print(f"{label} passed its page-picture check.", flush=True)
            return raw
        last_reason = reason
        print(f"{label} did not match on attempt {attempt}: {reason}", flush=True)
        retry_prompt = (
            prompt
            + " The previous picture was rejected for these exact reasons: "
            + reason
            + " Correct every listed problem in the next picture. Keep the required colours, characters, objects and action exact. "
              "Do not add captions, story sentences, labels, signs, speech bubbles or thought bubbles."
        )
    raise RuntimeError(f"{label} could not be matched to its words after {attempts} attempts: {last_reason}")


def visual_briefs(client, page_words):
    count = len(page_words)
    schema = {
        "type": "object",
        "properties": {
            "briefs": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {"type": "string"},
            }
        },
        "required": ["briefs"],
        "additionalProperties": False,
    }
    numbered = "\n".join(f"{index + 1}. {words}" for index, words in enumerate(page_words))
    prompt = f"""
Turn these {count} preschool story pages into {count} visual-only illustration briefs in the same order.
Each brief must choose one clear still moment that best represents that whole page. Name the visible main
characters, setting, one main action, and only the colours, counts and objects that matter to that moment.
Do not try to show every sentence or several actions happening at once.
Use one short sentence. Do not copy a title, heading or full story sentence. Do not include dialogue, quotes,
speech bubbles, signs, labels, captions, page text or instructions to print words. A learning object such as a
single letter A or number 3 may appear only when the page explicitly needs it as an object.
Story pages:
{numbered}
"""
    response = request_with_retry(
        "Visual briefs",
        lambda: client.responses.create(
            model=TEXT_MODEL,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "storybook_visual_briefs",
                    "strict": True,
                    "schema": schema,
                }
            },
        ),
    )
    data = json.loads(response.output_text)
    briefs = [" ".join(str(value).split()) for value in data.get("briefs", [])]
    if len(briefs) != count or any(not value for value in briefs):
        raise RuntimeError("The image planner did not return every visual brief.")
    return briefs


def illustration_style():
    return (
        "Friendly polished preschool picture-book illustration, bright clean colours, soft 3D cartoon look, "
        "wide landscape storybook scene, clear happy faces, simple uncluttered background. Illustration only. "
        "Absolutely no title, heading, caption, sentence, paragraph, speech bubble, page wording, logo or watermark. "
        f"Faithful friendly characters only from these allowed worlds: {STORY_THEMES}. "
        "Never show Numberblocks, Alphablocks or Colourblocks. Show only characters named in the visual brief. "
        "Match the brief's central moment, key objects and setting. Do not add a different main action or extra hero. "
    )


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


def remove_unpublished_directories(before):
    published = {
        str(book.get("slug", ""))
        for book in read_manifest().get("books", [])
        if isinstance(book, dict)
    }
    for child in BOOK_ROOT.iterdir():
        if child in before or not child.is_dir() or child.name in published:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", child.name):
            shutil.rmtree(child)


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
    page_words = [
        f"{plan['title']}. {plan['intro']}",
        *(f"{scene['heading']}. {scene['text']}" for scene in plan["scenes"]),
        f"The final story page. {plan['ending']}",
    ]
    briefs = visual_briefs(client, page_words)
    style = illustration_style()
    print(f"Creating cover for: {plan['title']}", flush=True)
    cover_words = page_words[0]
    cover_prompt = style + "Draw this opening scene without any printed book title or story text: " + briefs[0]
    save_webp(matching_image_bytes(client, "Cover", cover_prompt, cover_words), directory / "cover.webp")
    for index, scene in enumerate(plan["scenes"], 1):
        print(f"Creating picture {index} of 7 for: {plan['title']}", flush=True)
        scene_words = page_words[index]
        scene_prompt = style + "Draw this scene and nothing else: " + briefs[index]
        save_webp(
            matching_image_bytes(client, f"Picture {index} of 7", scene_prompt, scene_words),
            directory / f"scene-{index}.webp",
        )
    final_words = page_words[-1]
    final_prompt = style + "Draw this happy ending and nothing else: " + briefs[-1]
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


def repair_book_pictures(client, book):
    slug = str(book.get("slug", ""))
    pages = book.get("pages", [])
    directory = BOOK_ROOT / slug
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", slug) or len(pages) != 16 or not directory.is_dir():
        raise RuntimeError(f"{book.get('title', 'Book')} has an invalid generated-book layout.")
    page_words = []
    for spread in range(8):
        image_page = pages[spread * 2]
        text_page = pages[spread * 2 + 1]
        if image_page.get("type") != "image" or text_page.get("type") not in ("title", "text", "end"):
            raise RuntimeError(f"{book.get('title', 'Book')} has an invalid page pair at spread {spread + 1}.")
        heading = str(text_page.get("title", "")).strip()
        text = str(text_page.get("text", "")).strip()
        prefix = "The final story page. " if text_page.get("type") == "end" else ""
        page_words.append(f"{prefix}{heading}. {text}".strip())
    briefs = visual_briefs(client, page_words)
    filenames = ["cover.webp", *(f"scene-{index}.webp" for index in range(1, 8))]
    style = illustration_style()
    with tempfile.TemporaryDirectory(prefix=f".{slug}-repair-", dir=BOOK_ROOT) as temporary_name:
        temporary = Path(temporary_name)
        for index, (filename, words, brief) in enumerate(zip(filenames, page_words, briefs), 1):
            label = "Cover" if index == 1 else f"Picture {index - 1} of 7"
            print(f"Repairing {book['title']}: {label.lower()}...", flush=True)
            prompt = style + "Draw this scene and nothing else: " + brief
            save_webp(matching_image_bytes(client, label, prompt, words, attempts=6), temporary / filename)
        for filename in filenames:
            (temporary / filename).replace(directory / filename)
    version = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    image_pages = [pages[index] for index in range(0, 16, 2)]
    for image_page, filename in zip(image_pages, filenames):
        image_page["src"] = f"/generated-books/{slug}/{filename}?v={version}"
    book["cover"] = f"/generated-books/{slug}/cover.webp?v={version}"
    write_json_atomic(directory / "book.json", book)


def repair_generated_book(client, selected_slug):
    manifest = read_manifest()
    books = [book for book in manifest.get("books", []) if isinstance(book, dict)]
    book = next((item for item in books if item.get("slug") == selected_slug), None)
    if book is None:
        raise RuntimeError("The selected generated book was not found.")
    repair_book_pictures(client, book)
    write_json_atomic(MANIFEST, manifest)
    print(f"Repaired: {book.get('title', 'Book')}", flush=True)
    print("SUCCESS: the selected book kept its story and received checked, caption-free pictures.", flush=True)


def main():
    key = os.environ.get("OPENAI_API_KEY", "")
    count = int(os.environ.get("BOOK_COUNT", "0"))
    repair_slug = os.environ.get("REPAIR_SLUG", "").strip()
    repair_mode = bool(repair_slug)
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    if not repair_mode and not 1 <= count <= 10:
        raise RuntimeError("BOOK_COUNT must be from 1 to 10.")
    BOOK_ROOT.mkdir(parents=True, exist_ok=True)
    client = OpenAI(api_key=key, timeout=240.0, max_retries=0)
    request_with_retry("API key check", lambda: client.models.list())
    if repair_mode:
        try:
            repair_generated_book(client, repair_slug)
        except Exception as error:
            print(f"Repair stopped safely: {error}", flush=True)
            print("The book's original pictures, story and narration were not changed.", flush=True)
            raise SystemExit(1)
        return
    completed = 0
    failures = []
    for number in range(1, count + 1):
        directories_before = {child for child in BOOK_ROOT.iterdir() if child.is_dir()}
        try:
            create_book(client, number)
            completed += 1
        except Exception as error:
            remove_unpublished_directories(directories_before)
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
