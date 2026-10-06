#!/bin/sh
set -e
echo "Starting RQ Worker..."
exec python -m worker.main
