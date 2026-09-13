#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this update as root."
  exit 1
fi

app_file="/opt/little-sounds/app.py"
shell_file="/var/www/little-sounds/assets/site-shell.js"
module_file="/opt/little-sounds/parent_test.py"

if [ ! -f "$app_file" ] || [ ! -f "$shell_file" ]; then
  echo "Little Sounds is not installed in the expected location."
  exit 1
fi

if [ ! -f "${app_file}.before-parent-test" ]; then
  cp -a "$app_file" "${app_file}.before-parent-test"
fi
if [ ! -f "${shell_file}.before-parent-test" ]; then
  cp -a "$shell_file" "${shell_file}.before-parent-test"
fi

install -m 0644 /dev/stdin "$module_file" <<'PY'
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request


parent_test_blueprint = Blueprint("parent_test", __name__)
database_path = Path(os.environ.get("LITTLE_SOUNDS_DATA", "/var/lib/little-sounds")) / "little-sounds.sqlite3"
sticker_directory = Path(os.environ.get("LITTLE_SOUNDS_STICKERS", "/var/www/little-sounds/sticker-images"))
switch_pin = os.environ.get("LITTLE_SOUNDS_PIN", "0000")
parent_profile = os.environ.get("LITTLE_SOUNDS_PARENT", "Parent").strip() or "Parent"
cookie_name = "little_sounds_device"
categories = {
    "smiley-faces": "Smiley Faces",
    "well-done": "Well Done",
    "youre-a-star": "You're a Star",
}


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    connection = sqlite3.connect(database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS parent_test_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            category TEXT NOT NULL,
            sticker_number INTEGER NOT NULL,
            earned_at TEXT NOT NULL,
            UNIQUE(profile, category, sticker_number)
        )
        """
    )
    return connection


def active_parent(connection):
    token = request.cookies.get(cookie_name, "")
    if not token:
        return None
    device = connection.execute("SELECT profile FROM devices WHERE token = ?", (token,)).fetchone()
    if device is None or device["profile"] != parent_profile:
        return None
    return device


def check_parent_and_pin(connection):
    if active_parent(connection) is None:
        return "Switch to the parent profile first."
    supplied_pin = str((request.get_json(silent=True) or {}).get("pin", ""))
    if not secrets.compare_digest(supplied_pin, switch_pin):
        return "That PIN is not correct."
    return None


def category_payloads():
    return [
        {
            "id": category,
            "label": label,
            "image": f"/sticker-images/{category}/001.webp",
        }
        for category, label in categories.items()
        if (sticker_directory / category / "001.webp").is_file()
    ]


def reward_payload(row):
    return {
        "position": int(row["id"]),
        "profile": row["profile"],
        "category": row["category"],
        "category_label": categories[row["category"]],
        "sticker_number": int(row["sticker_number"]),
        "image": f"/sticker-images/{row['category']}/{int(row['sticker_number']):03d}.webp",
        "earned_at": row["earned_at"],
        "test_reward": True,
    }


@parent_test_blueprint.post("/api/parent-test/verify")
def verify_parent_test():
    with connect() as connection:
        error = check_parent_and_pin(connection)
        if error:
            return jsonify({"error": error}), 403
        return jsonify({"categories": category_payloads()})


@parent_test_blueprint.post("/api/parent-test/claim")
def claim_parent_test():
    body = request.get_json(silent=True) or {}
    requested_category = str(body.get("category", ""))
    with connect() as connection:
        error = check_parent_and_pin(connection)
        if error:
            return jsonify({"error": error}), 403
        available_categories = {item["id"] for item in category_payloads()}
        if requested_category not in available_categories:
            return jsonify({"error": "Choose an available sticker collection."}), 400
        available_numbers = sorted(
            int(path.stem)
            for path in (sticker_directory / requested_category).glob("*.webp")
            if path.stem.isdigit()
        )
        used_numbers = {
            int(row[0])
            for row in connection.execute(
                "SELECT sticker_number FROM parent_test_rewards WHERE profile = ? AND category = ?",
                (parent_profile, requested_category),
            )
        }
        unused_numbers = [number for number in available_numbers if number not in used_numbers]
        if not unused_numbers:
            return jsonify({"error": "You have tested every sticker in that collection."}), 409
        number = secrets.choice(unused_numbers)
        connection.execute(
            "INSERT INTO parent_test_rewards(profile, category, sticker_number, earned_at) VALUES (?, ?, ?, ?)",
            (parent_profile, requested_category, number, timestamp()),
        )
        row = connection.execute(
            "SELECT id, profile, category, sticker_number, earned_at FROM parent_test_rewards WHERE id = last_insert_rowid()"
        ).fetchone()
        return jsonify(reward_payload(row))


@parent_test_blueprint.get("/api/parent-test/rewards")
def parent_test_rewards():
    with connect() as connection:
        if active_parent(connection) is None:
            return jsonify({"error": "Switch to the parent profile first."}), 403
        rows = connection.execute(
            "SELECT id, profile, category, sticker_number, earned_at FROM parent_test_rewards WHERE profile = ? ORDER BY id",
            (parent_profile,),
        ).fetchall()
        return jsonify({"profile": parent_profile, "stickers": [reward_payload(row) for row in rows]})
PY

if ! grep -Fq 'parent-test-feature' "$app_file"; then
  install -m 0644 /dev/stdin /tmp/little-sounds-parent-register.txt <<'PY'

# parent-test-feature
from parent_test import parent_test_blueprint
app.register_blueprint(parent_test_blueprint)
PY
  tee -a "$app_file" </tmp/little-sounds-parent-register.txt >/dev/null
  rm -f /tmp/little-sounds-parent-register.txt
fi

if ! grep -Fq 'parent-test-feature' "$shell_file"; then
  install -m 0644 /dev/stdin /tmp/little-sounds-parent-test.js <<'JS'

// parent-test-feature
(function () {
  "use strict";

  let verifiedPin = "";

  async function requestJson(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...options
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || "Something went wrong.");
    return result;
  }

  function modalParts() {
    return {
      modal: document.getElementById("rewardModal"),
      card: document.getElementById("rewardCard")
    };
  }

  function closeModal() {
    modalParts().modal.hidden = true;
    verifiedPin = "";
  }

  function showPin() {
    const { modal, card } = modalParts();
    card.innerHTML = `
      <h2>🧪 Test a sticker</h2>
      <p>This saves only to Waqaar's test collection. It cannot change either child's stickers.</p>
      <div class="profile-pin">
        <label for="parentTestPin"><strong>Parent PIN</strong></label>
        <input id="parentTestPin" type="password" inputmode="numeric" maxlength="4" autocomplete="off" placeholder="••••">
      </div>
      <p class="profile-error" id="parentTestError" role="alert"></p>
      <div class="site-actions">
        <button class="site-primary" id="parentTestContinue" type="button">Continue</button>
        <button class="site-secondary" id="parentTestView" type="button">My test stickers</button>
        <button class="site-secondary" id="parentTestCancel" type="button">Cancel</button>
      </div>`;
    modal.hidden = false;
    const input = document.getElementById("parentTestPin");
    const submit = async () => {
      const errorBox = document.getElementById("parentTestError");
      errorBox.textContent = "";
      try {
        verifiedPin = input.value;
        const result = await requestJson("/api/parent-test/verify", {
          method: "POST",
          body: JSON.stringify({ pin: verifiedPin })
        });
        showChoices(result.categories);
      } catch (error) {
        verifiedPin = "";
        errorBox.textContent = error.message;
        input.select();
      }
    };
    document.getElementById("parentTestContinue").onclick = submit;
    input.addEventListener("keydown", event => { if (event.key === "Enter") submit(); });
    document.getElementById("parentTestView").onclick = showCollection;
    document.getElementById("parentTestCancel").onclick = closeModal;
    input.focus();
  }

  function showChoices(categories) {
    const { card } = modalParts();
    card.innerHTML = `
      <h2>Choose your test sticker!</h2>
      <div class="sticker-choice-grid">
        ${categories.map(category => `
          <button class="sticker-choice" type="button" data-category="${category.id}">
            <img src="${category.image}" alt=""><span>${category.label}</span>
          </button>`).join("")}
      </div>
      <div class="site-actions"><button class="site-secondary" id="parentTestCancel" type="button">Cancel</button></div>`;
    card.querySelectorAll(".sticker-choice").forEach(button => button.addEventListener("click", async () => {
      card.querySelectorAll("button").forEach(item => { item.disabled = true; });
      try {
        const reward = await requestJson("/api/parent-test/claim", {
          method: "POST",
          body: JSON.stringify({ pin: verifiedPin, category: button.dataset.category })
        });
        showReward(reward);
      } catch (error) {
        card.innerHTML = `<h2>Oops</h2><p>${error.message}</p><div class="site-actions"><button class="site-secondary" id="parentTestClose" type="button">Close</button></div>`;
        document.getElementById("parentTestClose").onclick = closeModal;
      }
    }));
    document.getElementById("parentTestCancel").onclick = closeModal;
  }

  function showReward(reward) {
    const { card } = modalParts();
    card.innerHTML = `
      <h2>Well done, ${reward.profile}!</h2>
      <p class="reward-number">Test sticker ${reward.position}</p>
      <div><img class="reward-image" src="${reward.image}" alt="${reward.category_label} test sticker"></div>
      <p>Saved only in your test collection.</p>
      <div class="site-actions">
        <button class="site-primary" id="parentTestAgain" type="button">Test another</button>
        <button class="site-secondary" id="parentTestView" type="button">My test stickers</button>
        <button class="site-secondary" id="parentTestDone" type="button">Done</button>
      </div>`;
    window.SiteAudio?.play("/audio/ui/well-done.mp3");
    document.getElementById("parentTestAgain").onclick = showPin;
    document.getElementById("parentTestView").onclick = showCollection;
    document.getElementById("parentTestDone").onclick = closeModal;
  }

  async function showCollection() {
    const { modal, card } = modalParts();
    modal.hidden = false;
    card.innerHTML = "<h2>Loading test stickers...</h2>";
    try {
      const result = await requestJson("/api/parent-test/rewards");
      card.innerHTML = `
        <h2>🧪 Waqaar's test stickers (${result.stickers.length})</h2>
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;max-height:55vh;overflow:auto;padding:5px">
          ${result.stickers.map(sticker => `<img style="width:100%;aspect-ratio:1;object-fit:contain" src="${sticker.image}" alt="${sticker.category_label} test sticker ${sticker.position}" loading="lazy">`).join("")}
        </div>
        <div class="site-actions">
          <button class="site-primary" id="parentTestNew" type="button">Test a sticker</button>
          <button class="site-secondary" id="parentTestDone" type="button">Done</button>
        </div>`;
      document.getElementById("parentTestNew").onclick = showPin;
      document.getElementById("parentTestDone").onclick = closeModal;
    } catch (error) {
      card.innerHTML = `<h2>Oops</h2><p>${error.message}</p><div class="site-actions"><button class="site-secondary" id="parentTestDone" type="button">Done</button></div>`;
      document.getElementById("parentTestDone").onclick = closeModal;
    }
  }

  window.ProfileShell.ready.then(profile => {
    if (profile !== window.ProfileShell.parentProfile) return;
    const tools = document.querySelector(".site-tools");
    if (!tools || document.getElementById("parentStickerTestButton")) return;
    const button = document.createElement("button");
    button.className = "site-tool-button";
    button.id = "parentStickerTestButton";
    button.type = "button";
    button.setAttribute("aria-label", "Test the sticker reward");
    button.textContent = "🧪 Test";
    button.onclick = showPin;
    tools.prepend(button);
  });
})();
JS
  tee -a "$shell_file" </tmp/little-sounds-parent-test.js >/dev/null
  rm -f /tmp/little-sounds-parent-test.js
fi

chown root:root "$module_file" "$app_file" "$shell_file"
chmod 0644 "$module_file" "$app_file" "$shell_file"
/opt/little-sounds-venv/bin/python -m py_compile "$app_file" "$module_file"
systemctl restart little-sounds
nginx -t
systemctl reload nginx
curl -fsS http://127.0.0.1/api/health >/dev/null

echo "Parent sticker test installed. Refresh the site while using Waqaar's profile."
