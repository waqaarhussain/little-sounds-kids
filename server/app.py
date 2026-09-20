import colorsys
import hashlib
import json
import math
import os
import random
import secrets
import sqlite3
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from PIL import Image, ImageFilter


DATA_DIRECTORY = Path(os.environ.get("LITTLE_SOUNDS_DATA", "/var/lib/little-sounds"))
DATABASE = DATA_DIRECTORY / "little-sounds.sqlite3"
SITE_ROOT = Path(os.environ.get("LITTLE_SOUNDS_SITE", "/var/www/little-sounds"))
STICKER_ROOT = Path(os.environ.get("LITTLE_SOUNDS_STICKERS", str(SITE_ROOT / "sticker-images")))
SWITCH_PIN = os.environ.get("LITTLE_SOUNDS_PIN", "0000")
COOKIE_NAME = os.environ.get("LITTLE_SOUNDS_COOKIE_NAME", "little_sounds_device")
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
ACTIVITY_THEMES = ("bluey", "pj-masks", "super-kitties", "paw-patrol")
SINGLE_CHARACTER_SLOTS = {
    "bluey": {0, 1, 3, 4, 5, 6, 7},
    "pj-masks": {0, 1, 2},
    "super-kitties": {0, 1, 2, 3},
    "paw-patrol": set(range(8)),
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
    "finish-the-pattern": tuple(f"round-{number}" for number in range(1, 21)),
    "odd-one-out": tuple(f"round-{number}" for number in range(1, 21)),
    "more-or-less": tuple(f"round-{number}" for number in range(1, 21)),
    "letter-hunt": tuple(f"round-{number}" for number in range(1, 21)),
    "number-hunt": tuple(f"round-{number}" for number in range(1, 21)),
    "dot-to-dot": ("puzzle",),
    "character-maze": ("puzzle",),
    "character-jigsaw": ("puzzle",),
    **NUMBER_LEVELS,
}
RANDOM_ACTIVITIES = {
    "count-and-choose", "match-the-pairs", "sort-colours-shapes",
    "finish-the-pattern", "odd-one-out", "more-or-less",
    "letter-hunt", "number-hunt",
    "dot-to-dot", "character-maze", "character-jigsaw",
}
PUZZLE_ACTIVITIES = {"dot-to-dot", "character-maze", "character-jigsaw"}
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
GAME_SYMBOLS = (
    "🍎", "⭐", "🐞", "🐠", "🦋", "🍓", "🌼", "🚗",
    "🐸", "🍪", "🎈", "🦆", "🐝", "💛", "🍊", "🚀",
    "🌙", "☀️", "🍀", "⚽", "🎀", "🍇", "🧸", "🎨",
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
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
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


def touch_activity_progress(connection, profile, activity):
    timestamp = datetime.now(timezone.utc)
    connection.execute(
        """
        INSERT INTO activity_sessions(profile, activity, last_active_at)
        VALUES (?, ?, ?)
        ON CONFLICT(profile, activity) DO UPDATE SET last_active_at = excluded.last_active_at
        """,
        (profile, activity, timestamp.isoformat(timespec="seconds")),
    )
    return False


def shuffled_choices(answer, values, size=3):
    choices = [answer]
    others = [value for value in values if value != answer]
    random.shuffle(others)
    choices.extend(others[: max(0, size - 1)])
    random.shuffle(choices)
    return choices


def recent_activity_art(connection, profile, activity, limit=8):
    rows = connection.execute(
        """
        SELECT plan_json FROM activity_variants
        WHERE profile = ? AND activity = ?
        ORDER BY attempt DESC LIMIT ?
        """,
        (profile, activity, limit),
    ).fetchall()
    recent_ids = []
    recent_themes = []
    for row in rows:
        try:
            plan = json.loads(row["plan_json"])
            sticker_id = int(plan.get("sticker_id", 0))
            theme = str(plan.get("theme", ""))
            if sticker_id:
                recent_ids.append(sticker_id)
            if theme:
                recent_themes.append(theme)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return recent_ids, recent_themes


def choose_activity_sticker(connection, profile, activity, single_character=False):
    recent_ids, recent_themes = recent_activity_art(connection, profile, activity)
    preferred_themes = [theme for theme in ACTIVITY_THEMES if theme not in recent_themes[:3]]
    if not preferred_themes:
        preferred_themes = list(ACTIVITY_THEMES)
    placeholders = ",".join("?" for _ in preferred_themes)
    rows = connection.execute(
        f"""
        SELECT id, category, serial, image_path
        FROM catalog_stickers
        WHERE active = 1 AND staged = 0 AND category IN ({placeholders})
        ORDER BY RANDOM() LIMIT 80
        """,
        preferred_themes,
    ).fetchall()
    if single_character:
        rows = [
            row for row in rows
            if (int(row["serial"]) - 1) % 10 in SINGLE_CHARACTER_SLOTS.get(row["category"], set())
        ]
    candidates = [row for row in rows if int(row["id"]) not in recent_ids]
    if not candidates:
        candidates = rows
    if not candidates:
        raise RuntimeError("No themed character pictures are ready. Ask a grown-up to run generate-stickers.")
    row = random.choice(candidates)
    return {
        "sticker_id": int(row["id"]),
        "theme": row["category"],
        "theme_label": CATEGORIES[row["category"]],
        "image": row["image_path"],
        "serial": int(row["serial"]),
    }


def sticker_file(image_path):
    prefix = "/sticker-images/"
    if not str(image_path).startswith(prefix):
        raise ValueError("The selected character picture has an invalid path.")
    relative = Path(str(image_path)[len(prefix):])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("The selected character picture has an invalid path.")
    return STICKER_ROOT / relative


def artwork_line_colour(image_path, theme):
    fallbacks = {
        "bluey": "#2864c7",
        "pj-masks": "#244e9b",
        "super-kitties": "#8a3db3",
        "paw-patrol": "#d64045",
    }
    source = sticker_file(image_path)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        image.thumbnail((96, 96), Image.Resampling.LANCZOS)

    buckets = {}
    for red, green, blue, alpha in image.getdata():
        if alpha < 128:
            continue
        _, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
        if saturation < 0.34 or value < 0.2 or value > 0.94:
            continue
        key = tuple(min(255, (channel // 32) * 32 + 16) for channel in (red, green, blue))
        buckets[key] = buckets.get(key, 0.0) + 1.0 + saturation * 2.0
    if not buckets:
        return fallbacks.get(theme, "#5a47c7")

    red, green, blue = max(buckets, key=buckets.get)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    if luminance > 0.62:
        factor = 0.62 / luminance
        red, green, blue = (round(channel * factor) for channel in (red, green, blue))
    elif luminance < 0.2:
        red, green, blue = (round(channel + (255 - channel) * 0.18) for channel in (red, green, blue))
    return f"#{red:02x}{green:02x}{blue:02x}"


def outline_dots(image_path, count):
    source = sticker_file(image_path)
    with Image.open(source) as opened:
        image = opened.convert("RGBA")

    def sample_polyline(points, sample_count, closed=False, offset=0.0):
        line_segments = []
        total_length = 0.0
        pair_count = len(points) if closed else len(points) - 1
        for index in range(pair_count):
            start = points[index]
            end = points[(index + 1) % len(points)]
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            if length <= 0:
                continue
            line_segments.append((total_length, total_length + length, start, end))
            total_length += length
        if not line_segments or sample_count < 2:
            return []
        points = []
        segment_index = 0
        for index in range(sample_count):
            if closed:
                target = total_length * (index + offset) / sample_count
            else:
                target = total_length * index / (sample_count - 1)
            while segment_index + 1 < len(line_segments) and target > line_segments[segment_index][1]:
                segment_index += 1
            start_distance, end_distance, start, end = line_segments[segment_index]
            fraction = (target - start_distance) / max(end_distance - start_distance, 0.001)
            points.append((
                round(start[0] + (end[0] - start[0]) * fraction, 1),
                round(start[1] + (end[1] - start[1]) * fraction, 1),
            ))
        return points

    def components(points, minimum=10):
        remaining = set(points)
        groups = []
        while remaining:
            start = remaining.pop()
            component = {start}
            queue = [start]
            while queue:
                x, y = queue.pop()
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        neighbour = (x + dx, y + dy)
                        if neighbour in remaining:
                            remaining.remove(neighbour)
                            component.add(neighbour)
                            queue.append(neighbour)
            if len(component) >= minimum:
                groups.append(component)
        return groups

    analysis_size = 256
    analysis = image.resize((analysis_size, analysis_size), Image.Resampling.LANCZOS)
    analysis_alpha = analysis.getchannel("A")
    smooth = analysis.convert("RGB").filter(ImageFilter.GaussianBlur(0.8))
    alpha_pixels = analysis_alpha.load()
    colour_pixels = smooth.load()

    # Sticker art often includes a white cutout, lightning marks and small props.
    # Remove pale backing, break thin decorative lines, then select the largest
    # substantial colour region nearest the centre. That region is the character.
    colour_mask = Image.new("L", (analysis_size, analysis_size))
    colour_mask_pixels = colour_mask.load()
    for y in range(analysis_size):
        for x in range(analysis_size):
            red, green, blue = colour_pixels[x, y]
            _, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
            if alpha_pixels[x, y] >= 48 and ((saturation >= 0.18 and value <= 0.97) or value < 0.62):
                colour_mask_pixels[x, y] = 255
    opened_mask = colour_mask.filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(7))
    opened_pixels = opened_mask.load()
    subject_components = components(
        (x, y)
        for y in range(analysis_size)
        for x in range(analysis_size)
        if opened_pixels[x, y]
    )
    if not subject_components:
        raise ValueError("The selected character picture has no usable character shape.")

    def subject_score(component):
        centre_x = sum(point[0] for point in component) / len(component)
        centre_y = sum(point[1] for point in component) / len(component)
        distance = math.hypot(centre_x - analysis_size / 2, centre_y - analysis_size / 2)
        centrality = 1 + max(0, 1 - distance / (analysis_size / math.sqrt(2)))
        return len(component) * centrality

    subject_seed = max(subject_components, key=subject_score)
    seed_mask = Image.new("L", (analysis_size, analysis_size))
    seed_pixels = seed_mask.load()
    for x, y in subject_seed:
        seed_pixels[x, y] = 255
    subject_mask = seed_mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(3))
    subject_pixels = subject_mask.load()
    subject_bounds = subject_mask.getbbox()
    if not subject_bounds:
        raise ValueError("The selected character picture has no usable character outline.")

    # Trace the mask boundary in true walking order. Sorting boundary points by
    # angle causes concave arms, legs and ears to collapse into number clusters.
    edges = set()
    for y in range(analysis_size):
        for x in range(analysis_size):
            if not subject_pixels[x, y]:
                continue
            if y == 0 or not subject_pixels[x, y - 1]:
                edges.add(((x, y), (x + 1, y)))
            if x == analysis_size - 1 or not subject_pixels[x + 1, y]:
                edges.add(((x + 1, y), (x + 1, y + 1)))
            if y == analysis_size - 1 or not subject_pixels[x, y + 1]:
                edges.add(((x + 1, y + 1), (x, y + 1)))
            if x == 0 or not subject_pixels[x - 1, y]:
                edges.add(((x, y + 1), (x, y)))
    if not edges:
        raise ValueError("The selected character picture has no usable character edge.")

    edge_starts = {}
    for edge in edges:
        edge_starts.setdefault(edge[0], []).append(edge[1])
    contours = []
    unused_edges = set(edges)
    while unused_edges:
        start, finish = min(unused_edges)
        contour = [start]
        unused_edges.remove((start, finish))
        current = finish
        while current != start and len(contour) <= len(edges):
            contour.append(current)
            candidates = [end for end in edge_starts.get(current, ()) if (current, end) in unused_edges]
            if not candidates:
                break
            following = candidates[0]
            unused_edges.remove((current, following))
            current = following
        if current == start and len(contour) >= 12:
            contours.append(contour)
    if not contours:
        raise ValueError("The selected character outline could not be traced.")

    def contour_area(contour):
        return abs(sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(contour, contour[1:] + contour[:1])
        )) / 2

    character_contour = max(contours, key=contour_area)
    outline = [
        (
            195 + x / analysis_size * 610,
            45 + y / analysis_size * 610,
        )
        for x, y in character_contour
    ]
    if len(outline) < 35:
        raise ValueError("The selected character outline is too small for a dot-to-dot puzzle.")

    magnitudes = {}
    edge_margin = 5
    for y in range(edge_margin, analysis_size - edge_margin):
        for x in range(edge_margin, analysis_size - edge_margin):
            if not subject_pixels[x, y]:
                continue
            if min(
                subject_pixels[x - edge_margin, y], subject_pixels[x + edge_margin, y],
                subject_pixels[x, y - edge_margin], subject_pixels[x, y + edge_margin],
            ) == 0:
                continue
            colour = colour_pixels[x, y]
            magnitude = max(
                sum(abs(colour[channel] - colour_pixels[nx, ny][channel]) for channel in range(3))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
            )
            if magnitude:
                magnitudes[(x, y)] = magnitude

    feature_paths = []
    if magnitudes:
        ordered_magnitudes = sorted(magnitudes.values())
        threshold = max(55, ordered_magnitudes[int((len(ordered_magnitudes) - 1) * 0.88)])
        edge_components = components(point for point, magnitude in magnitudes.items() if magnitude >= threshold)

        def farthest(component, start):
            queue = deque([start])
            distance = {start: 0}
            previous = {}
            while queue:
                x, y = queue.popleft()
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        neighbour = (x + dx, y + dy)
                        if neighbour in component and neighbour not in distance:
                            distance[neighbour] = distance[(x, y)] + 1
                            previous[neighbour] = (x, y)
                            queue.append(neighbour)
            finish = max(distance, key=distance.get)
            return finish, previous, distance[finish]

        for component in edge_components:
            first, _, _ = farthest(component, min(component))
            last, previous, graph_length = farthest(component, first)
            if graph_length < 16:
                continue
            path = [last]
            while path[-1] != first:
                path.append(previous[path[-1]])
            path.reverse()
            canvas_path = [
                (195 + x / (analysis_size - 1) * 610, 45 + y / (analysis_size - 1) * 610)
                for x, y in path
            ]
            path_length = sum(
                math.hypot(canvas_path[index][0] - canvas_path[index - 1][0], canvas_path[index][1] - canvas_path[index - 1][1])
                for index in range(1, len(canvas_path))
            )
            if path_length >= 45:
                feature_paths.append((path_length, canvas_path))

    selected_features = []
    feature_centres = []
    for path_length, path in sorted(feature_paths, reverse=True):
        centre = (
            sum(point[0] for point in path) / len(path),
            sum(point[1] for point in path) / len(path),
        )
        if any(math.hypot(centre[0] - old[0], centre[1] - old[1]) < 65 for old in feature_centres):
            continue
        selected_features.append((path_length, path))
        feature_centres.append(centre)
        if len(selected_features) == 8:
            break

    target = max(35, min(60, count))
    outer_choices = [sample_polyline(outline, target, closed=True, offset=offset / 20) for offset in range(20)]
    outer_points = max(
        outer_choices,
        key=lambda points: min(
            math.hypot(first[0] - second[0], first[1] - second[1])
            for index, first in enumerate(points)
            for second in points[index + 1:]
        ),
    )

    dots = [
        {
            "number": index + 1,
            "x": x,
            "y": y,
            "segment": 0,
            "break_before": index == 0,
        }
        for index, (x, y) in enumerate(outer_points)
    ]
    guides = []
    for path_length, path in selected_features:
        sampled = sample_polyline(path, min(28, max(6, round(path_length / 15))))
        if len(sampled) >= 4:
            guides.append([[x, y] for x, y in sampled])
    return dots, guides


def generate_maze(columns, rows):
    north, east, south, west = 1, 2, 4, 8
    walls = [north | east | south | west for _ in range(columns * rows)]
    visited = {0}
    stack = [0]
    directions = ((0, -1, north, south), (1, 0, east, west), (0, 1, south, north), (-1, 0, west, east))
    while stack:
        cell = stack[-1]
        x, y = cell % columns, cell // columns
        choices = []
        for dx, dy, wall, opposite in directions:
            nx, ny = x + dx, y + dy
            neighbour = ny * columns + nx
            if 0 <= nx < columns and 0 <= ny < rows and neighbour not in visited:
                choices.append((neighbour, wall, opposite))
        if not choices:
            stack.pop()
            continue
        neighbour, wall, opposite = random.choice(choices)
        walls[cell] &= ~wall
        walls[neighbour] &= ~opposite
        visited.add(neighbour)
        stack.append(neighbour)

    distances = {0: 0}
    queue = [0]
    while queue:
        cell = queue.pop(0)
        x, y = cell % columns, cell // columns
        for dx, dy, wall, _ in directions:
            nx, ny = x + dx, y + dy
            neighbour = ny * columns + nx
            if 0 <= nx < columns and 0 <= ny < rows and not (walls[cell] & wall) and neighbour not in distances:
                distances[neighbour] = distances[cell] + 1
                queue.append(neighbour)
    finish = max(distances, key=distances.get)
    return walls, finish


def build_themed_activity_plan(connection, profile, activity, attempt):
    artwork = choose_activity_sticker(connection, profile, activity, single_character=activity != "character-jigsaw")
    if activity == "dot-to-dot":
        dots, guides = outline_dots(artwork["image"], random.randint(45, 60))
        plan = {
            **artwork,
            "layout_version": 5,
            "line_colour": artwork_line_colour(artwork["image"], artwork["theme"]),
            "dot_count": len(dots),
            "dots": dots,
            "guides": guides,
        }
    elif activity == "character-maze":
        if attempt <= 2:
            columns, rows, difficulty = 11, 9, "Easy"
        elif attempt <= 5:
            columns, rows, difficulty = 15, 11, "Medium"
        else:
            columns, rows, difficulty = 19, 13, "Hard"
        walls, finish = generate_maze(columns, rows)
        plan = {**artwork, "columns": columns, "rows": rows, "walls": walls, "start": 0, "finish": finish, "difficulty": difficulty}
    elif activity == "character-jigsaw":
        if attempt <= 2:
            columns, rows = 4, 3
        elif attempt <= 5:
            columns, rows = 5, 4
        else:
            columns, rows = 6, 4
        order = list(range(columns * rows))
        random.shuffle(order)
        plan = {**artwork, "columns": columns, "rows": rows, "piece_count": len(order), "order": order}
    else:
        raise ValueError("That themed activity is not valid.")
    signature_source = {key: value for key, value in plan.items() if key != "theme_label"}
    canonical = json.dumps(signature_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return plan, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_activity_plan(activity, connection=None, profile="", attempt=1):
    if activity in {"dot-to-dot", "character-maze", "character-jigsaw"}:
        if connection is None or not profile:
            raise ValueError("The themed activity needs a profile and catalogue.")
        return build_themed_activity_plan(connection, profile, activity, attempt)
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
    elif activity == "finish-the-pattern":
        kinds = ("ABC", "AABC", "ABBC", "ABCC", "ABAC", "ABCB")
        rounds = []
        used = set()
        while len(rounds) < 20:
            kind = random.choice(kinds)
            symbols = random.sample(GAME_SYMBOLS, 3)
            unit = {
                "ABC": [symbols[0], symbols[1], symbols[2]],
                "AABC": [symbols[0], symbols[0], symbols[1], symbols[2]],
                "ABBC": [symbols[0], symbols[1], symbols[1], symbols[2]],
                "ABCC": [symbols[0], symbols[1], symbols[2], symbols[2]],
                "ABAC": [symbols[0], symbols[1], symbols[0], symbols[2]],
                "ABCB": [symbols[0], symbols[1], symbols[2], symbols[1]],
            }[kind]
            repeated = unit * 4
            sequence = repeated[:6]
            answer = repeated[6]
            key = (kind, tuple(symbols), answer)
            if key in used:
                continue
            used.add(key)
            choices = list(symbols)
            random.shuffle(choices)
            index = len(rounds) + 1
            rounds.append({"item": f"round-{index}", "sequence": sequence, "answer": answer, "choices": choices})
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "odd-one-out":
        rounds = []
        used = set()
        while len(rounds) < 20:
            same, odd = random.sample(GAME_SYMBOLS, 2)
            position = random.randrange(4)
            key = (same, odd, position)
            if key in used:
                continue
            used.add(key)
            pictures = [same] * 4
            pictures[position] = odd
            index = len(rounds) + 1
            rounds.append({"item": f"round-{index}", "pictures": pictures, "answer": position})
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "more-or-less":
        rounds = []
        used = set()
        while len(rounds) < 20:
            left_count, right_count = random.sample(range(1, 11), 2)
            left_icon, right_icon = random.sample(GAME_SYMBOLS, 2)
            key = (left_count, right_count, left_icon, right_icon)
            if key in used:
                continue
            used.add(key)
            index = len(rounds) + 1
            rounds.append({
                "item": f"round-{index}",
                "left_count": left_count,
                "right_count": right_count,
                "left_icon": left_icon,
                "right_icon": right_icon,
                "answer": "left" if left_count > right_count else "right",
            })
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "letter-hunt":
        rounds = []
        for index, letter in enumerate(random.sample(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), 20), 1):
            choices = shuffled_choices(letter.lower(), list("abcdefghijklmnopqrstuvwxyz"), 4)
            rounds.append({"item": f"round-{index}", "target": letter, "answer": letter.lower(), "choices": choices})
        plan = {"rounds": rounds}
        signature_source = plan
    elif activity == "number-hunt":
        rounds = []
        for index, number in enumerate(random.sample(range(1, 101), 20), 1):
            choices = shuffled_choices(number, list(range(1, 101)), 4)
            rounds.append({"item": f"round-{index}", "target": number, "answer": number, "choices": choices})
        plan = {"rounds": rounds}
        signature_source = plan
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
        existing_plan = json.loads(row["plan_json"])
        if activity != "dot-to-dot" or int(existing_plan.get("layout_version", 0)) >= 5:
            return int(row["attempt"]), existing_plan
        connection.execute(
            "UPDATE activity_variants SET completed = 1 WHERE profile = ? AND activity = ? AND attempt = ?",
            (profile, activity, int(row["attempt"])),
        )
    attempt = int(connection.execute(
        "SELECT COALESCE(MAX(attempt), 0) + 1 FROM activity_variants WHERE profile = ? AND activity = ?",
        (profile, activity),
    ).fetchone()[0])
    for _ in range(100):
        plan, signature = build_activity_plan(activity, connection, profile, attempt)
        if connection.execute(
            "SELECT 1 FROM activity_variants WHERE activity = ? AND signature = ? LIMIT 1",
            (activity, signature),
        ).fetchone():
            continue
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
                return jsonify({"error": "No stickers are available. Ask a grown-up to run generate-stickers."}), 409
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


@app.post("/api/progress/reset")
def reset_progress():
    body = json_body()
    requested = body.get("activities", [])
    if isinstance(requested, str):
        requested = [requested]
    activities = sorted({str(activity) for activity in requested if str(activity) in ACTIVITY_ITEMS})
    if not activities:
        return jsonify({"reset": []})
    with database() as connection:
        device = current_device(connection)
        if not device:
            return jsonify({"error": "Choose a profile first."}), 401
        profile = device["profile"]
        connection.execute("BEGIN IMMEDIATE")
        for activity in activities:
            connection.execute(
                "DELETE FROM activity_progress WHERE profile = ? AND activity = ?",
                (profile, activity),
            )
            connection.execute(
                "DELETE FROM activity_sessions WHERE profile = ? AND activity = ?",
                (profile, activity),
            )
            if activity in RANDOM_ACTIVITIES:
                connection.execute(
                    "UPDATE activity_variants SET completed = 1 WHERE profile = ? AND activity = ? AND completed = 0",
                    (profile, activity),
                )
        return jsonify({"profile": profile, "reset": activities})


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
        variant_attempt = None
        if activity in PUZZLE_ACTIVITIES:
            try:
                variant_attempt = int(body.get("attempt", 0))
            except (TypeError, ValueError):
                variant_attempt = 0
            variant = connection.execute(
                """
                SELECT completed FROM activity_variants
                WHERE profile = ? AND activity = ? AND attempt = ?
                """,
                (profile, activity, variant_attempt),
            ).fetchone()
            if not variant:
                return jsonify({"error": "This puzzle is no longer active. Reload for a fresh one."}), 409
            if int(variant["completed"]):
                return jsonify({
                    "activity": activity,
                    "item": item,
                    "new_item": False,
                    "already_completed": True,
                    "count": total,
                    "total": total,
                    "exercise_completed": False,
                    "cycle": None,
                    "reward_token": None,
                    "completed_items": [],
                    "parent_preview": profile == PARENT_PROFILE,
                    "expired": False,
                })
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
                if variant_attempt is None:
                    connection.execute(
                        """
                        UPDATE activity_variants SET completed = 1
                        WHERE profile = ? AND activity = ? AND completed = 0
                        """,
                        (profile, activity),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE activity_variants SET completed = 1
                        WHERE profile = ? AND activity = ? AND attempt = ? AND completed = 0
                        """,
                        (profile, activity, variant_attempt),
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
