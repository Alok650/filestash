#!/bin/sh

if [ -f .env ]; then
    export $(echo $(grep -v '^#' .env | xargs))
elif [ -f ../.env ]; then
    export $(echo $(grep -v '^#' ../.env | xargs))
fi

PYTHON=$(which python3 || which python)

mkdir -p ./data
chmod -R 777 ./data 2>/dev/null || true

echo "Running migrations..."
$PYTHON manage.py migrate --noinput

if [ -z "$ADMIN_API_KEY" ]; then
    echo "WARNING: ADMIN_API_KEY is not set. You will not be able to manage API keys."
fi

if command -v gunicorn >/dev/null 2>&1; then
    echo "Starting server with Gunicorn..."
    exec gunicorn --bind 0.0.0.0:8000 \
        --workers 4 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        core.wsgi:application
else
    echo "Gunicorn not found, falling back to manage.py runserver..."
    exec $PYTHON manage.py runserver 0.0.0.0:8000
fi