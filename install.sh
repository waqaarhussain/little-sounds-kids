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

echo "[1/7] Installing the web server and media tools..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx curl ca-certificates ffmpeg python3-venv fonts-dejavu-core

echo "[2/7] Downloading the human-recorded phonics sounds..."
curl -fsSL --retry 4 --retry-delay 2 \
  "https://github.com/bblodget/Letter_Sounds/archive/26c887a1341034239b532ab05a641ac3d6a65153.tar.gz" \
  -o "$work_dir/sounds.tar.gz"
tar -xzf "$work_dir/sounds.tar.gz" -C "$work_dir"
downloaded_source="$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name 'Letter_Sounds-*' -print -quit)"
if [ -z "$downloaded_source" ] || [ ! -f "$downloaded_source/sounds/a.ogg" ] || [ ! -f "$downloaded_source/sounds/z.ogg" ]; then
  echo "The recorded sound download failed. Nothing was published."
  exit 1
fi

echo "[3/7] Preparing the natural British voice..."
python3 -m venv "$work_dir/voice-env"
"$work_dir/voice-env/bin/pip" install --disable-pip-version-check "piper-tts==1.8.0"
curl -fsSL --retry 4 --retry-delay 2 \
  "https://huggingface.co/rhasspy/piper-voices/resolve/1162a9173d0ce503555aed757976b7a9912eae4c/en/en_GB/cori/high/en_GB-cori-high.onnx?download=true" \
  -o "$work_dir/en_GB-cori-high.onnx"
curl -fsSL --retry 4 --retry-delay 2 \
  "https://huggingface.co/rhasspy/piper-voices/resolve/1162a9173d0ce503555aed757976b7a9912eae4c/en/en_GB/cori/high/en_GB-cori-high.onnx.json?download=true" \
  -o "$work_dir/en_GB-cori-high.onnx.json"
echo "470b4dd634c98f8a4850d7626ffc3dfc90774628eeef6605a6dd8f88f30a5903  $work_dir/en_GB-cori-high.onnx" | sha256sum -c -
echo "9e7fb5b5671612c22f3c81cbe46c1ae87b031a4632bcb509e499dad6f1e2adec  $work_dir/en_GB-cori-high.onnx.json" | sha256sum -c -

echo "[4/7] Generating the complete iPhone and iPad audio pack..."
site_stage="$work_dir/site"
install -d -m 0755 "$site_stage/licenses"
cp -a "$installer_dir/site/." "$site_stage/"
cp "$downloaded_source/LICENSE" "$site_stage/licenses/Letter_Sounds_GPL-3.0.txt"
"$work_dir/voice-env/bin/python" "$installer_dir/generate_audio.py" \
  --model "$work_dir/en_GB-cori-high.onnx" \
  --phonics-dir "$downloaded_source/sounds" \
  --output "$site_stage/audio"

echo "[5/7] Building 100 different stickers in each school reward collection..."
python3 -m venv "$work_dir/sticker-env"
"$work_dir/sticker-env/bin/pip" install --disable-pip-version-check \
  "Pillow==11.3.0" "requests==2.32.5"
"$work_dir/sticker-env/bin/python" "$installer_dir/download_stickers.py" \
  --output "$work_dir/stickers" --count 100 --school-only
install -d -m 0700 /root/stickers
cp -a "$work_dir/stickers/." /root/stickers/
install -d -m 0755 "$site_stage/sticker-images"
cp -a "$work_dir/stickers/." "$site_stage/sticker-images/"

echo "[6/7] Installing the profile and achievement service..."
python3 -m venv /opt/little-sounds-venv
/opt/little-sounds-venv/bin/pip install --disable-pip-version-check -r "$installer_dir/server/requirements.txt"
install -d -m 0755 /opt/little-sounds
install -m 0644 "$installer_dir/server/app.py" /opt/little-sounds/app.py
install -d -o www-data -g www-data -m 0750 /var/lib/little-sounds

umask 077
{
  printf 'LITTLE_SOUNDS_PARENT="%s"\n' "$parent_profile"
  printf 'LITTLE_SOUNDS_CHILD_1="%s"\n' "$child_one"
  printf 'LITTLE_SOUNDS_CHILD_2="%s"\n' "$child_two"
  printf 'LITTLE_SOUNDS_PIN="%s"\n' "$switch_pin"
  printf 'LITTLE_SOUNDS_DATA="/var/lib/little-sounds"\n'
  printf 'LITTLE_SOUNDS_STICKERS="/var/www/little-sounds/sticker-images"\n'
} > /etc/little-sounds.env

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

echo "[7/7] Publishing the mobile-friendly website..."
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
    location = /stickers { return 301 /stickers/; }

    location /api/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        try_files $uri $uri/ =404;
    }

    location ~* \.(mp3|webp|png|jpg|jpeg)$ {
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

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 'Nginx HTTP'
fi

server_ip="$(hostname -I | awk '{print $1}')"
echo
echo "Installation complete."
echo "Landing page: http://${server_ip}"
echo "Phonics book: http://${server_ip}/phonicsbook/"
echo "Fun tracing: http://${server_ip}/handwriting/"
echo "Sticker book: http://${server_ip}/stickers/"
