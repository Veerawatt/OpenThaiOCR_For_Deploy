#!/usr/bin/env bash
# One-shot setup on a fresh Hostinger KVM VPS (Ubuntu 22.04/24.04), run as root
# from the project folder:   sudo bash scripts/setup-vps.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $EUID -ne 0 ]]; then echo "run as root: sudo bash $0"; exit 1; fi

echo "==> Docker"
if ! docker compose version >/dev/null 2>&1; then
  apt-get update
  apt-get install -y docker.io docker-compose-v2 || {
    # Older images without docker-compose-v2: fall back to Docker's official repo.
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  }
  systemctl enable --now docker
fi
docker compose version

echo "==> Firewall (SSH, HTTP, HTTPS)"
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
  ufw --force enable
fi

echo "==> .env"
if [[ ! -f .env ]]; then
  cp .env.example .env
  key=$(openssl rand -hex 24)
  sed -i "s/^API_KEY=.*/API_KEY=${key}/" .env
  echo "created .env with a new API key"
fi
grep -E '^(DOMAIN|API_KEY)=' .env

echo "==> Build and start"
docker compose up -d --build

echo "==> Waiting for the model to load"
for _ in $(seq 1 60); do
  if docker compose exec -T ocr curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    docker compose exec -T ocr curl -fsS http://127.0.0.1:8000/health; echo
    ip=$(curl -fsS -4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo
    echo "Ready. Open http://${ip}/  (or https://<your DOMAIN>/ if you set one)"
    exit 0
  fi
  sleep 2
done
echo "service did not become healthy; see: docker compose logs ocr"
exit 1
