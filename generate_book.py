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
from itertools import combinations
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
BANNED_STORY_NAMES = {
    "alphablock", "alphablocks", "colourblock", "colourblocks", "numberblock", "numberblocks",
    "kitty", "superkitty",
}
CHARACTER_ROSTERS = {
    "bluey": ("Bluey", "Bingo", "Chilli", "Bandit"),
    "pj masks": ("Catboy", "Owlette", "Gekko"),
    "superkitties": ("Ginny", "Sparks", "Buddy", "Bitsy"),
    "paw patrol": ("Chase", "Marshall", "Skye", "Rubble", "Rocky", "Zuma"),
}
CHARACTER_APPEARANCES = {
    "Bluey": "a small blue heeler puppy with blue and dark-blue fur",
    "Bingo": "a small orange heeler puppy with cream patches",
    "Chilli": "an adult red-orange heeler dog with cream patches",
    "Bandit": "an adult blue heeler dog with blue and dark-blue fur",
    "Catboy": "a child hero in a blue cat suit and blue cat-ear mask",
    "Owlette": "a child hero in a red owl suit, red mask and wing-shaped cape",
    "Gekko": "a child hero in a green lizard suit and green mask",
    "Ginny": "an orange ginger tabby cat in a pink hero suit and pink mask",
    "Sparks": "a yellow Bengal cat in a purple hero suit and purple mask",
    "Buddy": "a large calico cat in an orange hero suit and orange mask",
    "Bitsy": "a very small white kitten in a sky-blue hero suit and blue mask",
    "Chase": "a brown and tan German shepherd pup in blue police gear",
    "Marshall": "a white Dalmatian pup with black spots in red fire gear",
    "Skye": "a small tan cockapoo pup in pink flight gear",
    "Rubble": "a tan and brown bulldog pup in yellow builder gear",
    "Rocky": "a grey and white mixed-breed pup in green recycling gear",
    "Zuma": "a chocolate-brown Labrador pup in orange water-rescue gear",
}
SOUND_EFFECT_WORDS = {"bang", "beep", "boom", "click", "crash", "ding", "pop", "pow", "splash", "whoosh", "zap"}
PROTECTED_PAGE_TERMS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "red", "blue", "green", "yellow", "orange", "pink", "purple", "brown", "black", "white", "grey", "gray",
}
HARD_STORY_WORDS = {
    "adventure", "amazed", "astonished", "beautiful", "beneath", "carefully", "celebrated",
    "discovered", "enormous", "exclaimed", "excitedly", "gathered", "journey", "magnificent",
    "mysterious", "noticed", "puzzled", "sparkling", "suddenly", "whispered", "wonderful",
}
LONG_NAME_WORDS = {"superkitties"}
IMAGE_ATTEMPTS = 3
STORY_PLAN_ATTEMPTS = 8
PAGE_TEXT_ATTEMPTS = 3
MAX_CONSECUTIVE_BOOK_FAILURES = 3
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
COVER_DIVERSITY_SCHEMA = {
    "type": "object",
    "properties": {
        "distinct": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["distinct", "reason"],
    "additionalProperties": False,
}
STORY_COHERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "coherent": {"type": "boolean"},
        "natural": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["coherent", "natural", "reason"],
    "additionalProperties": False,
}
VISUAL_CONTINUITY_SCHEMA = {
    "type": "object",
    "properties": {
        "consistent": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["consistent", "reason"],
    "additionalProperties": False,
}
ADAPTED_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "heading": {"type": "string"},
        "text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["usable", "heading", "text", "reason"],
    "additionalProperties": False,
}
COVER_COMPOSITIONS = (
    "Use a wide side view with the characters moving across the scene.",
    "Use a gentle top-down view with the characters gathered around the key object.",
    "Place the key object large in the foreground and the characters farther back.",
    "Arrange the characters on a clear diagonal from near to far.",
    "Show the characters from behind as they look towards the main place or object.",
    "Use a low camera view with the characters doing the main action above it.",
    "Frame the scene through a gate, doorway, tree branches or another natural opening.",
    "Put one main character to one side in front, with the other named characters behind.",
    "Use a broad scene with the characters spread across clear left, middle and right areas.",
    "Place the characters in a loose circle around the main action, seen at a slight angle.",
)
COVER_BACKGROUNDS = (
    "a sunny beach with rock pools",
    "a green woodland path with tall trees",
    "a bright farm yard with a red barn",
    "a cosy playroom with shelves and cushions",
    "a snowy hill with small pine trees",
    "a colourful town square with little shops",
    "a flower garden with a small pond",
    "a hilltop picnic place under a wide sky",
    "a fun fair with flags and a gentle ride",
    "a riverside path with a little bridge",
)
COVER_ACTIONS = (
    "finding one surprising object together",
    "helping with one simple game",
    "carrying one special item as a team",
    "following a short trail of clues",
    "building one small thing together",
    "sorting a few bright objects",
    "getting ready for a friendly race",
    "sharing one useful item",
    "looking for one missing item",
    "celebrating one kind deed",
)


def theme_names():
    names = [part.strip() for part in re.split(r"\s*,\s*|\s+and\s+", STORY_THEMES) if part.strip()]
    return names or [STORY_THEMES]


def shuffled_cover_recipes():
    names = theme_names()
    groups = []
    if len(names) >= 2:
        groups.extend(combinations(names, 2))
    if len(names) >= 3:
        groups.extend(combinations(names, 3))
    if not groups:
        groups = [tuple(names)]
    groups = list(groups)
    backgrounds = list(COVER_BACKGROUNDS)
    actions = list(COVER_ACTIONS)
    seed = os.environ.get("BOOK_RECIPE_SEED", "") or str(random.SystemRandom().getrandbits(128))
    recipe_random = random.Random(seed)
    recipe_random.shuffle(groups)
    recipe_random.shuffle(backgrounds)
    recipe_random.shuffle(actions)
    return groups, backgrounds, actions


THEME_GROUPS, SHUFFLED_COVER_BACKGROUNDS, SHUFFLED_COVER_ACTIONS = shuffled_cover_recipes()


def book_cover_recipe(number):
    index = max(0, number - 1)
    return (
        THEME_GROUPS[index % len(THEME_GROUPS)],
        SHUFFLED_COVER_BACKGROUNDS[index % len(SHUFFLED_COVER_BACKGROUNDS)],
        SHUFFLED_COVER_ACTIONS[index % len(SHUFFLED_COVER_ACTIONS)],
        COVER_COMPOSITIONS[index % len(COVER_COMPOSITIONS)],
    )


def roster_for_theme(theme):
    return CHARACTER_ROSTERS.get(normalised(theme), ())


def text_names_character(text, character):
    return f" {normalised(character)} " in f" {normalised(text)} "


def character_appearance_guide(text):
    details = [
        f"{name}: {appearance}"
        for name, appearance in CHARACTER_APPEARANCES.items()
        if text_names_character(text, name)
    ]
    return "; ".join(details)


def complete_character_roster():
    return "; ".join(
        f"{theme}: {', '.join(names)}"
        for theme, names in CHARACTER_ROSTERS.items()
    )


def named_characters(text):
    return {
        name
        for name in CHARACTER_APPEARANCES
        if text_names_character(text, name)
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


def protected_page_terms(text):
    words = set(re.findall(r"[a-z]+|[0-9]+", str(text).lower()))
    return words & PROTECTED_PAGE_TERMS


def has_long_sentence(text):
    sentences = [part.strip() for part in re.split(r"[.!?]+", str(text)) if part.strip()]
    return any(len(re.findall(r"[A-Za-z]+", sentence)) > 11 for sentence in sentences)


def has_unpunctuated_character_list(text):
    names = sorted(CHARACTER_APPEARANCES, key=len, reverse=True)
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I)
    matches = list(pattern.finditer(str(text)))
    for first, second in zip(matches, matches[1:]):
        separator = str(text)[first.end():second.start()]
        if not separator.strip():
            return True
    return False


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


def story_is_coherent(client, plan, label="Story sequence"):
    ordered_pages = [
        f"Opening — {plan['title']}: {plan['intro']}",
        *(
            f"Page {index} — {scene['heading']}: {scene['text']}"
            for index, scene in enumerate(plan["scenes"], 1)
        ),
        f"Ending — {plan['ending']}",
    ]
    prompt = f"""
Check this eight-part preschool story in order:
{chr(10).join(ordered_pages)}

Return coherent=true only if it is one clear continuous story rather than eight random activities. The opening
must introduce the main cast, place and one goal or problem. Each page must follow naturally from the page
before it and move that same goal forward. The ending must solve that goal. A character cannot vanish for most
of the story and then suddenly win, solve the problem or become the main hero. A race winner must be shown
joining or running the race earlier. Letters, counting, colours, games and objects must help the same plot, not
appear as unrelated lessons. Small changes of place are fine only when the story clearly moves there. Reject
abrupt jumps in activity, unexplained new goals, disconnected page pairs, or an ending that was not prepared.
Return natural=true only when every page sounds like a warm human-written story for a four-year-old. Require
correct basic grammar and punctuation. Lists of names or items must use commas, such as “Bingo, Bandit,
Owlette and Sparks.” Reject missing small words, stiff template phrases, odd word order, unclear pronouns,
unnatural lines such as “The shops are bright as they come in,” and repeated filler that does not move the story.
Keep the wording simple, but never make it broken or robotic.
"""
    response = request_with_retry(
        label,
        lambda: client.responses.create(
            model=TEXT_MODEL,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "preschool_story_coherence",
                    "strict": True,
                    "schema": STORY_COHERENCE_SCHEMA,
                }
            },
        ),
    )
    result = json.loads(response.output_text)
    approved = bool(result.get("coherent")) and bool(result.get("natural"))
    return approved, str(result.get("reason", "The pages do not form one natural story."))


def story_plan(client, number, previous_books, selected_themes, cover_background, cover_action):
    used_titles = {normalised(book.get("title", "")) for book in previous_books if isinstance(book, dict)}
    used_texts = existing_values(previous_books, "text")
    previous_notes = previous_story_notes(previous_books)
    selected_rosters = {
        theme: roster_for_theme(theme)
        for theme in selected_themes
    }
    roster_rules = "; ".join(
        f"{theme}: {', '.join(names)}"
        for theme, names in selected_rosters.items()
        if names
    )
    last_problem = ""
    for attempt in range(1, STORY_PLAN_ATTEMPTS + 1):
        prompt = f"""
Create one original 16-page picture-book plan for children aged 3 to 5 in UK English.
It must be a playful crossover using friendly characters from every one of these selected themes:
{", ".join(selected_themes)}. Do not use characters from the other available themes in this book.
Use at least one named character from each selected theme. Where that theme has other friendly characters,
avoid repeating the exact named character group used by the recent books below.
Use character names only from this exact roster: {roster_rules}. Never invent, shorten or rename a character.
For SuperKitties, the only hero names are Ginny, Sparks, Buddy and Bitsy. There is no character named Kitty.
Never use, name or show Numberblocks, Alphablocks or Colourblocks. They are not allowed in these books.
Keep it safe, warm and funny. Choose only one simple learning idea from kindness, counting, letters or
colours, and make it help the story's single goal. Do not insert unrelated learning games on later pages.
Reading level: for a four-year-old who is just starting school. Each scene must have four or five very
short sentences and 24 to 34 words total. No sentence may have more than 11 words. Use only words a
four-year-old hears often, such as look, find, help, play, happy, big, small, red, run and jump.
Write natural, warm sentences that a parent would happily read aloud. Use correct grammar, articles and
prepositions. Put commas between names and items in every list, with “and” before the last item. Never remove
punctuation merely to make the words simpler. Avoid stiff, repetitive or computer-like phrases.
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
The intro and cover must take place in {cover_background}. Centre that opening moment on {cover_action}.
The intro must introduce the whole main cast and one clear goal or small problem. Use one named character
from each selected theme and at most one extra character. Keep that same small cast through the whole book.
No new named character may appear after the intro. Every main character must take part throughout the story.
scenes must contain exactly 6 objects with heading and text. Each scene must continue directly from the prior
scene and move the same goal forward. Name every character shown so the picture can match the exact words.
Make every page easy to draw as one still picture. Give each page one
clear main moment, not a chain of actions. Do not make several characters each do a different action on the
same page. Small gestures such as waving, hugging, pointing or clapping may support the moment, but must
never be the only detail that makes the picture match the words. Do not jump to a new game, lesson, goal or
place without explaining why it is the next step. Scene 6 must lead clearly into the ending, and the ending must
solve the exact goal from the intro. Do not copy any title, plot, page wording or picture from earlier books.
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
            for theme, roster in selected_rosters.items():
                if roster and not any(text_names_character(intro, name) for name in roster):
                    raise ValueError(f"name a real {theme} character from the supplied roster in the intro")
            for label, text in (("intro", intro), ("ending", ending)):
                if not 24 <= len(text.split()) <= 34 or normalised(text) in used_texts:
                    raise ValueError(f"write a new {label} using 24 to 34 simple words")
                if difficult_story_words(text) or banned_story_names(text) or has_long_sentence(text):
                    raise ValueError(f"make the {label} much easier for a four-year-old")
                if has_standalone_sound_effect(text):
                    raise ValueError(f"replace sound effects in the {label} with complete spoken sentences")
                if has_unpunctuated_character_list(text):
                    raise ValueError(f"use commas between character names in the {label}")
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
                if has_unpunctuated_character_list(text):
                    raise ValueError("use commas between character names in every list")
                if text_key in used_texts or text_key in new_texts:
                    raise ValueError("do not repeat page wording from any book")
                new_texts.add(text_key)
                cleaned.append({"heading": heading, "text": text})
            intro_cast = named_characters(intro)
            later_pages = [(f"scene {index}", scene["text"]) for index, scene in enumerate(cleaned, 1)]
            later_pages.append(("ending", ending))
            for page_label, page_text in later_pages:
                unexpected = named_characters(page_text) - intro_cast
                if unexpected:
                    raise ValueError(
                        f"introduce {', '.join(sorted(unexpected))} in the opening before using them in {page_label}"
                    )
            all_pages = [intro, *(scene["text"] for scene in cleaned), ending]
            for character in intro_cast:
                appearances = sum(text_names_character(page, character) for page in all_pages)
                if appearances < 4:
                    raise ValueError(f"keep {character} involved throughout at least four story pages")
            candidate = {"title": title, "intro": intro, "ending": ending, "scenes": cleaned}
            coherent, coherence_reason = story_is_coherent(client, candidate, "Story plan coherence check")
            if not coherent:
                raise ValueError(f"make all pages one continuous story: {coherence_reason}")
            return candidate
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
    identity_guide = character_appearance_guide(page_text)
    check_prompt = f"""
You are checking whether one preschool storybook picture is a sensible illustration for its page words.
Exact page words: {page_text}
Exact appearance guide for every named character on this page: {identity_guide or "no named character guide"}
One still picture is not expected to show every sentence or every step that happens across the page. Return
matches=true when it clearly shows the same central story moment, named main characters, setting and key
objects, without contradicting the page. Do not reject it merely because a small gesture, pose, facial
expression or later action is not visible, such as waving, hugging, pointing, smiling, clapping or holding
hands. Exact colour or object count matters only when that colour or count is central to the page.
Return false if it shows a different central event, misses a key object, replaces a named main character with
a character from another world, gets a central learning colour or count wrong, or shows Numberblocks,
Alphablocks or Colourblocks.
Return false if a named character has the wrong fur colour, species, mask, suit or uniform from the appearance
guide. A different character from the same programme does not count as the named character. For example, a
small white SuperKitties cat in blue is Bitsy, never Ginny; Ginny must be an orange tabby in pink.
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


def image_continues_previous_page(client, previous_raw, current_raw, previous_words, current_words, label):
    previous_encoded = base64.b64encode(previous_raw).decode("ascii")
    current_encoded = base64.b64encode(current_raw).decode("ascii")
    prompt = f"""
Check visual continuity between two consecutive preschool storybook pictures. The first supplied image is the
previous page and the second supplied image is the new page.
Previous page words: {previous_words}
New page words: {current_words}

Return consistent=true when recurring characters and important story objects keep the same identity and visible
features. An object may move, turn, fold, open, close or gain something only when the page words explain that
change. Return false when a continuing object silently changes its base colour, shape, pattern or key parts. For
example, a blue blanket with red, blue and green square patches cannot become a blanket with a pink star and a
yellow circle on the next page. Also reject a named character changing into a different character. Different
camera views, poses, lighting, backgrounds and non-recurring small props are fine. If no important object carries
between the pages, return true. Explain only the key continuity reason.
"""
    response = request_with_retry(
        f"{label} continuity check",
        lambda: client.responses.create(
            model=VISION_MODEL,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{previous_encoded}", "detail": "high"},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{current_encoded}", "detail": "high"},
                ],
            }],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "storybook_visual_continuity",
                    "strict": True,
                    "schema": VISUAL_CONTINUITY_SCHEMA,
                }
            },
        ),
    )
    result = json.loads(response.output_text)
    return bool(result.get("consistent")), str(result.get("reason", "The recurring story object changed."))


def existing_cover_bytes(manifest, limit=10):
    covers = []
    books = [book for book in manifest.get("books", []) if isinstance(book, dict)]
    for book in reversed(books):
        slug = str(book.get("slug", ""))
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", slug):
            continue
        path = BOOK_ROOT / slug / "cover.webp"
        try:
            covers.append(path.read_bytes())
        except OSError:
            continue
        if len(covers) >= limit:
            break
    return covers


def cover_reference_sheet(covers):
    tiles = []
    for raw in covers:
        try:
            tile = Image.open(io.BytesIO(raw)).convert("RGB")
            tile.thumbnail((320, 214), Image.Resampling.LANCZOS)
            tiles.append(tile.copy())
        except (OSError, ValueError):
            continue
    if not tiles:
        return b""
    columns = 2
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 320, rows * 214), "white")
    for index, tile in enumerate(tiles):
        x = (index % columns) * 320 + (320 - tile.width) // 2
        y = (index // columns) * 214 + (214 - tile.height) // 2
        sheet.paste(tile, (x, y))
    output = io.BytesIO()
    sheet.save(output, "JPEG", quality=78, optimize=True)
    return output.getvalue()


def cover_is_distinct(client, raw, earlier_covers):
    sheet = cover_reference_sheet(earlier_covers)
    if not sheet:
        return True, ""
    current_encoded = base64.b64encode(raw).decode("ascii")
    sheet_encoded = base64.b64encode(sheet).decode("ascii")
    prompt = """
The first image is a proposed new preschool book cover. The second image is a sheet of earlier covers.
Return distinct=false when the new cover repeats an earlier cover's main camera view, character arrangement,
pose, action and background so closely that the shelf would look like copies with different titles. Using the
same familiar characters or the same art style is fine. Return distinct=true when the new cover has a clearly
different composition, viewpoint, key action, main object or setting. Explain the most important reason briefly.
"""
    response = request_with_retry(
        "Cover diversity check",
        lambda: client.responses.create(
            model=VISION_MODEL,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{current_encoded}", "detail": "low"},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{sheet_encoded}", "detail": "high"},
                ],
            }],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "storybook_cover_diversity",
                    "strict": True,
                    "schema": COVER_DIVERSITY_SCHEMA,
                }
            },
        ),
    )
    result = json.loads(response.output_text)
    return bool(result.get("distinct")), str(result.get("reason", "Cover looks too similar."))


def try_matching_image_bytes(client, label, prompt, page_text, attempts=IMAGE_ATTEMPTS):
    last_reason = ""
    last_raw = None
    retry_prompt = prompt
    for attempt in range(1, attempts + 1):
        raw = image_bytes(client, retry_prompt)
        last_raw = raw
        matches, reason = image_matches_page(client, raw, page_text, label)
        if matches:
            print(f"{label} passed its page-picture check.", flush=True)
            return raw, ""
        last_reason = reason
        print(f"{label} did not match on attempt {attempt}: {reason}", flush=True)
        retry_prompt = (
            prompt
            + " The previous picture was rejected for these exact reasons: "
            + reason
            + " Correct every listed problem in the next picture. Keep the required colours, characters, objects and action exact. "
              "Do not add captions, story sentences, labels, signs, speech bubbles or thought bubbles."
        )
    return last_raw, last_reason


def matching_image_bytes(client, label, prompt, page_text, attempts=IMAGE_ATTEMPTS):
    raw, last_reason = try_matching_image_bytes(client, label, prompt, page_text, attempts)
    if raw is not None and not last_reason:
        return raw
    raise RuntimeError(f"{label} could not be matched to its words after {attempts} attempts: {last_reason}")


def page_match_words(page_type, heading, text):
    if page_type == "end":
        return f"The final story page. {text}".strip()
    return f"{heading}. {text}".strip()


def adapted_page_from_image(
    client, raw, label, page_type, heading, text, story_context, first_problem, forbidden_texts
):
    encoded = base64.b64encode(raw).decode("ascii")
    fixed_heading = heading if page_type in {"title", "end"} else ""
    last_problem = first_problem
    official_roster = complete_character_roster()
    for attempt in range(1, PAGE_TEXT_ATTEMPTS + 1):
        heading_rule = (
            f"Keep the heading exactly as {json.dumps(fixed_heading)}."
            if fixed_heading
            else "Write a new easy heading of one to four words that matches the picture."
        )
        prompt = f"""
Rewrite one page of a picture book for children aged 3 to 5 so its words truthfully match the supplied picture.
The picture was made for this original page: {heading}. {text}
Story context to preserve where the picture allows it: {story_context}
The last mismatch was: {last_problem}
{heading_rule}
Return usable=false if the picture contains a caption, story sentence, speech bubble, logo, watermark,
Numberblocks, Alphablocks or Colourblocks. Also return usable=false when the picture replaces or omits a named
original character, changes the central action, changes the setting, or shows a different story event; that picture
must be regenerated. Official character names are: {official_roster}. Never invent, shorten or guess a character
name. Keep every original named character, the central goal, action and setting exactly the same. Never change,
add or remove a number, count or colour. You may only adjust a small visible pose or gesture that does not change the plot.
Otherwise return usable=true and write four or five complete,
very short UK-English sentences totalling 24 to 34 words. Describe only characters, actions, colours,
counts, objects and settings clearly visible in the picture. Keep the page kind, safe tone and nearby story flow.
Use words a four-year-old knows. No sentence may exceed 11 words. Do not use sound
effects. Apart from character names, avoid words longer than eight letters. Do not copy another page's
wording from the story context. Do not mention the picture.
"""
        response = request_with_retry(
            f"{label} word match attempt {attempt}",
            lambda: client.responses.create(
                model=VISION_MODEL,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}", "detail": "low"},
                    ],
                }],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "adapted_storybook_page",
                        "strict": True,
                        "schema": ADAPTED_PAGE_SCHEMA,
                    }
                },
            ),
        )
        data = json.loads(response.output_text)
        if not data.get("usable"):
            raise RuntimeError(f"{label} cannot safely be matched by changing its words: {data.get('reason', last_problem)}")
        adapted_heading = fixed_heading or " ".join(str(data.get("heading", "")).split())[:60]
        adapted_text = " ".join(str(data.get("text", "")).split())
        words = len(adapted_text.split())
        if not adapted_heading or not 24 <= words <= 34:
            last_problem = "use a valid heading and exactly 24 to 34 words"
            continue
        if len(adapted_heading.split()) > 4 or difficult_story_words(adapted_heading) or banned_story_names(adapted_heading):
            last_problem = "make the heading short, easy and free of blocked characters"
            continue
        hard_words = difficult_story_words(adapted_text)
        blocked_names = banned_story_names(adapted_text)
        if hard_words or blocked_names or has_long_sentence(adapted_text) or has_standalone_sound_effect(adapted_text):
            last_problem = "use only easy short sentences, with no blocked characters or sound effects"
            continue
        original_details = protected_page_terms(f"{heading} {text}")
        adapted_details = protected_page_terms(f"{adapted_heading} {adapted_text}")
        if adapted_details != original_details:
            last_problem = "keep every original number, count and colour exactly unchanged"
            continue
        if normalised(adapted_text) in forbidden_texts:
            last_problem = "write new words that are not the same as another page or older book"
            continue
        adapted_words = page_match_words(page_type, adapted_heading, adapted_text)
        matches, reason = image_matches_page(client, raw, adapted_words, f"{label} adapted words")
        if matches:
            print(f"{label} kept its picture and adjusted its page words to match.", flush=True)
            return adapted_heading, adapted_text
        last_problem = reason
    raise RuntimeError(f"{label} picture and adjusted words still did not agree: {last_problem}")


def adaptive_story_image(
    client,
    label,
    prompt,
    page_type,
    heading,
    text,
    story_context,
    forbidden_texts,
    earlier_covers=(),
    previous_raw=None,
    previous_words="",
):
    original_words = page_match_words(page_type, heading, text)
    retry_prompt = prompt
    last_problem = ""
    for image_attempt in range(1, IMAGE_ATTEMPTS + 1):
        raw = image_bytes(client, retry_prompt)
        if earlier_covers:
            distinct, diversity_reason = cover_is_distinct(client, raw, earlier_covers)
            if not distinct:
                last_problem = diversity_reason
                print(f"{label} looked too much like an earlier cover: {diversity_reason}", flush=True)
                retry_prompt = (
                    prompt
                    + " Make this cover visibly different from the earlier shelf covers. Change its camera view, "
                      "character layout, key action and background while keeping the story moment correct. "
                    + diversity_reason
                )
                continue
        matches, reason = image_matches_page(client, raw, original_words, label)
        if matches:
            if previous_raw is not None:
                consistent, continuity_reason = image_continues_previous_page(
                    client, previous_raw, raw, previous_words, original_words, label
                )
                if not consistent:
                    last_problem = continuity_reason
                    print(f"{label} broke visual continuity: {continuity_reason}", flush=True)
                    retry_prompt = (
                        prompt
                        + " Keep every recurring character and important story object visually consistent with "
                          "the prior page. Fix this continuity problem: "
                        + continuity_reason
                    )
                    continue
            print(f"{label} passed its page-picture check.", flush=True)
            return raw, heading, text
        print(f"{label} did not match its first words: {reason}", flush=True)
        try:
            adapted_heading, adapted_text = adapted_page_from_image(
                client, raw, label, page_type, heading, text, story_context, reason, forbidden_texts
            )
            adapted_words = page_match_words(page_type, adapted_heading, adapted_text)
            if previous_raw is not None:
                consistent, continuity_reason = image_continues_previous_page(
                    client, previous_raw, raw, previous_words, adapted_words, label
                )
                if not consistent:
                    last_problem = continuity_reason
                    print(f"{label} broke visual continuity: {continuity_reason}", flush=True)
                    retry_prompt = (
                        prompt
                        + " Keep every recurring character and important story object visually consistent with "
                          "the prior page. Fix this continuity problem: "
                        + continuity_reason
                    )
                    continue
            return raw, adapted_heading, adapted_text
        except RuntimeError as error:
            last_problem = str(error)
            print(
                f"{label} could not safely change its words on picture attempt {image_attempt}: {error}",
                flush=True,
            )
        retry_prompt = (
            prompt
            + " The previous picture could not be paired safely with simple page words because: "
            + last_problem
            + " Make a clean, caption-free replacement with the named characters and one very clear action."
        )
    raise RuntimeError(
        f"{label} could not produce one safe picture-and-words pair after {IMAGE_ATTEMPTS} picture attempts: {last_problem}"
    )


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
    selected_themes, cover_background, cover_action, composition = book_cover_recipe(number)
    plan = story_plan(
        client,
        number,
        [BASE_BOOK, *history["books"], *manifest["books"]],
        selected_themes,
        cover_background,
        cover_action,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = f"{clean_slug(plan['title'])}-{stamp}-{random.randrange(1000, 9999)}"
    directory = BOOK_ROOT / slug
    directory.mkdir(parents=True, exist_ok=False)
    page_words = [
        f"{plan['title']}. {plan['intro']}",
        *(f"{scene['heading']}. {scene['text']}" for scene in plan["scenes"]),
        f"The final story page. {plan['ending']}",
    ]
    story_context = " ".join(page_words)
    final_page_texts = existing_values([BASE_BOOK, *history["books"], *manifest["books"]], "text")
    briefs = visual_briefs(client, page_words)
    style = illustration_style()
    print(f"Creating cover for: {plan['title']}", flush=True)
    earlier_covers = existing_cover_bytes(manifest)
    cover_prompt = (
        style
        + "Draw this opening scene without any printed book title or story text: "
        + briefs[0]
        + " Required cover setting: "
        + cover_background
        + ". Required main cover activity: "
        + cover_action
        + ". Use only characters from these selected themes: "
        + ", ".join(selected_themes)
        + "."
        + " Exact named character appearance guide: "
        + character_appearance_guide(page_words[0])
        + ". Do not swap one named character for another from the same show."
        + " For this cover only: "
        + composition
    )
    cover_raw, _, plan["intro"] = adaptive_story_image(
        client,
        "Cover",
        cover_prompt,
        "title",
        plan["title"],
        plan["intro"],
        story_context,
        final_page_texts,
        earlier_covers,
    )
    final_page_texts.add(normalised(plan["intro"]))
    save_webp(cover_raw, directory / "cover.webp")
    previous_raw = cover_raw
    previous_words = page_match_words("title", plan["title"], plan["intro"])
    for index, scene in enumerate(plan["scenes"], 1):
        print(f"Creating picture {index} of 7 for: {plan['title']}", flush=True)
        scene_prompt = (
            style
            + "Draw this scene and nothing else: "
            + briefs[index]
            + " Exact named character appearance guide: "
            + character_appearance_guide(page_words[index])
            + ". Do not swap one named character for another from the same show."
        )
        scene_raw, scene["heading"], scene["text"] = adaptive_story_image(
            client,
            f"Picture {index} of 7",
            scene_prompt,
            "text",
            scene["heading"],
            scene["text"],
            story_context,
            final_page_texts,
            previous_raw=previous_raw,
            previous_words=previous_words,
        )
        final_page_texts.add(normalised(scene["text"]))
        save_webp(scene_raw, directory / f"scene-{index}.webp")
        previous_raw = scene_raw
        previous_words = page_match_words("text", scene["heading"], scene["text"])
    final_prompt = (
        style
        + "Draw this happy ending and nothing else: "
        + briefs[-1]
        + " Exact named character appearance guide: "
        + character_appearance_guide(page_words[-1])
        + ". Do not swap one named character for another from the same show."
    )
    print(f"Creating picture 7 of 7 for: {plan['title']}", flush=True)
    final_raw, _, plan["ending"] = adaptive_story_image(
        client,
        "Picture 7 of 7",
        final_prompt,
        "end",
        "The End",
        plan["ending"],
        story_context,
        final_page_texts,
        previous_raw=previous_raw,
        previous_words=previous_words,
    )
    final_page_texts.add(normalised(plan["ending"]))
    save_webp(final_raw, directory / "scene-7.webp")
    coherent, coherence_reason = story_is_coherent(client, plan, "Final story coherence check")
    if not coherent:
        raise RuntimeError(f"Final page sequence was rejected before publishing: {coherence_reason}")
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
    start_count = int(os.environ.get("BOOK_START_COUNT", "0"))
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
    current_count = len([
        book for book in read_manifest().get("books", [])
        if isinstance(book, dict)
    ])
    completed = max(0, min(count, current_count - start_count))
    if completed:
        print(f"Resuming this job: {completed} of {count} requested books are already complete.", flush=True)
    consecutive_failures = 0
    total_failures = 0
    while completed < count:
        number = completed + 1
        directories_before = {child for child in BOOK_ROOT.iterdir() if child.is_dir()}
        try:
            create_book(client, number)
            completed += 1
            consecutive_failures = 0
        except Exception as error:
            remove_unpublished_directories(directories_before)
            consecutive_failures += 1
            total_failures += 1
            print(f"Book slot {number} attempt failed safely: {error}", flush=True)
            if consecutive_failures < MAX_CONSECUTIVE_BOOK_FAILURES:
                print(f"Creating a fresh replacement plan for book slot {number} automatically.", flush=True)
            else:
                print(
                    f"Stopped after {MAX_CONSECUTIVE_BOOK_FAILURES} consecutive full-book failures to limit cost.",
                    flush=True,
                )
                break
    print(f"Book generation finished: {completed} of {count} completed.", flush=True)
    if completed < count:
        print(
            f"FAILED: {count - completed} requested book(s) are still missing after {total_failures} safe replacement attempt(s).",
            flush=True,
        )
        raise SystemExit(1)
    print("SUCCESS: every requested book is ready. Open /books/ to see them.", flush=True)


if __name__ == "__main__":
    main()
