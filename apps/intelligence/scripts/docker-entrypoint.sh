#!/bin/sh
set -e

# Default to running the API if no argument is provided
ROLE=${1:-"api"}

if [ "$ROLE" = "api" ]; then
    echo "Starting Cadence Intelligence API..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$ROLE" = "worker" ]; then
    echo "Starting Cadence Intelligence Stream Worker..."
    exec python -m app.workers.stream_worker
else
    echo "Unknown role: $ROLE. Expected 'api' or 'worker'."
    exit 1
fi
