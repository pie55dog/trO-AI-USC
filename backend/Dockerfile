# Tro API container for Google Cloud Run (see deploy/README.md).
#
# The database stays a SQLite file. Cloud Run's disk is wiped whenever the
# server restarts, so Litestream copies every change to a Cloud Storage
# bucket about once a second and restores it when the server starts again.
# Photos and bracelet uploads go straight to the same bucket through a
# Cloud Run volume mount at /media.
FROM python:3.12-slim

ARG LITESTREAM_VERSION=0.3.13
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz /tmp/litestream.tar.gz
RUN tar -C /usr/local/bin -xzf /tmp/litestream.tar.gz && rm /tmp/litestream.tar.gz

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/tro.db \
    MEDIA_DIR=/media

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY litestream.yml /etc/litestream.yml
COPY start.sh ./start.sh
RUN mkdir -p /data /media && chmod +x start.sh

CMD ["./start.sh"]
