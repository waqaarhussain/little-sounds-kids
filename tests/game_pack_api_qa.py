#!/usr/bin/env python3
import importlib.util
import os
import tempfile
from pathlib import Path


project = Path(__file__).resolve().parents[1]
temporary = tempfile.TemporaryDirectory(prefix="little-sounds-game-api-")
os.environ["LITTLE_SOUNDS_DATA"] = temporary.name
os.environ["LITTLE_SOUNDS_SITE"] = str(project / "site")
os.environ["LITTLE_SOUNDS_STICKERS"] = str(project / "site" / "sticker-images")
os.environ["LITTLE_SOUNDS_PARENT"] = "Parent"
os.environ["LITTLE_SOUNDS_CHILD_1"] = "Nevaeh"
os.environ["LITTLE_SOUNDS_CHILD_2"] = "Inaara"

spec = importlib.util.spec_from_file_location("game_pack_app", project / "server" / "app.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with module.database() as connection:
    for category in module.ACTIVITY_THEMES:
        allowed = sorted(module.SINGLE_CHARACTER_SLOTS[category])
        for offset, slot in enumerate(allowed[:3], 1):
            serial = slot + 1
            connection.execute(
                """
                INSERT INTO catalog_stickers(category, serial, image_path, sha256, phash, dhash, colorhash, prompt, active, staged, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                """,
                (
                    category,
                    serial,
                    f"/sticker-images/{category}-{serial}.png",
                    f"sha-{category}-{offset}",
                    f"phash-{category}-{offset}",
                    f"dhash-{category}-{offset}",
                    f"colour-{category}-{offset}",
                    "QA character",
                    module.now(),
                ),
            )

client = module.app.test_client()
selected = client.post("/api/profile/select", json={"profile": "Nevaeh"})
assert selected.status_code == 200, selected.get_json()

for activity in sorted(module.GAME_PACK_ACTIVITIES):
    variant_response = client.get(f"/api/activity/variant?activity={activity}")
    assert variant_response.status_code == 200, (activity, variant_response.get_json())
    variant = variant_response.get_json()
    plan = variant["plan"]
    assert plan["layout_version"] == 1
    assert len(plan["characters"]) == 2
    assert len(set(plan["themes"])) == 2
    assert plan["world"] in module.GAME_PACK_WORLDS
    assert isinstance(plan["seed"], int)
    completion_response = client.post(
        "/api/progress/complete",
        json={"activity": activity, "item": "mission", "attempt": variant["attempt"]},
    )
    assert completion_response.status_code == 200, (activity, completion_response.get_json())
    completion = completion_response.get_json()
    assert completion["exercise_completed"] is True
    assert completion["reward_token"]

print("GAME PACK API QA PASSED: seven random cross-theme games and seven sticker rewards")
temporary.cleanup()
