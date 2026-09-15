#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root."
  exit 1
fi

parent_profile="${LITTLE_SOUNDS_PARENT:-}"
child_one="${LITTLE_SOUNDS_CHILD_1:-}"
child_two="${LITTLE_SOUNDS_CHILD_2:-}"
switch_pin="${LITTLE_SOUNDS_PIN:-}"
sticker_backup_url="${LITTLE_SOUNDS_STICKER_BACKUP_URL:-https://github.com/waqaarhussain/little-sounds-kids/releases/download/sticker-pack/little-sounds-sticker-pack.tar.gz}"

if [ -z "$parent_profile" ] || [ -z "$child_one" ] || [ -z "$child_two" ] || [ -z "$switch_pin" ]; then
  if [ ! -t 0 ]; then
    echo "Set LITTLE_SOUNDS_PARENT, LITTLE_SOUNDS_CHILD_1, LITTLE_SOUNDS_CHILD_2 and LITTLE_SOUNDS_PIN."
    exit 1
  fi
  read -r -p "Parent profile name: " parent_profile
  read -r -p "First child profile name: " child_one
  read -r -p "Second child profile name: " child_two
  read -r -s -p "Four-digit switch PIN: " switch_pin
  echo
fi

for profile_name in "$parent_profile" "$child_one" "$child_two"; do
  if ! printf '%s' "$profile_name" | grep -Eq "^[[:alnum:] .'-]{1,30}$"; then
    echo "Profile names may contain letters, numbers, spaces, dots, apostrophes and hyphens only."
    exit 1
  fi
done
if ! printf '%s' "$switch_pin" | grep -Eq '^[0-9]{4}$'; then
  echo "The switch PIN must be exactly four digits."
  exit 1
fi

installer_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work_dir="$(mktemp -d /tmp/little-sounds-install.XXXXXX)"
trap 'rm -rf "$work_dir"' EXIT

echo "[1/4] Installing the web server..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx curl ca-certificates python3-venv fonts-dejavu-core rsync ffmpeg

site_stage="$work_dir/site"
cp -a "$installer_dir/site/." "$site_stage/"

echo "[2/4] Installing the refillable AI sticker helper..."
python3 -m venv /opt/little-sounds-ai-venv
/opt/little-sounds-ai-venv/bin/pip install --disable-pip-version-check --upgrade \
  "openai>=2.0,<3.0" "Pillow>=11.0,<13.0" "ImageHash>=4.3,<5.0"
install -d -m 0755 /opt/little-sounds
install -m 0755 "$installer_dir/generate_stickers.py" /opt/little-sounds/generate_stickers.py
install -m 0755 "$installer_dir/generate_book.py" /opt/little-sounds/generate_book.py
install -m 0755 "$installer_dir/narrate_books.py" /opt/little-sounds/narrate_books.py
rm -f /usr/local/bin/generate /usr/local/bin/backup-stickers
install -m 0755 "$installer_dir/generate-stickers" /usr/local/bin/generate-stickers
install -m 0755 "$installer_dir/generate-book" /usr/local/bin/generate-book
install -m 0755 "$installer_dir/narrate-books" /usr/local/bin/narrate-books
install -m 0755 "$installer_dir/sticker_pack.py" /opt/little-sounds/sticker_pack.py
install -m 0755 "$installer_dir/backup" /usr/local/bin/backup
install -m 0755 "$installer_dir/refresh-test" /usr/local/bin/refresh-test
install -m 0755 "$installer_dir/update-test" /usr/local/bin/update-test
install -m 0755 "$installer_dir/live" /usr/local/bin/live
install -d -m 0700 /root/stickers/catalog
install -d -m 0755 /var/www/little-sounds/sticker-images
install -d -m 0755 /var/www/little-sounds/sticker-generator
install -d -m 0755 /var/www/little-sounds/generated-books

cat > /var/www/little-sounds/sticker-generator/index.html <<'STATUS'
<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sticker Generator</title><style>body{min-height:100vh;margin:0;display:grid;place-items:center;padding:20px;box-sizing:border-box;color:#263657;background:linear-gradient(145deg,#68d2f7,#efe6ff,#fff0a6);font-family:ui-rounded,"Arial Rounded MT Bold",system-ui,sans-serif;text-align:center}main{max-width:650px;padding:35px;border:6px solid #fff;border-radius:32px;background:#ffffffc9;box-shadow:0 12px 30px #34486a30}h1{font-size:clamp(2rem,8vw,4rem);margin:0 0 15px}p{font-size:1.15rem;font-weight:800}code{padding:4px 9px;border-radius:8px;background:#e9e4ff}</style></head><body><main><h1>✨ Sticker Generator</h1><p>Your sticker helper is ready.</p><p>Open Termius as root and run <code>generate-stickers</code>.</p><p><a href="/">◀ Back home</a></p></main></body></html>
STATUS

cat > /etc/systemd/system/little-sounds-sticker-generator.service <<'SYSTEMD'
[Unit]
Description=Fill and replenish Little Sounds sticker books
After=network-online.target little-sounds.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/root/.config/little-sounds/openai.env
WorkingDirectory=/opt/little-sounds
ExecStart=/opt/little-sounds-ai-venv/bin/python /opt/little-sounds/generate_stickers.py
User=root
Group=root
UMask=0022
Nice=10
Restart=no
TimeoutStartSec=infinity
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/root/stickers/catalog /var/www/little-sounds/sticker-images /var/www/little-sounds/sticker-generator /var/lib/little-sounds

[Install]
WantedBy=multi-user.target
SYSTEMD

cat > /etc/systemd/system/little-sounds-book-generator.service <<'SYSTEMD'
[Unit]
Description=Create Little Sounds 16-page storybooks
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/root/.config/little-sounds/openai.env
EnvironmentFile=/run/little-sounds-book.env
WorkingDirectory=/opt/little-sounds
ExecStart=/opt/little-sounds-ai-venv/bin/python /opt/little-sounds/generate_book.py
User=root
Group=root
UMask=0022
Nice=10
Restart=no
TimeoutStartSec=infinity
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/var/www/little-sounds/generated-books
SYSTEMD

echo "[3/4] Installing the profile and achievement service..."
python3 -m venv /opt/little-sounds-venv
/opt/little-sounds-venv/bin/pip install --disable-pip-version-check -r "$installer_dir/server/requirements.txt"
install -d -m 0755 /opt/little-sounds
install -m 0644 "$installer_dir/server/app.py" /opt/little-sounds/app.py
install -m 0644 "$installer_dir/server/requirements.txt" /opt/little-sounds/requirements.txt
python3 -m venv /opt/little-sounds-test-venv
/opt/little-sounds-test-venv/bin/pip install --disable-pip-version-check -r "$installer_dir/server/requirements.txt"
install -d -m 0755 /opt/little-sounds-test /var/www/little-sounds-test
install -m 0644 "$installer_dir/server/app.py" /opt/little-sounds-test/app.py
install -m 0644 "$installer_dir/server/requirements.txt" /opt/little-sounds-test/requirements.txt
install -d -o www-data -g www-data -m 0750 /var/lib/little-sounds /var/lib/little-sounds-test

umask 077
{
  printf 'LITTLE_SOUNDS_PARENT="%s"\n' "$parent_profile"
  printf 'LITTLE_SOUNDS_CHILD_1="%s"\n' "$child_one"
  printf 'LITTLE_SOUNDS_CHILD_2="%s"\n' "$child_two"
  printf 'LITTLE_SOUNDS_PIN="%s"\n' "$switch_pin"
  printf 'LITTLE_SOUNDS_DATA="/var/lib/little-sounds"\n'
  printf 'LITTLE_SOUNDS_STICKERS="/var/www/little-sounds/sticker-images"\n'
} > /etc/little-sounds.env

{
  printf 'LITTLE_SOUNDS_PARENT="%s"\n' "$parent_profile"
  printf 'LITTLE_SOUNDS_CHILD_1="%s"\n' "$child_one"
  printf 'LITTLE_SOUNDS_CHILD_2="%s"\n' "$child_two"
  printf 'LITTLE_SOUNDS_PIN="%s"\n' "$switch_pin"
  printf 'LITTLE_SOUNDS_DATA="/var/lib/little-sounds-test"\n'
  printf 'LITTLE_SOUNDS_STICKERS="/var/www/little-sounds/sticker-images"\n'
  printf 'LITTLE_SOUNDS_COOKIE_NAME="little_sounds_test_device"\n'
} > /etc/little-sounds-test.env

cat > /etc/systemd/system/little-sounds.service <<'SYSTEMD'
[Unit]
Description=Little Sounds profile and rewards service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/little-sounds
EnvironmentFile=/etc/little-sounds.env
ExecStart=/opt/little-sounds-venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8787 --access-logfile - app:app
Restart=on-failure
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/little-sounds

[Install]
WantedBy=multi-user.target
SYSTEMD

cat > /etc/systemd/system/little-sounds-test.service <<'SYSTEMD'
[Unit]
Description=Little Sounds isolated test profile and rewards service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/little-sounds-test
EnvironmentFile=/etc/little-sounds-test.env
ExecStart=/opt/little-sounds-test-venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8788 --access-logfile - app:app
Restart=on-failure
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/lib/little-sounds-test

[Install]
WantedBy=multi-user.target
SYSTEMD

echo "[4/4] Publishing the mobile-friendly website..."
install -d -m 0755 /var/www/little-sounds
cp -a "$site_stage/." /var/www/little-sounds/
chmod -R a+rX /var/www/little-sounds

cat > /etc/nginx/sites-available/little-sounds <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    root /var/www/little-sounds;
    index index.html;

    location = /phonicsbook { return 301 /phonicsbook/; }
    location = /handwriting { return 301 /handwriting/; }
    location = /counting { return 301 /counting/; }
    location = /matching { return 301 /matching/; }
    location = /sorting { return 301 /sorting/; }
    location = /patterns { return 301 /patterns/; }
    location = /odd-one-out { return 301 /odd-one-out/; }
    location = /more-or-less { return 301 /more-or-less/; }
    location = /books { return 301 /books/; }
    location = /letter-hunt { return 301 /letter-hunt/; }
    location = /number-hunt { return 301 /number-hunt/; }
    location = /stickers { return 301 /stickers/; }
    location = /allstickers { return 301 /allstickers/; }
    location = /sticker-generator { return 301 /sticker-generator/; }

    location = /test { return 301 /test/; }

    location ^~ /test/api/ {
        proxy_pass http://127.0.0.1:8788/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location ^~ /test/ {
        alias /var/www/little-sounds-test/;
        index index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri $uri/ =404;
    }

    location ~* \.(webp|png|jpg|jpeg)$ {
        expires 30d;
        add_header Cache-Control "public";
    }

    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
}
NGINX

ln -sfn /etc/nginx/sites-available/little-sounds /etc/nginx/sites-enabled/little-sounds
rm -f /etc/nginx/sites-enabled/default
systemctl daemon-reload
systemctl enable --now little-sounds nginx
systemctl enable little-sounds-test.service
nginx -t
systemctl restart little-sounds
systemctl reload nginx

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1/api/health >/dev/null; then break; fi
  if [ "$attempt" -eq 10 ]; then
    echo "The achievement service did not start. Check: journalctl -u little-sounds"
    exit 1
  fi
  sleep 1
done

if curl -fsSL --retry 3 --retry-delay 2 "$sticker_backup_url" -o "$work_dir/sticker-pack.tar.gz"; then
  echo "Restoring the reusable sticker pack..."
  if python3 /opt/little-sounds/sticker_pack.py restore "$work_dir/sticker-pack.tar.gz"; then
    chown -R www-data:www-data /var/lib/little-sounds
    chmod -R a+rX /var/www/little-sounds/sticker-images
    systemctl restart little-sounds
  else
    echo "The published backup is from an older setup. Installation will continue; run generate-stickers if stickers are missing."
  fi
else
  echo "No reusable backup is published yet. Run generate-stickers after installation."
fi

source_commit="$(curl -fsSL "https://api.github.com/repos/waqaarhussain/little-sounds-kids/branches/main" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"]["sha"])' 2>/dev/null || true)"
if [[ "$source_commit" =~ ^[0-9a-f]{40}$ ]]; then
  printf '%s\n' "$source_commit" > /opt/little-sounds/source-commit
fi
refresh-test

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 'Nginx HTTP'
fi

server_ip="$(hostname -I | awk '{print $1}')"
echo
echo "Installation complete."
echo "Landing page: http://${server_ip}"
echo "Phonics book: http://${server_ip}/phonicsbook/"
echo "Fun tracing: http://${server_ip}/handwriting/"
echo "Count and Choose: http://${server_ip}/counting/"
echo "Match the Pairs: http://${server_ip}/matching/"
echo "Sort and Learn: http://${server_ip}/sorting/"
echo "Finish the Pattern: http://${server_ip}/patterns/"
echo "Odd One Out: http://${server_ip}/odd-one-out/"
echo "Which Has More: http://${server_ip}/more-or-less/"
echo "Letter Hunt: http://${server_ip}/letter-hunt/"
echo "Number Hunt: http://${server_ip}/number-hunt/"
echo "Books: http://${server_ip}/books/"
echo "Test site: http://${server_ip}/test/"
echo "Sticker book: http://${server_ip}/stickers/"
echo "All stickers monitor: http://${server_ip}/allstickers/"
echo
echo "Create or refill stickers: generate-stickers"
echo "Create one or more 16-page books: generate-book"
echo "Save stickers, albums, game memory and generated books: backup"
echo "Save everything except generated books: backup no-books"
echo "Future test workflow: update-test, test at /test/, then run live to promote it."
