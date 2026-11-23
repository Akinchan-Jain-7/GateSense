#!/bin/bash
# One-paste setup for the GateSense live demo on a fresh Ubuntu 24.04 server.
#
# Paste this whole file into Oracle Cloud's "Create instance → Show advanced options →
# Management → Initialization script (cloud-init)" box. It also works on any other Ubuntu
# server: run it once as root (sudo bash oracle-cloud-init.sh).
#
# What it does, in order: opens ports 80/443 in the server's own firewall (Oracle's Ubuntu
# image blocks them), installs Docker, clones the repo, writes .env.prod with fresh random
# secrets (they never leave the server), starts the production stack in demo mode with the
# traffic simulator, and adds a cron job that keeps the server on the newest images.
#
# Progress log on the server: /var/log/gatesense-setup.log
set -euo pipefail
exec >>/var/log/gatesense-setup.log 2>&1
echo "=== GateSense setup started $(date -Is) ==="

APP_DIR=/opt/gatesense
REPO=https://github.com/Akinchan-Jain-7/GateSense.git
APP_USER=ubuntu
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

# 1. Firewall: Oracle's Ubuntu image only allows SSH in iptables. The cloud-side
#    "Security List" rules for 80/443 are added separately in the Oracle console.
if command -v iptables >/dev/null && ! iptables -C INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT 2>/dev/null; then
  iptables -I INPUT 1 -p tcp -m multiport --dports 80,443 -j ACCEPT
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save; fi
fi

# 2. Docker.
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if id "$APP_USER" >/dev/null 2>&1; then usermod -aG docker "$APP_USER"; fi

# 3. Code.
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
git config --system --add safe.directory "$APP_DIR" # the cron job below runs git as root

# 4. Settings with fresh secrets. Only written once, so a rerun never signs everyone out.
if [ ! -f .env.prod ]; then
  public_ip=""
  for url in https://api.ipify.org https://ifconfig.me https://icanhazip.com; do
    public_ip=$(curl -fsS --max-time 10 "$url" | tr -d '[:space:]') && [ -n "$public_ip" ] && break
  done
  if [ -z "$public_ip" ]; then echo "Could not find the public IP"; exit 1; fi
  site="${public_ip//./-}.sslip.io" # free DNS name that points at the IP
  cp .env.prod.example .env.prod
  set_value() { sed -i "s|^$1=.*|$1=$2|" .env.prod; }
  set_value SITE_ADDRESS "$site"
  set_value PUBLIC_BASE_URL "https://$site"
  set_value POSTGRES_PASSWORD "$(openssl rand -hex 32)"
  set_value JWT_SECRET_KEY "$(openssl rand -hex 32)"
  set_value METRICS_TOKEN "$(openssl rand -hex 32)"
  set_value DEMO_MODE true
  set_value COMPOSE_PROFILES demo
  chmod 600 .env.prod
fi
if id "$APP_USER" >/dev/null 2>&1; then chown -R "$APP_USER:$APP_USER" "$APP_DIR"; fi

# 5. Start. Pulling is retried for up to 30 minutes, in case the GHCR packages are still
#    private when the server boots (they must be made public once, see docs/deployment.md).
for attempt in $(seq 1 60); do
  if "${COMPOSE[@]}" pull; then break; fi
  echo "pull failed (attempt $attempt), retrying in 30 s"
  sleep 30
done
"${COMPOSE[@]}" up -d
"${COMPOSE[@]}" ps

# 6. Stay current without SSH deploy keys: every 15 minutes, take new commits and images.
#    `up -d` only restarts the services whose image or settings changed.
cat >/etc/cron.d/gatesense-update <<CRON
*/15 * * * * root (cd $APP_DIR && git pull -q --ff-only && ${COMPOSE[*]} pull -q && ${COMPOSE[*]} up -d) >>/var/log/gatesense-update.log 2>&1
CRON
chmod 644 /etc/cron.d/gatesense-update

echo "=== GateSense setup finished $(date -Is): https://$(grep '^SITE_ADDRESS=' .env.prod | cut -d= -f2) ==="
