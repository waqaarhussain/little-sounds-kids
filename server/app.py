import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request


DATA_DIRECTORY = Path(os.environ.get("LITTLE_SOUNDS_DATA", "/var/lib/little-sounds"))
DATABASE = DATA_DIRECTORY / "little-sounds.sqlite3"
STICKER_DIRECTORY = Path(os.environ.get("LITTLE_SOUNDS_STICKERS", "/var/www/little-sounds/sticker-images"))
SWITCH_PIN = os.environ.get("LITTLE_SOUNDS_PIN", "0000")
COOKIE_NAME = "little_sounds_device"
PARENT_PROFILE = os.environ.get("LITTLE_SOUNDS_PARENT", "Parent").strip() or "Parent"
CHILD_PROFILES = (
    os.environ.get("LITTLE_SOUNDS_CHILD_1", "Child 1").strip() or "Child 1",
    os.environ.get("LITTLE_SOUNDS_CHILD_2", "Child 2").strip() or "Child 2",
)
PROFILES = (PARENT_PROFILE, *CHILD_PROFILES)
CATEGORIES = {
    "smiley-faces": "Smiley Faces",
    "well-done": "Well Done",
    "youre-a-star": "You're a Star",
}
ACTIVITY_ITEMS = {
    "phonics": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "letters": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "numbers": tuple(str(number) for number in range(1, 10)),
    "shapes": ("circle", "square", "triangle", "diamond", "pentagon", "heart", "star", "hexagon", "oval"),
}

app = Flask(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
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
            CREATE TABLE IF NOT EXISTS shared_stickers (
                position INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                sticker_number INTEGER NOT NULL CHECK(sticker_number BETWEEN 1 AND 100),
                chosen_at TEXT NOT NULL,
                chosen_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rewards (
                profile TEXT NOT NULL,
                position INTEGER NOT NULL,
                earned_at TEXT NOT NULL,
                PRIMARY KEY(profile, position),
                FOREIGN KEY(position) REFERENCES shared_stickers(position)
            );
            CREATE TABLE IF NOT EXISTS activity_progress (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                item TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity, item)
            );
            CREATE TABLE IF NOT EXISTS activity_completions (
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY(profile, activity, cycle)
            );
            CREATE TABLE IF NOT EXISTS pending_rewards (
                token TEXT PRIMARY KEY,
                profile TEXT NOT NULL,
                activity TEXT NOT NULL,
                cycle INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(profile, activity, cycle)
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
    category = row["category"]
    number = int(row["sticker_number"])
    return {
        "position": int(row["position"]),
        "category": category,
        "category_label": CATEGORIES[category],
        "sticker_number": number,
        "image": f"/sticker-images/{category}/{number:03d}.webp",
    }


def available_categories():
    return {
        category: label
        for category, label in CATEGORIES.items()
        if (STICKER_DIRECTORY / category / "001.webp").is_file()
    }


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


@app.get("/api/sticker-categories")
def sticker_categories():
    available = available_categories()
    return jsonify(
        {
            "categories": [
                {
                    "id": category,
                    "label": label,
                    "image": f"/sticker-images/{category}/001.webp",
                }
                for category, label in available.items()
            ]
        }
    )


@app.post("/api/rewards/claim")
def claim_reward():
    body = json_body()
    requested_category = str(body.get("category", ""))
    reward_token = str(body.get("reward_token", ""))
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        profile = device["profile"]
        if profile == PARENT_PROFILE:
            return jsonify({"parent_preview": True, "message": "Parent testing does not change the children's sticker sequence."})

        pending = connection.execute(
            "SELECT token FROM pending_rewards WHERE token = ? AND profile = ?",
            (reward_token, profile),
        ).fetchone()
        if pending is None:
            return jsonify({"error": "Finish a complete exercise before choosing a sticker."}), 403

        connection.execute("BEGIN IMMEDIATE")
        position = int(
            connection.execute(
                "SELECT COUNT(*) FROM rewards WHERE profile = ?", (profile,)
            ).fetchone()[0]
        ) + 1
        shared = connection.execute(
            "SELECT position, category, sticker_number FROM shared_stickers WHERE position = ?",
            (position,),
        ).fetchone()

        if shared is None:
            available = available_categories()
            if requested_category not in available:
                return jsonify({"needs_choice": True, "position": position})
            used_numbers = {
                int(row[0])
                for row in connection.execute(
                    "SELECT sticker_number FROM shared_stickers WHERE category = ?", (requested_category,)
                )
            }
            available = [number for number in range(1, 101) if number not in used_numbers]
            if not available:
                available = list(range(1, 101))
            sticker_number = secrets.choice(available)
            connection.execute(
                "INSERT INTO shared_stickers(position, category, sticker_number, chosen_at, chosen_by) VALUES (?, ?, ?, ?, ?)",
                (position, requested_category, sticker_number, now(), profile),
            )
            shared = connection.execute(
                "SELECT position, category, sticker_number FROM shared_stickers WHERE position = ?",
                (position,),
            ).fetchone()

        connection.execute(
            "INSERT OR IGNORE INTO rewards(profile, position, earned_at) VALUES (?, ?, ?)",
            (profile, position, now()),
        )
        connection.execute(
            "DELETE FROM pending_rewards WHERE token = ? AND profile = ?",
            (reward_token, profile),
        )
        payload = sticker_payload(shared)
        payload.update({"needs_choice": False, "profile": profile})
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
        rows = connection.execute(
            """
            SELECT s.position, s.category, s.sticker_number, r.earned_at
            FROM rewards r
            JOIN shared_stickers s ON s.position = r.position
            WHERE r.profile = ?
            ORDER BY s.position
            """,
            (profile,),
        ).fetchall()
        return jsonify(
            {
                "profile": profile,
                "stickers": [dict(sticker_payload(row), earned_at=row["earned_at"]) for row in rows],
            }
        )


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
        if profile == PARENT_PROFILE:
            return jsonify({"activity": activity, "completed_items": [], "count": 0, "total": len(ACTIVITY_ITEMS[activity]), "parent_preview": True})
        completed = [
            row[0]
            for row in connection.execute(
                "SELECT item FROM activity_progress WHERE profile = ? AND activity = ? ORDER BY completed_at",
                (profile, activity),
            )
        ]
        return jsonify({"activity": activity, "completed_items": completed, "count": len(completed), "total": len(ACTIVITY_ITEMS[activity])})


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
        if profile == PARENT_PROFILE:
            return jsonify({"parent_preview": True, "activity": activity, "item": item, "count": 0, "total": total, "exercise_completed": False})

        connection.execute("BEGIN IMMEDIATE")
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
        exercise_completed = count == total
        cycle = None
        reward_token = None
        if exercise_completed:
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
            connection.execute(
                "DELETE FROM activity_progress WHERE profile = ? AND activity = ?",
                (profile, activity),
            )
            reward_token = secrets.token_urlsafe(24)
            connection.execute(
                "INSERT INTO pending_rewards(token, profile, activity, cycle, created_at) VALUES (?, ?, ?, ?, ?)",
                (reward_token, profile, activity, cycle, now()),
            )
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
                "completed_items": [] if exercise_completed else [
                    row[0]
                    for row in connection.execute(
                        "SELECT item FROM activity_progress WHERE profile = ? AND activity = ? ORDER BY completed_at",
                        (profile, activity),
                    )
                ],
            }
        )


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


initialise_database()
