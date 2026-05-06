#!/bin/bash
# ============================================================================
# Strange Street — Deploy / Update Script
# Run this to deploy or update the app on your OCI VM.
# Usage: sudo bash deploy/deploy.sh
# ============================================================================

set -euo pipefail

APP_DIR="/opt/strangestreet"
APP_USER="strangestreet"
REPO_URL="https://github.com/kamaleshpantra/strangestreet.git"  # UPDATE THIS
BRANCH="main"

echo "============================================"
echo "  Strange Street — Deploying..."
echo "============================================"

# ── 1. Pull latest code ─────────────────────────────────────────────────────
echo ">>> [1/5] Pulling latest code..."
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin
    sudo -u "$APP_USER" git reset --hard "origin/$BRANCH"
else
    # First-time clone
    rm -rf "$APP_DIR/tmp_clone"
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR/tmp_clone"
    cp -a "$APP_DIR/tmp_clone/." "$APP_DIR/"
    rm -rf "$APP_DIR/tmp_clone"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
fi

# ── 2. Set up Python virtual environment ────────────────────────────────────
echo ">>> [2/5] Setting up Python environment..."
if [ ! -d "$APP_DIR/venv" ]; then
    sudo -u "$APP_USER" python3.11 -m venv "$APP_DIR/venv"
fi
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# ── 3. Create upload directories ────────────────────────────────────────────
echo ">>> [3/5] Creating directories..."
sudo -u "$APP_USER" mkdir -p \
    "$APP_DIR/app/static/uploads/posts" \
    "$APP_DIR/app/static/uploads/avatars" \
    "$APP_DIR/app/static/uploads/zones" \
    "$APP_DIR/app/static/uploads/stories" \
    "$APP_DIR/app/static/uploads/messages"

# ── 4. Run database migrations ──────────────────────────────────────────────
echo ">>> [4/5] Running database migrations..."
cd "$APP_DIR"
sudo -u "$APP_USER" bash -c "source $APP_DIR/venv/bin/activate && source $APP_DIR/.env.sh && python -m alembic upgrade head"

# ── 5. Restart services ─────────────────────────────────────────────────────
echo ">>> [5/5] Restarting services..."
systemctl restart strangestreet
systemctl enable strangestreet
systemctl enable strangestreet-ml.timer
systemctl start strangestreet-ml.timer

echo ""
echo "============================================"
echo "  ✅ Deployment complete!"
echo "============================================"
echo "  App:    http://$(curl -s ifconfig.me)"
echo "  Status: systemctl status strangestreet"
echo "  Logs:   journalctl -u strangestreet -f"
echo "============================================"
