#!/usr/bin/env bash
# Run ONCE on the Linode as prch:  cd /opt/prch && bash make_env.sh play.yourdomain.com
# Writes /opt/prch/.env with fresh secrets. Refuses to overwrite: changing these keys logs
# every player out and breaks every issued token. MAX_MATCHES is the one value to edit by
# hand, and only from measured numbers (see Server/NOTES_multiplayer.md).
set -euo pipefail
cd /opt/prch
if [ $# -ne 1 ]; then
  echo "usage: bash make_env.sh <public host, e.g. play.yourdomain.com>"
  exit 1
fi
if [ -e .env ]; then
  echo "STOP: /opt/prch/.env already exists. Not overwriting it."
  exit 1
fi
umask 077
k() { openssl rand -hex 32; }
cat > .env <<EOF
PUBLIC_HOST=$1
POSTGRES_PASSWORD=$(k)
NAKAMA_SERVER_KEY=$(k)
NAKAMA_SESSION_KEY=$(k)
NAKAMA_REFRESH_KEY=$(k)
NAKAMA_HTTP_KEY=$(k)
NAKAMA_CONSOLE_USER=prch-admin
NAKAMA_CONSOLE_PASSWORD=$(k)
NAKAMA_CONSOLE_SIGNING_KEY=$(k)
LAUNCHER_KEY=$(k)
GAME_TICKET_SECRET=$(k)
MAX_MATCHES=1
EOF
chmod 600 .env
echo "wrote /opt/prch/.env"
