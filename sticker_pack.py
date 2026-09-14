#!/usr/bin/env python3

import argparse
import hashlib
import http.client
import io
import json
import os
import sqlite3
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


THEMES = ("bluey", "pj-masks", "super-kitties", "paw-patrol", "numberblocks", "alphablocks", "colourblocks")
TARGET = 100
DATABASE = Path("/var/lib/little-sounds/little-sounds.sqlite3")
PRIVATE_ROOT = Path("/root/stickers/catalog")
SITE_ROOT = Path("/var/www/little-sounds")
PUBLIC_ROOT = SITE_ROOT / "sticker-images"
DEFAULT_ARCHIVE = Path("/root/stickers/little-sounds-sticker-pack.tar.gz")
DEFAULT_REPOSITORY = "waqaarhussain/little-sounds-kids"
RELEASE_TAG = "sticker-pack"
ASSET_NAME = "little-sounds-sticker-pack.tar.gz"
CONFIG_FILE = Path("/etc/little-sounds.env")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database():
    connection = sqlite3.connect(DATABASE, timeout=60)
    connection.row_factory = sqlite3.Row
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
        """
    )
    connection.commit()


def add_bytes(archive, name, content):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def configured_children():
    values = {}
    if CONFIG_FILE.is_file():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    first = os.environ.get("LITTLE_SOUNDS_CHILD_1") or values.get("LITTLE_SOUNDS_CHILD_1")
    second = os.environ.get("LITTLE_SOUNDS_CHILD_2") or values.get("LITTLE_SOUNDS_CHILD_2")
    if not first or not second:
        raise RuntimeError("Could not read the two configured child profiles from /etc/little-sounds.env.")
    return first, second


def create_pack(destination):
    connection = database()
    ensure_schema(connection)
    children = configured_children()
    profile_slots = {children[0]: "child_1", children[1]: "child_2"}
    active_counts = {
        category: int(connection.execute(
            "SELECT COUNT(*) FROM catalog_stickers WHERE category = ? AND active = 1 AND staged = 0",
            (category,),
        ).fetchone()[0])
        for category in THEMES
    }
    for category, count in active_counts.items():
        if count != TARGET:
            raise RuntimeError(f"{category} has {count} active stickers. Run generate before creating the backup.")

    rows = connection.execute(
        """
        SELECT DISTINCT s.id, s.category, s.serial, s.image_path, s.active, s.staged,
               s.created_at, s.retired_at, s.sha256, s.phash, s.dhash, s.colorhash, s.prompt
        FROM catalog_stickers s
        LEFT JOIN catalog_rewards r ON r.sticker_id = s.id
        WHERE (s.active = 1 AND s.staged = 0) OR r.sticker_id IS NOT NULL
        ORDER BY s.category, s.serial
        """
    ).fetchall()
    items = []
    source_files = []
    exported_hashes = set()
    for row in rows:
        category = row["category"]
        serial = int(row["serial"])
        if category not in THEMES or serial < 1:
            raise RuntimeError("The sticker catalogue contains an invalid category or serial.")
        private_source = PRIVATE_ROOT / category / f"{serial:04d}.png"
        public_source = SITE_ROOT / str(row["image_path"]).lstrip("/")
        if not private_source.is_file() or not public_source.is_file():
            raise FileNotFoundError(f"Sticker files are incomplete for {category} #{serial}.")
        private_bytes = private_source.read_bytes()
        if hashlib.sha256(private_bytes).hexdigest() != row["sha256"]:
            raise RuntimeError(f"Checksum mismatch for {private_source}.")
        private_name = f"private/{category}/{row['sha256']}.png"
        public_name = f"public/{category}/{row['sha256']}.webp"
        source_files.append((private_name, private_source, public_name, public_source))
        exported_hashes.add(row["sha256"])
        items.append(
            {
                "category": category,
                "serial": serial,
                "active": int(row["active"]),
                "staged": int(row["staged"]),
                "created_at": row["created_at"],
                "retired_at": row["retired_at"],
                "sha256": row["sha256"],
                "phash": row["phash"],
                "dhash": row["dhash"],
                "colorhash": row["colorhash"],
                "prompt": row["prompt"],
                "private": private_name,
                "public": public_name,
            }
        )

    rewards = []
    for row in connection.execute(
        """
        SELECT r.profile, r.position, r.activity, r.cycle, s.sha256
        FROM catalog_rewards r
        JOIN catalog_stickers s ON s.id = r.sticker_id
        ORDER BY r.profile, r.position
        """
    ):
        profile_slot = profile_slots.get(row["profile"])
        if not profile_slot:
            continue
        if row["sha256"] not in exported_hashes:
            raise RuntimeError("An earned sticker is missing from the exported sticker set.")
        rewards.append(
            {
                "profile_slot": profile_slot,
                "position": int(row["position"]),
                "sticker_sha256": row["sha256"],
                "activity": row["activity"],
                "cycle": int(row["cycle"]),
            }
        )

    history = [dict(row) for row in connection.execute(
        "SELECT category, sha256, phash, dhash, colorhash, prompt, created_at FROM sticker_history ORDER BY category, created_at, sha256"
    )]
    activity_variants = []
    for row in connection.execute(
        """
        SELECT profile, activity, attempt, signature, plan_json, completed, created_at
        FROM activity_variants
        ORDER BY profile, activity, attempt
        """
    ):
        profile_slot = profile_slots.get(row["profile"])
        if not profile_slot:
            continue
        activity_variants.append(
            {
                "profile_slot": profile_slot,
                "activity": row["activity"],
                "attempt": int(row["attempt"]),
                "signature": row["signature"],
                "plan_json": row["plan_json"],
                "completed": int(row["completed"]),
                "created_at": row["created_at"],
            }
        )
    connection.close()
    manifest = {
        "format": 4,
        "created_at": utc_now(),
        "target_per_theme": TARGET,
        "themes": list(THEMES),
        "stickers": items,
        "history": history,
        "rewards": rewards,
        "activity_variants": activity_variants,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
        add_bytes(archive, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        for private_name, private_source, public_name, public_source in source_files:
            archive.add(private_source, arcname=private_name, recursive=False)
            archive.add(public_source, arcname=public_name, recursive=False)
    temporary.replace(destination)
    print(
        f"Created {destination} with {len(items)} sticker files, {len(rewards)} anonymised album entries, "
        f"{len(activity_variants)} remembered game plans and {len(history)} design fingerprints."
    )
    return destination

def member_bytes(archive, name):
    member = archive.getmember(name)
    if not member.isfile() or member.size > 20 * 1024 * 1024:
        raise RuntimeError(f"Unsafe sticker-pack entry: {name}")
    extracted = archive.extractfile(member)
    if extracted is None:
        raise RuntimeError(f"Could not read {name}")
    return extracted.read()


def restore_pack(source):
    connection = database()
    ensure_schema(connection)
    existing = int(connection.execute("SELECT COUNT(*) FROM catalog_stickers").fetchone()[0])
    if existing:
        print(f"Sticker catalogue already contains {existing} records. Restore skipped.")
        connection.close()
        return False
    with tarfile.open(source, "r:gz") as archive:
        manifest = json.loads(member_bytes(archive, "manifest.json"))
        format_version = int(manifest.get("format", 0))
        if format_version not in (2, 3, 4) or tuple(manifest.get("themes", [])) != THEMES:
            raise RuntimeError("This is not a compatible Little Sounds sticker pack.")
        items = manifest.get("stickers", [])
        if format_version == 2:
            if len(items) != TARGET * len(THEMES):
                raise RuntimeError(f"Sticker pack contains {len(items)} stickers; expected {TARGET * len(THEMES)}.")
            for item in items:
                item.setdefault("active", 1)
                item.setdefault("staged", 0)
                item.setdefault("retired_at", None)
        for category in THEMES:
            active_count = sum(
                1 for item in items
                if item.get("category") == category and int(item.get("active", 0)) == 1 and int(item.get("staged", 0)) == 0
            )
            if active_count != TARGET:
                raise RuntimeError(f"Sticker pack does not contain exactly {TARGET} active {category} stickers.")

        children = configured_children()
        profile_slots = {"child_1": children[0], "child_2": children[1]}
        sha_to_id = {}
        connection.execute("BEGIN IMMEDIATE")
        for item in items:
            category = item["category"]
            serial = int(item["serial"])
            if category not in THEMES or serial < 1:
                raise RuntimeError("Sticker pack contains an invalid category or serial.")
            private_bytes = member_bytes(archive, item["private"])
            public_bytes = member_bytes(archive, item["public"])
            if hashlib.sha256(private_bytes).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Sticker pack checksum failed for {category} #{serial}.")
            private_target = PRIVATE_ROOT / category / f"{serial:04d}.png"
            public_target = PUBLIC_ROOT / category / f"{serial:04d}.webp"
            private_target.parent.mkdir(parents=True, exist_ok=True)
            public_target.parent.mkdir(parents=True, exist_ok=True)
            private_target.write_bytes(private_bytes)
            public_target.write_bytes(public_bytes)
            cursor = connection.execute(
                """
                INSERT INTO catalog_stickers(category, serial, image_path, active, staged, created_at, retired_at,
                                             sha256, phash, dhash, colorhash, prompt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category, serial, f"/sticker-images/{category}/{serial:04d}.webp",
                    int(item.get("active", 1)), int(item.get("staged", 0)), item["created_at"],
                    item.get("retired_at"), item["sha256"], item.get("phash"), item.get("dhash"),
                    item.get("colorhash"), item.get("prompt"),
                ),
            )
            sha_to_id[item["sha256"]] = int(cursor.lastrowid)

        for item in manifest.get("history", []):
            if item.get("category") not in THEMES:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO sticker_history(category, sha256, phash, dhash, colorhash, prompt, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["category"], item["sha256"], item.get("phash"), item.get("dhash"),
                    item.get("colorhash"), item.get("prompt"), item.get("created_at") or utc_now(),
                ),
            )

        restored_rewards = 0
        if format_version >= 3:
            for reward in manifest.get("rewards", []):
                profile = profile_slots.get(reward.get("profile_slot"))
                sticker_id = sha_to_id.get(reward.get("sticker_sha256"))
                position = int(reward.get("position", 0))
                if not profile or not sticker_id or position < 1:
                    raise RuntimeError("Sticker pack contains an invalid album entry.")
                connection.execute(
                    """
                    INSERT INTO catalog_rewards(profile, position, sticker_id, activity, cycle, earned_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile, position, sticker_id, reward.get("activity") or "restored",
                        int(reward.get("cycle", 0)), manifest.get("created_at") or utc_now(),
                    ),
                )
                restored_rewards += 1

        restored_variants = 0
        if format_version >= 4:
            for variant in manifest.get("activity_variants", []):
                profile = profile_slots.get(variant.get("profile_slot"))
                activity = str(variant.get("activity", ""))
                attempt = int(variant.get("attempt", 0))
                signature = str(variant.get("signature", ""))
                plan_json = str(variant.get("plan_json", ""))
                completed = int(variant.get("completed", 0))
                if not profile or not activity or attempt < 1 or len(signature) != 64 or completed not in (0, 1):
                    raise RuntimeError("Sticker pack contains an invalid remembered game plan.")
                try:
                    json.loads(plan_json)
                except (TypeError, ValueError):
                    raise RuntimeError("Sticker pack contains a damaged remembered game plan.")
                connection.execute(
                    """
                    INSERT INTO activity_variants(profile, activity, attempt, signature, plan_json, completed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile, activity, attempt, signature, plan_json, completed,
                        variant.get("created_at") or manifest.get("created_at") or utc_now(),
                    ),
                )
                restored_variants += 1
        connection.commit()
    connection.close()
    print(
        f"Restored {len(items)} sticker files, {restored_rewards} album entries "
        f"and {restored_variants} remembered game plans from {source}."
    )
    return True

def github_json(method, path, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"https://api.github.com{path}", data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "little-sounds-sticker-backup")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    return json.loads(content) if content else {}


def upload_asset(path, repository, release_id, token):
    size = path.stat().st_size
    if size >= 2 * 1024 * 1024 * 1024:
        raise RuntimeError("The sticker pack is too large for one GitHub Release asset.")
    connection = http.client.HTTPSConnection("uploads.github.com", timeout=300)
    endpoint = f"/repos/{repository}/releases/{release_id}/assets?name={urllib.parse.quote(ASSET_NAME)}"
    connection.putrequest("POST", endpoint)
    connection.putheader("Accept", "application/vnd.github+json")
    connection.putheader("Authorization", f"Bearer {token}")
    connection.putheader("X-GitHub-Api-Version", "2022-11-28")
    connection.putheader("User-Agent", "little-sounds-sticker-backup")
    connection.putheader("Content-Type", "application/gzip")
    connection.putheader("Content-Length", str(size))
    connection.endheaders()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            connection.send(chunk)
    response = connection.getresponse()
    content = response.read()
    if response.status != 201:
        raise RuntimeError(f"GitHub upload failed ({response.status}): {content.decode(errors='replace')}")
    return json.loads(content)


def upload_pack(source, repository):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing.")
    encoded_tag = urllib.parse.quote(RELEASE_TAG, safe="")
    try:
        release = github_json("GET", f"/repos/{repository}/releases/tags/{encoded_tag}", token)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        release = github_json(
            "POST",
            f"/repos/{repository}/releases",
            token,
            {
                "tag_name": RELEASE_TAG,
                "target_commitish": "main",
                "name": "Reusable Little Sounds sticker pack",
                "body": "Generated sticker assets plus anonymised child album positions and used-sticker state for fresh family VPS installations.",
                "draft": False,
                "prerelease": False,
            },
        )
    for asset in release.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            github_json("DELETE", f"/repos/{repository}/releases/assets/{asset['id']}", token)
    uploaded = upload_asset(source, repository, int(release["id"]), token)
    download = uploaded.get("browser_download_url") or f"https://github.com/{repository}/releases/download/{RELEASE_TAG}/{ASSET_NAME}"
    print(f"Uploaded reusable sticker pack: {download}")
    return download


def main():
    parser = argparse.ArgumentParser(description="Create, restore or upload the reusable Little Sounds sticker pack.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--output", type=Path, default=DEFAULT_ARCHIVE)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    upload_parser = subparsers.add_parser("upload")
    upload_parser.add_argument("source", type=Path, nargs="?", default=DEFAULT_ARCHIVE)
    upload_parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    args = parser.parse_args()
    if args.command == "create":
        create_pack(args.output)
    elif args.command == "restore":
        restore_pack(args.source)
    else:
        upload_pack(args.source, args.repository)


if __name__ == "__main__":
    main()
