#!/usr/bin/env python3

import argparse
import base64
import hashlib
import html
import io
import os
import random
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import imagehash
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError
from PIL import Image, ImageDraw, ImageFilter


MODEL = "gpt-image-2.5-sunburst"
TARGET = 100
DATABASE = Path("/var/lib/little-sounds/little-sounds.sqlite3")
PRIVATE_ROOT = Path("/root/stickers/catalog")
PUBLIC_ROOT = Path("/var/www/little-sounds/sticker-images")
STATUS_ROOT = Path("/var/www/little-sounds/sticker-generator")
LEGACY_PRIVATE = Path("/root/stickers/openai")

THEMES = {
    "bluey": {
        "label": "Bluey",
        "subjects": ["Bluey", "Bingo", "Bluey and Bingo", "Bandit", "Chilli", "Muffin", "Socks", "Rusty", "Coco and Indy", "the Heeler family"],
    },
    "pj-masks": {
        "label": "PJ Masks",
        "subjects": ["Catboy", "Owlette", "Gekko", "Catboy and Owlette", "Catboy and Gekko", "Owlette and Gekko", "the three PJ Masks heroes", "Catboy with a friendly owl", "Gekko with a friendly lizard", "the PJ Masks team"],
    },
    "super-kitties": {
        "label": "SuperKitties",
        "subjects": ["Ginny", "Sparks", "Buddy", "Bitsy", "Ginny and Bitsy", "Sparks and Buddy", "Ginny and Sparks", "Buddy and Bitsy", "three SuperKitties", "the full SuperKitties team"],
    },
    "paw-patrol": {
        "label": "Paw Patrol",
        "subjects": ["Chase", "Marshall", "Skye", "Rubble", "Rocky", "Zuma", "Everest", "Liberty", "Chase and Marshall", "a joyful Paw Patrol team group"],
    },
    "numberblocks": {
        "label": "Numberblocks",
        "subjects": ["Numberblock One", "Numberblock Two", "Numberblock Three", "Numberblock Four", "Numberblock Five", "Numberblock Six", "Numberblock Seven", "Numberblock Eight", "Numberblock Nine", "Numberblock Ten"],
    },
    "alphablocks": {
        "label": "Alphablocks",
        "subjects": [f"Alphablock {letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
    },
    "colourblocks": {
        "label": "Colourblocks",
        "subjects": [
            "Colourblock Red", "Colourblock Orange", "Colourblock Yellow", "Colourblock Green",
            "Colourblock Blue", "Colourblock Purple", "Colourblock Pink", "Colourblock Brown",
            "Colourblock Black and Colourblock White", "a joyful rainbow group of Colourblocks",
        ],
    },
}

ALPHABLOCK_EXTRAS = [
    "Alphablocks A, B and C playing together",
    "Alphablocks D, E and F dancing together",
    "Alphablocks G, H and I sharing a high-five",
    "Alphablocks J, K and L jumping together",
    "Alphablocks M, N and O celebrating together",
    "Alphablocks P, Q and R in a friendly group",
    "Alphablocks S, T and U posing together",
    "Alphablocks V, W and X racing together",
    "Alphablocks Y and Z celebrating together",
    "the vowel Alphablocks A, E, I, O and U in one compact group",
    "Alphablocks A and Z as cheerful best friends",
    "Alphablocks B and P bouncing a colourful ball",
    "Alphablocks C and K wearing party hats",
    "Alphablocks D and T playing a tiny drum",
    "Alphablocks F and V flying like superheroes",
    "Alphablocks G and J doing a joyful dance",
    "Alphablocks H and R waving together",
    "Alphablocks L and Y leaping through the air",
    "Alphablocks M and N sharing a friendly hug",
    "Alphablocks Q and X discovering a treasure star",
    "Alphablocks S and Z making a superhero landing",
    "a compact mixed Alphablocks celebration group from across A to Z",
]

ACTIONS = [
    "doing a joyful star jump",
    "racing forward in an energetic action pose",
    "dancing with a huge cheerful smile",
    "waving proudly after helping a friend",
    "making a playful superhero landing",
    "celebrating with both arms or paws raised",
    "balancing in a funny one-foot pose",
    "giving an enthusiastic thumbs-up or paw-up",
    "spinning through the air in a dynamic pose",
    "sharing a happy high-five when more than one character is present",
]

PROPS = [
    "gold stars and tiny rainbow arcs",
    "a striped ball and curling motion lines",
    "colourful balloons and floating confetti",
    "a toy rocket and little space sparkles",
    "a flower, butterflies and small hearts",
    "a treasure map and jewel-shaped doodles",
    "music notes and a tiny toy drum",
    "a friendly cloud and sunshine doodles",
    "building blocks and bright zigzag marks",
    "a celebration rosette with streamers but no written text",
]

COMPOSITIONS = [
    "front three-quarter view with a bouncy rounded silhouette",
    "slightly low camera angle with a bold triangular silhouette",
    "side-facing leap with a sweeping curved silhouette",
    "close friendly pose with the full body still visible",
    "symmetrical hero pose with a strong compact silhouette",
    "diagonal action pose with clearly separated arms and legs",
    "gentle overhead angle with a playful circular composition",
    "wide mid-air pose with a lively star-shaped silhouette",
    "kneeling or sitting pose with an expressive friendly face",
    "grouped pyramid composition with every face fully visible",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_database():
    connection = sqlite3.connect(DATABASE, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 60000")
    return connection


def ensure_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_stickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            serial INTEGER NOT NULL,
            image_path TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0, 1)),
            staged INTEGER NOT NULL DEFAULT 1 CHECK(staged IN (0, 1)),
            created_at TEXT NOT NULL,
            retired_at TEXT,
            sha256 TEXT NOT NULL UNIQUE,
            phash TEXT,
            dhash TEXT,
            colorhash TEXT,
            prompt TEXT,
            UNIQUE(category, serial)
        );
        CREATE INDEX IF NOT EXISTS catalog_stickers_category_active
            ON catalog_stickers(category, active, serial);
        CREATE TABLE IF NOT EXISTS sticker_history (
            category TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            phash TEXT,
            dhash TEXT,
            colorhash TEXT,
            prompt TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY(category, sha256)
        );
        CREATE TABLE IF NOT EXISTS catalog_rewards (
            profile TEXT NOT NULL,
            position INTEGER NOT NULL,
            sticker_id INTEGER NOT NULL,
            activity TEXT NOT NULL,
            cycle INTEGER NOT NULL,
            earned_at TEXT NOT NULL,
            PRIMARY KEY(profile, position),
            UNIQUE(profile, sticker_id),
            FOREIGN KEY(sticker_id) REFERENCES catalog_stickers(id)
        );
        INSERT OR IGNORE INTO sticker_history(category, sha256, phash, dhash, colorhash, prompt, created_at)
        SELECT category, sha256, phash, dhash, colorhash, prompt, created_at FROM catalog_stickers;
        """
    )
    connection.commit()


def concept_for(serial, retry):
    index = serial - 1
    generation = index // 100
    within_generation = index % 100
    subject_index = within_generation % 10
    action_index = (within_generation // 10) % 10
    prop_index = (subject_index * 3 + action_index * 7 + generation) % 10
    composition_index = (subject_index * 7 + action_index * 3 + generation * 3) % 10
    if retry:
        action_index = (action_index + retry * 3) % 10
        prop_index = (prop_index + retry * 7) % 10
        composition_index = (composition_index + retry * 3) % 10
    return subject_index, action_index, prop_index, composition_index


def make_prompt(category, serial, retry):
    details = THEMES[category]
    subject_index, action_index, prop_index, composition_index = concept_for(serial, retry)
    if category == "alphablocks":
        slot = ((serial - 1) % TARGET) + 1
        if slot <= 78:
            letter = chr(ord("A") + ((slot - 1) % 26))
            round_number = ((slot - 1) // 26) + 1
            subject = f"Alphablock {letter} alone, design round {round_number} of 3 for the letter {letter}"
        else:
            subject = ALPHABLOCK_EXTRAS[slot - 79]
    else:
        subject = details["subjects"][subject_index]
    action = ACTIONS[action_index]
    prop = PROPS[prop_index]
    composition = COMPOSITIONS[composition_index]
    if category == "numberblocks":
        symbols = "Keep the essential numeral on every Numberblocks character clear and mathematically correct. Include no other letters, words or numbers."
    elif category == "alphablocks":
        symbols = "Keep the essential capital letter on every Alphablocks character clear and correct. Include no other letters, words or numbers."
    else:
        symbols = "Include no words, letters, numbers or logos."
    alternate = ""
    if retry:
        alternate = f" Alternate attempt {retry + 1}: radically change the pose, silhouette, expression, camera angle and decorations from any earlier result."
    return (
        f"Create exactly one premium die-cut children's reward sticker featuring {subject} {action}, decorated only with {prop}. "
        f"Make the character faithfully recognisable as part of {details['label']}. Use {composition}. "
        "Polished friendly 3D CGI cartoon, joyful preschool energy, soft detailed fur or fabric, vivid clean colours, studio-quality lighting, full body visible. "
        "Make a compact standalone sticker with a thick smooth white vinyl cut-line. Transparent background outside the cut-line. Exactly one sticker design in the image, "
        "including when several characters form one group. No sticker sheet, panels, scene, scenery, rectangular background, black background, checkerboard, watermark or interface. "
        f"No cropped heads or limbs. {symbols} This design must be materially different in subject, action and silhouette from other stickers in the collection.{alternate}"
    )


def normalise_sticker(raw_bytes):
    image = Image.open(io.BytesIO(raw_bytes))
    image.seek(0)
    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] > 245:
        image = image.copy()
        for corner in ((0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)):
            ImageDraw.floodfill(image, corner, (0, 0, 0, 0), thresh=34)
    bounds = image.getbbox()
    if not bounds:
        raise ValueError("The generated image was empty.")
    subject = image.crop(bounds)
    subject.thumbnail((570, 570), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    x = (640 - subject.width) // 2
    y = (640 - subject.height) // 2
    subject_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    subject_layer.alpha_composite(subject, (x, y))
    mask = subject_layer.getchannel("A")
    outline = mask.filter(ImageFilter.MaxFilter(17))
    shadow = outline.filter(ImageFilter.GaussianBlur(9))
    shadow_layer = Image.new("RGBA", canvas.size, (29, 38, 66, 0))
    shadow_layer.putalpha(shadow.point(lambda value: round(value * 0.23)))
    canvas.alpha_composite(shadow_layer, (0, 7))
    white = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    white.putalpha(outline)
    canvas.alpha_composite(white)
    canvas.alpha_composite(subject_layer)
    return canvas


def flattened(image):
    result = Image.new("RGB", image.size, "white")
    result.paste(image, mask=image.getchannel("A"))
    return result.resize((256, 256), Image.Resampling.LANCZOS)


def fingerprints(image):
    base = flattened(image)
    return str(imagehash.phash(base)), str(imagehash.dhash(base)), str(imagehash.colorhash(base))


def image_sha(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return hashlib.sha256(buffer.getvalue()).hexdigest(), buffer.getvalue()


def hash_distance(value, other):
    if not value or not other:
        return 999
    return imagehash.hex_to_hash(value) - imagehash.hex_to_hash(other)


def too_similar(existing_rows, sha256, phash, dhash, colorhash):
    for row in existing_rows:
        if row["sha256"] == sha256:
            return True
        p_distance = hash_distance(phash, row["phash"])
        d_distance = hash_distance(dhash, row["dhash"])
        same_colour_signature = bool(colorhash and colorhash == row["colorhash"])
        if p_distance <= 5 or d_distance <= 4 or (p_distance <= 9 and d_distance <= 8 and same_colour_signature):
            return True
    return False


def next_serial(connection, category):
    return int(connection.execute(
        "SELECT COALESCE(MAX(serial), 0) + 1 FROM catalog_stickers WHERE category = ?", (category,)
    ).fetchone()[0])


def save_sticker(connection, category, serial, image, prompt, active=0, staged=1):
    private_directory = PRIVATE_ROOT / category
    public_directory = PUBLIC_ROOT / category
    private_directory.mkdir(parents=True, exist_ok=True)
    public_directory.mkdir(parents=True, exist_ok=True)
    private_file = private_directory / f"{serial:04d}.png"
    public_file = public_directory / f"{serial:04d}.webp"
    sha256, png_bytes = image_sha(image)
    phash, dhash, colorhash = fingerprints(image)
    existing = connection.execute(
        """
        SELECT sha256, phash, dhash, colorhash FROM catalog_stickers WHERE category = ?
        UNION
        SELECT sha256, phash, dhash, colorhash FROM sticker_history WHERE category = ?
        """,
        (category, category),
    ).fetchall()
    if too_similar(existing, sha256, phash, dhash, colorhash):
        raise ValueError("The result was too similar to an existing design.")
    private_file.write_bytes(png_bytes)
    image.save(public_file, "WEBP", quality=78, method=5)
    connection.execute(
        """
        INSERT INTO catalog_stickers(category, serial, image_path, active, staged, created_at,
                                     sha256, phash, dhash, colorhash, prompt)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (category, serial, f"/sticker-images/{category}/{serial:04d}.webp", active, staged,
         utc_now(), sha256, phash, dhash, colorhash, prompt),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO sticker_history(category, sha256, phash, dhash, colorhash, prompt, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (category, sha256, phash, dhash, colorhash, prompt, utc_now()),
    )
    connection.commit()


def import_legacy(connection):
    if not LEGACY_PRIVATE.is_dir():
        return 0
    imported = 0
    for category in THEMES:
        source_directory = LEGACY_PRIVATE / category
        if not source_directory.is_dir():
            continue
        for source in sorted(source_directory.glob("*.png")):
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            if connection.execute("SELECT 1 FROM catalog_stickers WHERE sha256 = ?", (source_sha,)).fetchone():
                continue
            serial = next_serial(connection, category)
            try:
                image = Image.open(source).convert("RGBA")
                if image.size != (640, 640):
                    buffer = io.BytesIO()
                    image.save(buffer, "PNG")
                    image = normalise_sticker(buffer.getvalue())
                active_count = int(connection.execute(
                    "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND active = 1", (category,)
                ).fetchone()[0])
                save_sticker(connection, category, serial, image, "Imported from the successful 10-sticker trial.", active=int(active_count < TARGET), staged=0)
                imported += 1
                print(f"Imported existing {THEMES[category]['label']} sticker as #{serial}", flush=True)
            except ValueError as error:
                print(f"Skipped legacy {source.name}: {error}", flush=True)
    return imported


def generate_image(client, prompt):
    response = client.images.generate(
        model=MODEL,
        prompt=prompt,
        size="1024x1024",
        quality="low",
        background="transparent",
        output_format="png",
    )
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("OpenAI returned no image data.")
    return base64.b64decode(response.data[0].b64_json)


def request_image(client, prompt, label, serial):
    last_error = None
    for api_attempt in range(6):
        try:
            return generate_image(client, prompt)
        except (RateLimitError, APITimeoutError, APIConnectionError) as error:
            last_error = error
            delay = min(75, 10 * (api_attempt + 1)) + random.uniform(0, 3)
            print(f"Network/rate wait for {label} #{serial}: {delay:.0f}s", flush=True)
            time.sleep(delay)
        except APIStatusError as error:
            last_error = error
            if error.status_code == 429 or error.status_code >= 500:
                delay = min(75, 10 * (api_attempt + 1)) + random.uniform(0, 3)
                print(f"API wait for {label} #{serial}: {delay:.0f}s", flush=True)
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(str(last_error) if last_error else "Image request failed.")


def inventory(connection, category):
    active = int(connection.execute(
        "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND active = 1", (category,)
    ).fetchone()[0])
    used_active = int(connection.execute(
        """
        SELECT COUNT(DISTINCT s.id) FROM catalog_stickers s
        JOIN catalog_rewards r ON r.sticker_id = s.id
        WHERE s.category = ? AND s.active = 1
        """, (category,)
    ).fetchone()[0])
    staged = int(connection.execute(
        "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND staged = 1", (category,)
    ).fetchone()[0])
    return active, used_active, staged


def publish_category(connection, category, needed):
    connection.execute("BEGIN IMMEDIATE")
    used_ids = [row[0] for row in connection.execute(
        """
        SELECT DISTINCT s.id FROM catalog_stickers s
        JOIN catalog_rewards r ON r.sticker_id = s.id
        WHERE s.category = ? AND s.active = 1
        """, (category,)
    )]
    if used_ids:
        placeholders = ",".join("?" for _ in used_ids)
        connection.execute(
            f"UPDATE catalog_stickers SET active = 0, retired_at = ? WHERE id IN ({placeholders})",
            (utc_now(), *used_ids),
        )
    staged_ids = [row[0] for row in connection.execute(
        "SELECT id FROM catalog_stickers WHERE category = ? AND staged = 1 ORDER BY serial LIMIT ?",
        (category, needed),
    )]
    if len(staged_ids) != needed:
        connection.rollback()
        raise RuntimeError("Not enough completed replacement stickers to publish safely.")
    if staged_ids:
        placeholders = ",".join("?" for _ in staged_ids)
        connection.execute(
            f"UPDATE catalog_stickers SET active = 1, staged = 0 WHERE id IN ({placeholders})", staged_ids
        )
    final_active = int(connection.execute(
        "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND active = 1", (category,)
    ).fetchone()[0])
    if final_active != TARGET:
        connection.rollback()
        raise RuntimeError(f"Safety check failed: expected {TARGET} active stickers, found {final_active}.")
    connection.commit()


def write_status(connection, running=True, message=""):
    sections = []
    for category, details in THEMES.items():
        active, used_active, staged = inventory(connection, category)
        history = int(connection.execute(
            "SELECT COUNT(*) FROM sticker_history WHERE category = ?", (category,)
        ).fetchone()[0])
        images = connection.execute(
            "SELECT serial, image_path, active, staged FROM catalog_stickers WHERE category = ? ORDER BY serial DESC LIMIT 20",
            (category,),
        ).fetchall()
        cards = "".join(
            f'<article><span>#{row["serial"]}</span><img src="{html.escape(row["image_path"])}" alt="" loading="lazy"><small>{"staged" if row["staged"] else "active" if row["active"] else "retired"}</small></article>'
            for row in reversed(images)
        )
        sections.append(
            f'<section><h2>{html.escape(details["label"])} <small>{active}/{TARGET} active · {used_active} due for refill · {staged} staged · {history} ever made</small></h2><div class="grid">{cards}</div></section>'
        )
    state = "Generator running" if running else "Generator finished"
    page = f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><meta http-equiv="refresh" content="30"><title>Sticker Generator</title><style>*{{box-sizing:border-box}}body{{margin:0;padding:24px clamp(14px,4vw,44px);font-family:ui-rounded,"Arial Rounded MT Bold",system-ui,sans-serif;color:#243557;background:linear-gradient(155deg,#64cdf5,#f4e9ff 50%,#fff0a6)}}header,main{{max-width:1100px;margin:auto}}header{{text-align:center}}h1{{font-size:clamp(2rem,7vw,4.4rem);margin:0;text-shadow:0 4px #fff}}header p{{font-weight:900}}section{{margin:30px 0;padding:18px;border:5px solid #fff;border-radius:28px;background:#ffffffb8;box-shadow:0 9px 24px #40547b24}}h2{{margin:0 0 14px}}h2 small{{color:#7258e8;font-size:.7em}}.grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}}article{{position:relative;aspect-ratio:1;border-radius:20px;background:#fff;box-shadow:0 6px 14px #35476a20;display:grid;place-items:center;overflow:hidden}}article span{{position:absolute;z-index:2;top:7px;left:7px;padding:5px 8px;border-radius:99px;background:#ffe15c;font-weight:1000}}article small{{position:absolute;right:7px;bottom:7px;padding:4px 7px;border-radius:99px;background:#fff;font-weight:900}}img{{width:100%;height:100%;object-fit:contain}}@media(max-width:760px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}</style></head><body><header><h1>✨ {state}</h1><p>{html.escape(message)}</p><p>This page refreshes every 30 seconds.</p><p><a href="/">◀ Back to Little Sounds</a></p></header><main>{''.join(sections)}</main></body></html>'''
    STATUS_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_ROOT / "index.tmp"
    temporary.write_text(page)
    temporary.replace(STATUS_ROOT / "index.html")


def replenish_category(connection, client, category):
    details = THEMES[category]
    active, used_active, staged = inventory(connection, category)
    needed = max(0, TARGET - (active - used_active))
    to_generate = max(0, needed - staged)
    print(f"{details['label']}: {active} active, {used_active} used, {staged} staged, {to_generate} new needed.", flush=True)
    successful = 0
    consecutive_failures = 0
    while successful < to_generate and consecutive_failures < 24:
        serial = next_serial(connection, category)
        saved = False
        for design_attempt in range(8):
            prompt = make_prompt(category, serial, design_attempt)
            try:
                raw = request_image(client, prompt, details["label"], serial)
                image = normalise_sticker(raw)
                save_sticker(connection, category, serial, image, prompt)
                successful += 1
                saved = True
                consecutive_failures = 0
                print(f"{details['label']} #{serial}: saved ({successful}/{to_generate} new)", flush=True)
                write_status(connection, True, f"Creating {details['label']} stickers…")
                break
            except APIStatusError as error:
                print(f"{details['label']} #{serial} attempt {design_attempt + 1} rejected by the API: {error}", flush=True)
            except Exception as error:
                print(f"{details['label']} #{serial} attempt {design_attempt + 1}: {error}", flush=True)
        if not saved:
            consecutive_failures += 1
            print(f"Could not complete {details['label']} #{serial}; trying a new variation.", flush=True)
    active, used_active, staged = inventory(connection, category)
    needed = max(0, TARGET - (active - used_active))
    if staged < needed:
        raise RuntimeError(f"{details['label']} needs {needed} replacements but only {staged} are ready. Run generate again later.")
    publish_category(connection, category, needed)
    print(f"{details['label']}: shared book restored to {TARGET} active stickers.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Fill and replenish the Little Sounds shared sticker books.")
    parser.add_argument("--target", type=int, default=TARGET)
    args = parser.parse_args()
    if args.target != TARGET:
        raise ValueError(f"This site is configured for exactly {TARGET} active stickers per theme.")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    PUBLIC_ROOT.mkdir(parents=True, exist_ok=True)
    STATUS_ROOT.mkdir(parents=True, exist_ok=True)
    connection = connect_database()
    ensure_schema(connection)
    imported = import_legacy(connection)
    if imported:
        print(f"Kept {imported} successful stickers from the earlier trial.", flush=True)
    client = OpenAI(api_key=api_key, timeout=180.0, max_retries=0)
    try:
        client.models.list()
    except Exception as error:
        raise RuntimeError(f"The OpenAI API key could not be verified: {error}") from error
    write_status(connection, True, "Checking the shared 100-sticker catalogues…")
    errors = []
    for category in THEMES:
        try:
            replenish_category(connection, client, category)
        except Exception as error:
            errors.append(f"{THEMES[category]['label']}: {error}")
            print(f"FAILED {THEMES[category]['label']}: {error}", flush=True)
    message = "All seven shared sticker books are ready." if not errors else "Some themes need another generate run: " + " | ".join(errors)
    write_status(connection, False, message)
    connection.close()
    if errors:
        raise RuntimeError(message)
    print(message, flush=True)
    print("Run backup-stickers once generation finishes to save this sticker pack for future VPS resets.", flush=True)


if __name__ == "__main__":
    main()
