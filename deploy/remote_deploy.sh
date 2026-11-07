#!/usr/bin/env bash
# Runs on the Linode as prch, from /opt/prch. push.ps1 calls it after uploading.
# Unpacks any uploaded game code/assets, renders Nakama's config from .env, installs the
# nightly database dump, and (re)starts the stack.
set -euo pipefail
cd /opt/prch
IN=/opt/prch/incoming
GAME=/opt/prch/gameserver/game

if [ ! -f .env ]; then
  echo "STOP: no /opt/prch/.env. Run: bash make_env.sh <public host>"
  exit 1
fi

mkdir -p "$GAME"
# Replace whole folders so files deleted on the laptop do not linger here.
if [ -f "$IN/code.tgz" ]; then
  rm -rf "$GAME/Code" "$GAME/Server" "$GAME/requirements.txt"
  tar -xzf "$IN/code.tgz" -C "$GAME"
  rm "$IN/code.tgz"
fi
if [ -f "$IN/assets.tgz" ]; then
  rm -rf "$GAME/Graphics" "$GAME/Audio" "$GAME/levels"
  tar -xzf "$IN/assets.tgz" -C "$GAME"
  rm "$IN/assets.tgz"
fi

set -a
. ./.env
set +a
envsubst '${NAKAMA_SESSION_KEY} ${NAKAMA_REFRESH_KEY} ${NAKAMA_SERVER_KEY} ${NAKAMA_HTTP_KEY} ${LAUNCHER_KEY} ${NAKAMA_CONSOLE_USER} ${NAKAMA_CONSOLE_PASSWORD} ${NAKAMA_CONSOLE_SIGNING_KEY}' \
  < nakama/local.yml.tmpl > nakama/local.yml
chmod 600 nakama/local.yml

# Nightly dump at 04:00, keep 14 days. Both lines mention prch/backups, so a re-run
# replaces them instead of adding copies.
DUMP='0 4 * * * cd /opt/prch && docker compose exec -T postgres pg_dump -U postgres nakama | gzip > /opt/prch/backups/nakama-$(date +\%F).sql.gz'
PRUNE='30 4 * * * find /opt/prch/backups -name "nakama-*.sql.gz" -mtime +14 -delete'
( crontab -l 2>/dev/null | grep -v 'prch/backups' || true; echo "$DUMP"; echo "$PRUNE" ) | crontab -

if [ -d "$GAME/Code" ] && [ -d "$GAME/Graphics" ]; then
  docker compose up -d --build
else
  echo "(no game files uploaded yet: starting postgres, nakama and caddy only)"
  docker compose up -d --build postgres nakama caddy
fi
docker compose ps
