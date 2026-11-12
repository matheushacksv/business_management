#!/bin/sh
set -e
until mc alias set local http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"; do
    echo "Waiting MinIO..."
    sleep 1
done
mc mb --ignore-existing "local/$MINIO_BUCKET_NAME"
