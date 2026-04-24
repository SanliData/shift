#!/usr/bin/env bash
# DigitalOcean Ubuntu — path: /var/www/shift
# Run: chmod +x scripts/deploy.sh && APP_ROOT=/var/www/shift ./scripts/deploy.sh

APP_ROOT="${APP_ROOT:-/var/www/shift}"
cd "$APP_ROOT"

git pull
source .venv/bin/activate
pip install -r requirements-prod.txt

pkill -f uvicorn || true

nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 > shift.log 2>&1 &
