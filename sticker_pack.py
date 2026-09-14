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
        """
    )
    connection.commit()


def add_bytes(archive, name, content):
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def create_pack(destination):
    connection = database()
    ensure_schema(connection)
    items = []
    source_files = []
    for category in THEMES:
        rows = connection.execute(
            """
            SELECT serial, image_path, created_at, sha256, phash, dhash, colorhash, prompt
            FROM catalog_stickers
            WHERE category = ? AND active = 1 AND staged = 0
            ORDER BY serial
            """,
            (category,),
        ).fetchall()
        if len(rows) != TARGET:
            raise RuntimeError(f"{category} has {len(rows)} active stickers. Run generate before creating the backup.")
        for pack_serial, row in enumerate(rows, start=1):
            private_source = PRIVATE_ROOT / category / f"{int(row['serial']):04d}.png"
            public_source = SITE_ROOT / str(row["image_path"]).lstrip("/")
            if not private_source.is_file() or not public_source.is_file():
                raise FileNotFoundError(f"Sticker files are incomplete for {category} #{row['serial']}.")
            private_bytes = private_source.read_bytes()
            if hashlib.sha256(private_bytes).hexdigest() != row["sha256"]:
                raise RuntimeError(f"Checksum mismatch for {private_source}.")
            private_name = f"private/{category}/{pack_serial:04d}.png"
            public_name = f"public/{category}/{pack_serial:04d}.webp"
            source_files.append((private_name, private_source, public_name, public_source))
            items.append(
                {
                    "category": category,
                    "serial": pack_serial,
                    "created_at": row["created_at"],
                    "sha256": row["sha256"],
                    "phash": row["phash"],
                    "dhash": row["dhash"],
                    "colorhash": row["colorhash"],
                    "prompt": row["prompt"],
                    "private": private_name,
                    "public": public_name,
                }
            )
    history = [dict(row) for row in connection.execute(
        "SELECT category, sha256, phash, dhash, colorhash, prompt, created_at FROM sticker_history ORDER BY category, created_at, sha256"
    )]
    connection.close()
    manifest = {
        "format": 2,
        "created_at": utc_now(),
        "target_per_theme": TARGET,
        "themes": list(THEMES),
        "stickers": items,
        "history": history,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz", compresslevel=6) as archive:
        add_bytes(archive, "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
        for private_name, private_source, public_name, public_source in source_files:
            archive.add(private_source, arcname=private_name, recursive=False)
            archive.add(public_source, arcname=public_name, recursive=False)
    temporary.replace(destination)
    print(f"Created {destination} with {len(items)} reusable stickers and {len(history)} remembered design fingerprints.")
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
        if manifest.get("format") != 2 or tuple(manifest.get("themes", [])) != THEMES:
            raise RuntimeError("This is not a compatible Little Sounds sticker pack.")
        items = manifest.get("stickers", [])
        if len(items) != TARGET * len(THEMES):
            raise RuntimeError(f"Sticker pack contains {len(items)} stickers; expected {TARGET * len(THEMES)}.")
        for category in THEMES:
            if sum(1 for item in items if item.get("category") == category) != TARGET:
                raise RuntimeError(f"Sticker pack does not contain exactly {TARGET} {category} stickers.")
        connection.execute("BEGIN IMMEDIATE")
        for item in items:
            category = item["category"]
            serial = int(item["serial"])
            if category not in THEMES or not 1 <= serial <= TARGET:
                raise RuntimeError("Sticker pack contains an invalid category or slot.")
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
            connection.execute(
                """
                INSERT INTO catalog_stickers(category, serial, image_path, active, staged, created_at,
                                             sha256, phash, dhash, colorhash, prompt)
                VALUES (?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?)
                """,
                (category, serial, f"/sticker-images/{category}/{serial:04d}.webp", item["created_at"],
                 item["sha256"], item.get("phash"), item.get("dhash"), item.get("colorhash"), item.get("prompt")),
            )
        for item in manifest.get("history", []):
            if item.get("category") not in THEMES:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO sticker_history(category, sha256, phash, dhash, colorhash, prompt, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item["category"], item["sha256"], item.get("phash"), item.get("dhash"),
                 item.get("colorhash"), item.get("prompt"), item.get("created_at") or utc_now()),
            )
        connection.commit()
    connection.close()
    print(f"Restored {len(items)} stickers from {source}.")
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
                "body": "Generated sticker assets used to restore fresh family VPS installations without paying to generate the same collection again.",
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
