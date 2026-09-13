#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this command as root."
  exit 1
fi

if [ ! -d /var/www/little-sounds ]; then
  echo "Finish the Little Sounds base installation first."
  exit 1
fi

if systemctl is-active --quiet little-sounds-ai-stickers.service 2>/dev/null; then
  echo "The AI sticker generator is already running."
  echo "Watch it with: journalctl -u little-sounds-ai-stickers -f"
  exit 0
fi

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
generator_source="$script_directory/generate_openai_stickers.py"
if [ ! -f "$generator_source" ]; then
  echo "The generator file is missing from the downloaded package."
  exit 1
fi

echo "Preparing the OpenAI sticker generator..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv ca-certificates

if [ ! -x /opt/little-sounds-ai-venv/bin/python ]; then
  python3 -m venv /opt/little-sounds-ai-venv
fi
/opt/little-sounds-ai-venv/bin/pip install --disable-pip-version-check --upgrade \
  "openai>=2.0,<3.0" "Pillow>=11.0,<13.0" "ImageHash>=4.3,<5.0"
install -d -m 0755 /opt/little-sounds
install -m 0755 "$generator_source" /opt/little-sounds/generate_openai_stickers.py
install -d -m 0700 /root/stickers/openai
install -d -m 0755 /var/www/little-sounds/ai-stickers

while true; do
  read -r -s -p "Paste your OpenAI API key, then press Enter: " openai_key
  echo
  if [[ "$openai_key" =~ ^sk-[A-Za-z0-9_-]{20,}$ ]]; then
    break
  fi
  echo "That does not look like a complete OpenAI API key. Try again."
done

key_length="${#openai_key}"
key_start="${openai_key:0:7}"
key_end="${openai_key:key_length-4:4}"
echo "Key received: ${key_start}...${key_end} (${key_length} characters)"
read -r -p "Keep the existing stickers and build the 80-sticker trial with this key? [Y/n]: " confirmation
if [[ "$confirmation" =~ ^[Nn]$ ]]; then
  unset openai_key
  echo "Cancelled. Nothing was generated."
  exit 0
fi

umask 077
install -m 0600 /dev/stdin /etc/little-sounds-openai.env <<ENV
OPENAI_API_KEY=${openai_key}
PYTHONUNBUFFERED=1
ENV
unset openai_key

install -m 0644 /dev/stdin /etc/systemd/system/little-sounds-ai-stickers.service <<'SYSTEMD'
[Unit]
Description=Generate Little Sounds AI sticker trial
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/little-sounds-openai.env
WorkingDirectory=/opt/little-sounds
ExecStart=/opt/little-sounds-ai-venv/bin/python /opt/little-sounds/generate_openai_stickers.py --count 10 --private-root /root/stickers/openai --public-root /var/www/little-sounds/ai-stickers
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
ReadWritePaths=/root/stickers/openai /var/www/little-sounds/ai-stickers

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl reset-failed little-sounds-ai-stickers.service 2>/dev/null || true
systemctl start little-sounds-ai-stickers.service
sleep 2
rm -f /etc/little-sounds-openai.env

if systemctl is-failed --quiet little-sounds-ai-stickers.service; then
  echo "The generator could not start:"
  journalctl -u little-sounds-ai-stickers.service -n 25 --no-pager
  exit 1
fi

echo
echo "The 80-sticker trial is running safely in the background."
echo "You may close Termius; the VPS will continue working."
echo "Live preview: http://152.53.117.106/ai-stickers/"
echo "Progress command: journalctl -u little-sounds-ai-stickers -f"
echo "Status command: systemctl status little-sounds-ai-stickers --no-pager"
