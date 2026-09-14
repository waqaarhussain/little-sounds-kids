import hashlib
import json
import os
import random
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, request


DATA_DIRECTORY = Path(os.environ.get("LITTLE_SOUNDS_DATA", "/var/lib/little-sounds"))
DATABASE = DATA_DIRECTORY / "little-sounds.sqlite3"
SWITCH_PIN = os.environ.get("LITTLE_SOUNDS_PIN", "0000")
COOKIE_NAME = "little_sounds_device"
PARENT_PROFILE = os.environ.get("LITTLE_SOUNDS_PARENT", "Parent").strip() or "Parent"
CHILD_PROFILES = (
    os.environ.get("LITTLE_SOUNDS_CHILD_1", "Child 1").strip() or "Child 1",
    os.environ.get("LITTLE_SOUNDS_CHILD_2", "Child 2").strip() or "Child 2",
)
PROFILES = (PARENT_PROFILE, *CHILD_PROFILES)
TARGET_STICKERS = 100
CATEGORIES = {
    "bluey": "Bluey",
    "pj-masks": "PJ Masks",
    "super-kitties": "SuperKitties",
    "paw-patrol": "Paw Patrol",
    "numberblocks": "Numberblocks",
    "alphablocks": "Alphablocks",
    "colourblocks": "Colourblocks",
}
NUMBER_LEVELS = {
    f"numbers-{start}-{start + 9}": tuple(str(number) for number in range(start, start + 10))
    for start in range(1, 100, 10)
}
TRACING_SHAPES = (
    "circle", "square", "triangle", "rectangle", "diamond", "pentagon", "hexagon",
    "octagon", "oval", "semicircle", "crescent", "heart", "star", "cross", "arrow",
)
ACTIVITY_ITEMS = {
    "phonics": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "letters": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "shapes": TRACING_SHAPES,
    "count-and-choose": tuple(f"round-{number}" for number in range(1, 21)),
    "match-the-pairs": tuple(f"round-{number}" for number in range(1, 7)),
    "sort-colours-shapes": tuple(f"round-{number}" for number in range(1, 21)),
    **NUMBER_LEVELS,
}
RANDOM_ACTIVITIES = {"count-and-choose", "match-the-pairs", "sort-colours-shapes"}
COUNTING_ICONS = (
    ("apples", "🍎"), ("stars", "⭐"), ("ladybirds", "🐞"), ("fish", "🐠"),
    ("butterflies", "🦋"), ("strawberries", "🍓"), ("flowers", "🌼"), ("cars", "🚗"),
    ("frogs", "🐸"), ("biscuits", "🍪"), ("balloons", "🎈"), ("ducks", "🦆"),
    ("bees", "🐝"), ("hearts", "💛"), ("oranges", "🍊"), ("rockets", "🚀"),
)
GAME_COLOURS = (
    ("red", "#f24f67"), ("blue", "#3a7eea"), ("yellow", "#ffd52e"),
    ("green", "#35bd73"), ("orange", "#ff922e"), ("purple", "#8659df"),
    ("pink", "#f56ab1"), ("turquoise", "#22bdb7"),
)
GAME_SHAPES = (
    "circle", "square", "triangle", "rectangle", "diamond", "pentagon",
    "hexagon", "oval", "heart", "star",
)
MATCHING_ANIMALS = (
    ("cat", "🐱"), ("dog", "🐶"), ("frog", "🐸"), ("fish", "🐠"),
    ("lion", "🦁"), ("rabbit", "🐰"), ("fox", "🦊"), ("panda", "🐼"),
    ("koala", "🐨"), ("tiger", "🐯"), ("monkey", "🐵"), ("cow", "🐮"),
    ("pig", "🐷"), ("mouse", "🐭"), ("hamster", "🐹"), ("bear", "🐻"),
    ("chicken", "🐔"), ("penguin", "🐧"), ("owl", "🦉"), ("duck", "🦆"),
    ("octopus", "🐙"), ("whale", "🐳"), ("snail", "🐌"), ("butterfly", "🦋"),
)

app = Flask(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialise_database() -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                token TEXT PRIMARY KEY,
                profile TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity_progress (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                item TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity, item)
            );
            CREATE TABLE IF NOT EXISTS activity_sessions (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity)
            );
            CREATE TABLE IF NOT EXISTS activity_completions (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity, cycle)
            );
            CREATE TABLE IF NOT EXISTS activity_variants (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                signature TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0, 1)),
                created_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity, attempt),
                UNIQUE(profile, activity, signature)
            );
            CREATE TABLE IF NOT EXISTS pending_rewards (
                token TEXT PRIMARY KEY,
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(profile, activity, cycle)
            );
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
            INSERT OR IGNORE INTO sticker_history(category, sha256, phash, dhash, colorhash, prompt, created_at)
            SELECT category, sha256, phash, dhash, colorhash, prompt, created_at FROM catalog_stickers;
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
            """
        )


def current_device(connection):
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return None
    return connection.execute(
        "SELECT token, profile FROM devices WHERE token = ?", (token,)
    ).fetchone()


def json_body():
    return request.get_json(silent=True) or {}


def sticker_payload(row):
    return {
        "id": int(row["id"]),
        "serial": int(row["serial"]),
        "category": row["category"],
        "category_label": CATEGORIES[row["category"]],
        "image": row["image_path"],
    }


def pending_reward(connection, token):
    if not token:
        return None
    return connection.execute(
        "SELECT token, profile, activity, cycle FROM pending_rewards WHERE token = ?",
        (token,),
    ).fetchone()


INACTIVITY_LIMIT = timedelta(minutes=10)


def touch_activity_progress(connection, profile, activity):
    timestamp = datetime.now(timezone.utc)
    session = connection.execute(
        "SELECT last_active_at FROM activity_sessions WHERE profile = ? AND activity = ?",
        (profile, activity),
    ).fetchone()
    expired = False
    if session:
        try:
            last_active = datetime.fromisoformat(session["last_active_at"])
            expired = timestamp - last_active >= INACTIVITY_LIMIT
        except (TypeError, ValueError):
            expired = True
    if expired:
        connection.execute(
            "DELETE FROM activity_progress WHERE profile = ? AND activity = ?",
            (profile, activity),
        )
        if activity in RANDOM_ACTIVITIES:
            connection.execute(
                "DELETE FROM activity_variants WHERE profile = ? AND activity = ? AND completed = 0",
                (profile, activity),
            )
    connection.execute(
        """
        INSERT INTO activity_sessions(profile, activity, last_active_at)
        VALUES (?, ?, ?)
        ON CONFLICT(profile, activity) DO UPDATE SET last_active_at = excluded.last_active_at
        """,
        (profile, activity, timestamp.isoformat(timespec="seconds")),
    )
    return expired


def shuffled_choices(answer, values, size=3):
    choices = [answer]
    others = [value for value in values if value != answer]
    random.shuffle(others)
    choices.extend(others[: max(0, size - 1)])
    random.shuffle(choices)
    return choices


def build_activity_plan(activity):
    if activity == "count-and-choose":
        combinations = [(count, name, icon) for count in range(1, 11) for name, icon in COUNTING_ICONS]
        selected = random.sample(combinations, 20)
        rounds = []
        for index, (count, name, icon) in enumerate(selected, 1):
            rounds.append({
                "item": f"round-{index}",
                "count": count,
                "name": name,
                "icon": icon,
                "choices": shuffled_choices(count, list(range(1, 11))),
            })
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "sort-colours-shapes":
        combinations = [(shape, colour_name, colour_hex) for shape in GAME_SHAPES for colour_name, colour_hex in GAME_COLOURS]
        selected = random.sample(combinations, 20)
        question_types = ["colour"] * 10 + ["shape"] * 10
        random.shuffle(question_types)
        rounds = []
        colour_names = [name for name, _ in GAME_COLOURS]
        for index, ((shape, colour_name, colour_hex), question_type) in enumerate(zip(selected, question_types), 1):
            answer = colour_name if question_type == "colour" else shape
            values = colour_names if question_type == "colour" else list(GAME_SHAPES)
            rounds.append({
                "item": f"round-{index}",
                "shape": shape,
                "colour": colour_name,
                "colour_hex": colour_hex,
                "question": question_type,
                "answer": answer,
                "choices": shuffled_choices(answer, values),
            })
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "match-the-pairs":
        animals = random.sample(MATCHING_ANIMALS, 6)
        deck = [
            {"round": f"round-{index}", "animal": animal, "icon": icon, "copy": copy}
            for index, (animal, icon) in enumerate(animals, 1)
            for copy in ("a", "b")
        ]
        random.shuffle(deck)
        plan = {"pairs": [{"round": f"round-{index}", "animal": animal, "icon": icon} for index, (animal, icon) in enumerate(animals, 1)], "deck": deck}
        signature_source = sorted(animal for animal, _ in animals)
    else:
        raise ValueError("That activity does not use a generated plan.")
    canonical = json.dumps(signature_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return plan, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_or_create_activity_variant(connection, profile, activity):
    row = connection.execute(
        """
        SELECT attempt, signature, plan_json
        FROM activity_variants
        WHERE profile = ? AND activity = ? AND completed = 0
        ORDER BY attempt DESC LIMIT 1
        """,
        (profile, activity),
    ).fetchone()
    if row:
        return int(row["attempt"]), json.loads(row["plan_json"])
    attempt = int(connection.execute(
        "SELECT COALESCE(MAX(attempt), 0) + 1 FROM activity_variants WHERE profile = ? AND activity = ?",
        (profile, activity),
    ).fetchone()[0])
    for _ in range(100):
        plan, signature = build_activity_plan(activity)
        try:
            connection.execute(
                """
                INSERT INTO activity_variants(profile, activity, attempt, signature, plan_json, completed, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (profile, activity, attempt, signature, json.dumps(plan, ensure_ascii=False, separators=(",", ":")), now()),
            )
            return attempt, plan
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("Could not create a fresh activity. Please try again.")


@app.get("/api/activity/variant")
def activity_variant():
    activity = request.args.get("activity", "")
    if activity not in RANDOM_ACTIVITIES:
        return jsonify({"error": "Choose a valid game activity."}), 400
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        connection.execute("BEGIN IMMEDIATE")
        attempt, plan = get_or_create_activity_variant(connection, device["profile"], activity)
        return jsonify({"activity": activity, "attempt": attempt, "plan": plan})


def available_category_rows(connection, profile):
    rows = []
    for category, label in CATEGORIES.items():
        count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM catalog_stickers s
                LEFT JOIN catalog_rewards r ON r.sticker_id = s.id AND r.profile = ?
                WHERE s.category = ? AND s.active = 1 AND r.sticker_id IS NULL
                """,
                (profile, category),
            ).fetchone()[0]
        )
        cover = connection.execute(
            """
            SELECT s.image_path
            FROM catalog_stickers s
            LEFT JOIN catalog_rewards r ON r.sticker_id = s.id AND r.profile = ?
            WHERE s.category = ? AND s.active = 1 AND r.sticker_id IS NULL
            ORDER BY s.serial LIMIT 1
            """,
            (profile, category),
        ).fetchone()
        if cover:
            rows.append(
                {
                    "id": category,
                    "label": label,
                    "image": cover["image_path"],
                    "available": count,
                    "target": TARGET_STICKERS,
                }
            )
    return rows


def set_device_cookie(response, token):
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=60 * 60 * 24 * 365 * 5,
        httponly=True,
        samesite="Lax",
        secure=False,
    )
    return response


@app.get("/api/profile")
def profile_status():
    with database() as connection:
        device = current_device(connection)
        return jsonify(
            {
                "profile": device["profile"] if device else None,
                "profiles": PROFILES,
                "parent_profile": PARENT_PROFILE,
                "child_profiles": CHILD_PROFILES,
                "needs_selection": device is None,
            }
        )


@app.post("/api/profile/select")
def select_profile():
    profile = str(json_body().get("profile", ""))
    if profile not in PROFILES:
        return jsonify({"error": "Choose a valid profile."}), 400
    with database() as connection:
        if current_device(connection):
            return jsonify({"error": "Use Switch Profile and enter the PIN."}), 403
        token = secrets.token_urlsafe(32)
        timestamp = now()
        connection.execute(
            "INSERT INTO devices(token, profile, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (token, profile, timestamp, timestamp),
        )
    return set_device_cookie(jsonify({"profile": profile}), token)


@app.post("/api/profile/switch")
def switch_profile():
    body = json_body()
    profile = str(body.get("profile", ""))
    pin = str(body.get("pin", ""))
    if profile not in PROFILES:
        return jsonify({"error": "Choose a valid profile."}), 400
    if not secrets.compare_digest(pin, SWITCH_PIN):
        return jsonify({"error": "That PIN is not correct."}), 403
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "This device has no remembered profile."}), 409
        connection.execute(
            "UPDATE devices SET profile = ?, updated_at = ? WHERE token = ?",
            (profile, now(), device["token"]),
        )
    return jsonify({"profile": profile})


@app.post("/api/rewards/bonus")
def create_bonus_reward():
    body = json_body()
    target_profile = str(body.get("profile", ""))
    pin = str(body.get("pin", ""))
    if target_profile not in CHILD_PROFILES:
        return jsonify({"error": "Choose a child profile."}), 400
    if not secrets.compare_digest(pin, SWITCH_PIN):
        return jsonify({"error": "That PIN is not correct."}), 403
    with database() as connection:
        if not current_device(connection):
            return jsonify({"error": "Choose a profile first."}), 401
        connection.execute("BEGIN IMMEDIATE")
        cycle = int(
            connection.execute(
                "SELECT COALESCE(MAX(cycle), 0) + 1 FROM catalog_rewards WHERE profile = ? AND activity = 'good-behaviour'",
                (target_profile,),
            ).fetchone()[0]
        )
        connection.execute(
            "DELETE FROM pending_rewards WHERE profile = ? AND activity = 'good-behaviour'",
            (target_profile,),
        )
        token = secrets.token_urlsafe(24)
        connection.execute(
            "INSERT INTO pending_rewards(token, profile, activity, cycle, created_at) VALUES (?, ?, 'good-behaviour', ?, ?)",
            (token, target_profile, cycle, now()),
        )
        return jsonify({"reward_token": token, "profile": target_profile})


@app.get("/api/sticker-categories")
def sticker_categories():
    reward_token = request.args.get("reward_token", "")
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        pending = pending_reward(connection, reward_token) if reward_token else None
        profile = pending["profile"] if pending else device["profile"]
        if profile == PARENT_PROFILE:
            profile = CHILD_PROFILES[0]
        return jsonify({"profile": profile, "categories": available_category_rows(connection, profile)})


@app.get("/api/sticker-book")
def sticker_book():
    category = request.args.get("category", "")
    reward_token = request.args.get("reward_token", "")
    if category not in CATEGORIES:
        return jsonify({"error": "Choose a valid sticker theme."}), 400
    with database() as connection:
        if not current_device(connection):
            return jsonify({"error": "Choose a profile first."}), 401
        pending = pending_reward(connection, reward_token)
        if not pending:
            return jsonify({"error": "This sticker reward has expired."}), 403
        profile = pending["profile"]
        rows = connection.execute(
            """
            SELECT s.id, s.category, s.serial, s.image_path
            FROM catalog_stickers s
            LEFT JOIN catalog_rewards r ON r.sticker_id = s.id AND r.profile = ?
            WHERE s.category = ? AND s.active = 1 AND s.staged = 0 AND r.sticker_id IS NULL
            ORDER BY s.serial
            """,
            (profile, category),
        ).fetchall()
        seed_text = f"{reward_token}|{profile}|{category}"
        rng = random.Random(hashlib.sha256(seed_text.encode("utf-8")).hexdigest())
        chosen = []
        if category == "alphablocks":
            by_letter = {letter: [] for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
            extras = []
            for row in rows:
                serial = int(row["serial"])
                slot = ((serial - 1) % TARGET_STICKERS) + 1
                if slot <= 78:
                    by_letter["ABCDEFGHIJKLMNOPQRSTUVWXYZ"[(slot - 1) % 26]].append(row)
                else:
                    extras.append(row)
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                options = by_letter[letter]
                if options:
                    chosen.append((letter, rng.choice(options)))
            rng.shuffle(extras)
            missing = 26 - len(chosen)
            chosen.extend((None, row) for row in extras[:missing])
        else:
            shuffled = list(rows)
            rng.shuffle(shuffled)
            chosen = [(None, row) for row in shuffled[:20]]
        slots = []
        for letter, row in chosen:
            item = sticker_payload(row)
            item.update({"available": True, "peeled": False, "retired": False})
            if letter:
                item["letter"] = letter
            slots.append(item)
        return jsonify(
            {
                "profile": profile,
                "category": category,
                "category_label": CATEGORIES[category],
                "slots": slots,
                "available": len(rows),
                "shown": len(slots),
                "target": TARGET_STICKERS,
            }
        )

@app.get("/api/all-stickers")
def all_stickers():
    with database() as connection:
        categories = []
        for category, label in CATEGORIES.items():
            rows = connection.execute(
                """
                SELECT id, category, serial, image_path, active, staged
                FROM catalog_stickers
                WHERE category = ?
                ORDER BY serial
                """,
                (category,),
            ).fetchall()
            stickers = []
            for row in rows:
                item = sticker_payload(row)
                item["status"] = "staged" if row["staged"] else "active" if row["active"] else "retired"
                stickers.append(item)
            categories.append(
                {
                    "id": category,
                    "label": label,
                    "count": len(stickers),
                    "stickers": stickers,
                }
            )
        return jsonify(
            {
                "categories": categories,
                "total": sum(category["count"] for category in categories),
                "refreshed_at": now(),
            }
        )


@app.post("/api/rewards/claim")
def claim_reward():
    body = json_body()
    reward_token = str(body.get("reward_token", ""))
    requested_sticker = body.get("sticker_id")
    with database() as connection:
        if not current_device(connection):
            return jsonify({"error": "Choose a profile first."}), 401
        pending = pending_reward(connection, reward_token)
        if not pending:
            return jsonify({"error": "Finish an exercise or use Give Sticker first."}), 403
        if requested_sticker is None:
            categories = available_category_rows(connection, pending["profile"])
            if not categories:
                return jsonify({"error": "No stickers are available. Ask a grown-up to run generate."}), 409
            return jsonify(
                {
                    "needs_choice": True,
                    "profile": pending["profile"],
                    "categories": categories,
                }
            )
        try:
            sticker_id = int(requested_sticker)
        except (TypeError, ValueError):
            return jsonify({"error": "Choose a valid sticker."}), 400

        connection.execute("BEGIN IMMEDIATE")
        pending = pending_reward(connection, reward_token)
        if not pending:
            return jsonify({"error": "That reward was already collected."}), 409
        profile = pending["profile"]
        sticker = connection.execute(
            """
            SELECT s.id, s.category, s.serial, s.image_path
            FROM catalog_stickers s
            LEFT JOIN catalog_rewards r ON r.sticker_id = s.id AND r.profile = ?
            WHERE s.id = ? AND s.active = 1 AND s.staged = 0 AND r.sticker_id IS NULL
            """,
            (profile, sticker_id),
        ).fetchone()
        if not sticker:
            return jsonify({"error": "That sticker has already been peeled. Choose another one."}), 409
        position = int(
            connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM catalog_rewards WHERE profile = ?",
                (profile,),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO catalog_rewards(profile, position, sticker_id, activity, cycle, earned_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (profile, position, sticker_id, pending["activity"], int(pending["cycle"]), now()),
        )
        connection.execute("DELETE FROM pending_rewards WHERE token = ?", (reward_token,))
        payload = sticker_payload(sticker)
        payload.update(
            {
                "needs_choice": False,
                "profile": profile,
                "position": position,
                "activity": pending["activity"],
            }
        )
        return jsonify(payload)


@app.get("/api/rewards")
def rewards():
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        requested_profile = request.args.get("profile", "")
        profile = device["profile"]
        if requested_profile in CHILD_PROFILES and profile == PARENT_PROFILE:
            profile = requested_profile
        if profile == PARENT_PROFILE:
            profile = CHILD_PROFILES[0]
        rows = connection.execute(
            """
            SELECT s.id, s.category, s.serial, s.image_path,
                   r.position, r.activity, r.earned_at
            FROM catalog_rewards r
            JOIN catalog_stickers s ON s.id = r.sticker_id
            WHERE r.profile = ?
            ORDER BY r.position
            """,
            (profile,),
        ).fetchall()
        stickers = []
        for row in rows:
            item = sticker_payload(row)
            item.update(
                {
                    "position": int(row["position"]),
                    "activity": row["activity"],
                    "earned_at": row["earned_at"],
                }
            )
            stickers.append(item)
        return jsonify({"profile": profile, "stickers": stickers})


@app.get("/api/progress")
def activity_progress():
    activity = request.args.get("activity", "")
    if activity not in ACTIVITY_ITEMS:
        return jsonify({"error": "Choose a valid activity."}), 400
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        profile = device["profile"]
        expired = touch_activity_progress(connection, profile, activity)
        completed = [
            row[0]
            for row in connection.execute(
                "SELECT item FROM activity_progress WHERE profile = ? AND activity = ? ORDER BY completed_at",
                (profile, activity),
            )
        ]
        return jsonify(
            {
                "activity": activity,
                "completed_items": completed,
                "count": len(completed),
                "total": len(ACTIVITY_ITEMS[activity]),
                "parent_preview": profile == PARENT_PROFILE,
                "expired": expired,
            }
        )


@app.post("/api/progress/touch")
def touch_progress():
    activity = str(json_body().get("activity", ""))
    if activity not in ACTIVITY_ITEMS:
        return jsonify({"error": "Choose a valid activity."}), 400
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        profile = device["profile"]
        expired = touch_activity_progress(connection, profile, activity)
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM activity_progress WHERE profile = ? AND activity = ?",
                (profile, activity),
            ).fetchone()[0]
        )
        return jsonify({"activity": activity, "expired": expired, "count": count})


@app.post("/api/progress/complete")
def complete_activity_item():
    body = json_body()
    activity = str(body.get("activity", ""))
    item = str(body.get("item", ""))
    if activity not in ACTIVITY_ITEMS or item not in ACTIVITY_ITEMS[activity]:
        return jsonify({"error": "That activity item is not valid."}), 400
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        profile = device["profile"]
        total = len(ACTIVITY_ITEMS[activity])
        connection.execute("BEGIN IMMEDIATE")
        expired = touch_activity_progress(connection, profile, activity)
        cursor = connection.execute(
            "INSERT OR IGNORE INTO activity_progress(profile, activity, item, completed_at) VALUES (?, ?, ?, ?)",
            (profile, activity, item, now()),
        )
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM activity_progress WHERE profile = ? AND activity = ?",
                (profile, activity),
            ).fetchone()[0]
        )
        exercise_completed = count == total and cursor.rowcount == 1
        cycle = None
        reward_token = None
        if exercise_completed:
            if activity in RANDOM_ACTIVITIES:
                connection.execute(
                    """
                    UPDATE activity_variants SET completed = 1
                    WHERE profile = ? AND activity = ? AND completed = 0
                    """,
                    (profile, activity),
                )
            cycle = int(
                connection.execute(
                    "SELECT COALESCE(MAX(cycle), 0) + 1 FROM activity_completions WHERE profile = ? AND activity = ?",
                    (profile, activity),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO activity_completions(profile, activity, cycle, completed_at) VALUES (?, ?, ?, ?)",
                (profile, activity, cycle, now()),
            )
            if profile != PARENT_PROFILE:
                connection.execute(
                    "DELETE FROM activity_progress WHERE profile = ? AND activity = ?",
                    (profile, activity),
                )
                connection.execute(
                    "DELETE FROM pending_rewards WHERE profile = ? AND activity = ?",
                    (profile, activity),
                )
                reward_token = secrets.token_urlsafe(24)
                connection.execute(
                    "INSERT INTO pending_rewards(token, profile, activity, cycle, created_at) VALUES (?, ?, ?, ?, ?)",
                    (reward_token, profile, activity, cycle, now()),
                )
        completed_items = []
        if not exercise_completed or profile == PARENT_PROFILE:
            completed_items = [
                row[0]
                for row in connection.execute(
                    "SELECT item FROM activity_progress WHERE profile = ? AND activity = ? ORDER BY completed_at",
                    (profile, activity),
                )
            ]
        return jsonify(
            {
                "activity": activity,
                "item": item,
                "new_item": cursor.rowcount == 1,
                "already_completed": cursor.rowcount != 1,
                "count": count,
                "total": total,
                "exercise_completed": exercise_completed,
                "cycle": cycle,
                "reward_token": reward_token,
                "completed_items": completed_items,
                "parent_preview": profile == PARENT_PROFILE,
                "expired": expired,
            }
        )


@app.get("/api/health")
def health():
    with database() as connection:
        counts = {
            category: int(
                connection.execute(
                    "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND active = 1",
                    (category,),
                ).fetchone()[0]
            )
            for category in CATEGORIES
        }
    return jsonify({"ok": True, "active_stickers": counts, "target": TARGET_STICKERS})


initialise_database()
