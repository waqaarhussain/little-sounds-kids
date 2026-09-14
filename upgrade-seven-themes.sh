#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this update as root."
  exit 1
fi

installer_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
database="/var/lib/little-sounds/little-sounds.sqlite3"
private_category="/root/stickers/catalog/alphablocks"
public_category="/var/www/little-sounds/sticker-images/alphablocks"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot="/root/stickers/rebuild-backups/alphablocks-${stamp}"

for required in generate_stickers.py sticker_pack.py generate backup-stickers server/app.py; do
  if [ ! -f "$installer_dir/$required" ]; then
    echo "Missing update file: $required"
    exit 1
  fi
done

if [ ! -f "$database" ] || [ ! -f /etc/systemd/system/little-sounds.service ]; then
  echo "The Little Sounds base site is not installed on this VPS yet."
  exit 1
fi

systemctl stop little-sounds-sticker-generator.service 2>/dev/null || true

reward_count="$(python3 - "$database" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
try:
    count = connection.execute(
        """
        SELECT COUNT(*)
        FROM catalog_rewards r
        JOIN catalog_stickers s ON s.id = r.sticker_id
        WHERE s.category = 'alphablocks'
        """
    ).fetchone()[0]
finally:
    connection.close()
print(count)
PY
)"

if [ "$reward_count" -ne 0 ]; then
  echo "Stopped safely: $reward_count earned Alphablocks sticker(s) already exist and will not be deleted."
  echo "Tell Codex before continuing so those earned rewards can be preserved."
  exit 1
fi

install -d -m 0700 "$snapshot/private" "$snapshot/public"
install -m 0600 "$database" "$snapshot/little-sounds.sqlite3"
if [ -d "$private_category" ]; then
  cp -a "$private_category/." "$snapshot/private/"
fi
if [ -d "$public_category" ]; then
  cp -a "$public_category/." "$snapshot/public/"
fi

python3 - "$database" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1], timeout=60)
connection.execute("PRAGMA foreign_keys = ON")
connection.execute("BEGIN IMMEDIATE")
try:
    connection.execute("DELETE FROM sticker_history WHERE category = 'alphablocks'")
    connection.execute("DELETE FROM catalog_stickers WHERE category = 'alphablocks'")
    connection.commit()
except Exception:
    connection.rollback()
    raise
finally:
    connection.close()
PY

install -d -m 0700 "$private_category" /root/stickers/catalog/colourblocks
install -d -m 0755 "$public_category" /var/www/little-sounds/sticker-images/colourblocks
find "$private_category" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -delete
find "$public_category" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -delete

install -m 0755 "$installer_dir/generate_stickers.py" /opt/little-sounds/generate_stickers.py
install -m 0755 "$installer_dir/sticker_pack.py" /opt/little-sounds/sticker_pack.py
install -m 0755 "$installer_dir/generate" /usr/local/bin/generate
install -m 0755 "$installer_dir/backup-stickers" /usr/local/bin/backup-stickers
install -m 0644 "$installer_dir/server/app.py" /opt/little-sounds/app.py

chown -R www-data:www-data /var/lib/little-sounds
chmod -R a+rX /var/www/little-sounds/sticker-images
systemctl restart little-sounds

if ! curl -fsS http://127.0.0.1:8787/api/health >/dev/null; then
  echo "The updated service did not answer its health check. Run: journalctl -u little-sounds -n 60"
  exit 1
fi

echo
echo "Seven-theme update complete."
echo "The old Alphablocks files and database are recoverable from: $snapshot"
echo "Your five already-correct themes were not changed."
echo "Now run: generate"
echo "It will create 100 corrected Alphablocks and 100 new Colourblocks."
