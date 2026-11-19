#!/bin/sh

set -e
# The database may be restarting during a stack deploy: wait for it (up to ~60s) instead of failing the task
i=0
until python manage.py migrate --noinput; do
  i=$((i + 1))
  [ "$i" -ge 12 ] && exit 1
  echo "Database not ready, retrying in 5s ($i/12)"
  sleep 5
done
python manage.py collectstatic --noinput
exec gunicorn core.wsgi:application --workers 2 --threads 16 --timeout 120 --bind 0.0.0.0:8000
