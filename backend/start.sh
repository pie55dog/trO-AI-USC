#!/bin/sh
# Container entry point. Cloud Run tells us which port to listen on in $PORT.
set -e
set -f  # keep the * below literal

SERVER="uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=*"

if [ -n "$LITESTREAM_REPLICA_URL" ]; then
  # Bring back the database saved by the last server, if there is one.
  litestream restore -config /etc/litestream.yml -if-db-not-exists -if-replica-exists /data/tro.db
  # Run the API, copying every database change to the bucket as it happens.
  exec litestream replicate -config /etc/litestream.yml -exec "$SERVER"
fi

# No bucket configured (e.g. running the image locally): plain SQLite.
exec $SERVER
