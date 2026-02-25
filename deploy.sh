#!/bin/bash
set -e

REPO_DIR="/root/IBKR_investment_tracker"
DOMAIN="portfolio.srv1211053.hstgr.cloud"

echo "=== IBKR Portfolio Tracker - Deploy ==="

# 1. Pull latest code
echo ""
echo "--- Pulling latest code ---"
cd "$REPO_DIR"
git pull origin main

# 2. Ensure backend/.env exists
if [ ! -f backend/.env ]; then
    echo ""
    echo "--- backend/.env not found, creating from root .env ---"
    if [ -f .env ]; then
        cp .env backend/.env
        echo "Copied .env → backend/.env"
    else
        echo "ERROR: No .env file found. Create backend/.env with IBKR_TOKEN, IBKR_QUERY_ID, CORS_ORIGINS, DATABASE_URL"
        exit 1
    fi
fi

# 3. Build frontend (before docker compose, since frontend container mounts dist/)
echo ""
echo "--- Rebuilding frontend ---"
cd "$REPO_DIR/frontend"

# Install Node.js if not present
if ! command -v node &> /dev/null; then
    echo "Node.js not found, installing via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

npm ci
npm run build

# 4. Rebuild and restart Docker containers (backend + frontend nginx)
echo ""
echo "--- Rebuilding Docker containers ---"
cd "$REPO_DIR/backend"
docker compose down
docker compose build --no-cache
docker compose up -d

# 5. Status check
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "--- Docker status ---"
docker compose ps

echo ""
echo "--- Health check ---"
sleep 3
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/health" || true)
if [ "$HEALTH" = "200" ]; then
    echo "Backend health check: OK (200)"
else
    echo "Backend health check: FAILED (HTTP $HEALTH)"
    echo "Check logs: cd $REPO_DIR/backend && docker compose logs -f"
fi

SCHEDULER=$(curl -s "http://127.0.0.1:8000/api/scheduler/status" 2>/dev/null || true)
if [ -n "$SCHEDULER" ]; then
    echo "Scheduler status: $SCHEDULER"
fi

echo ""
echo "Visit: https://$DOMAIN"
echo "Logs:  cd $REPO_DIR/backend && docker compose logs -f"
