#!/bin/bash
# ============================================================================
# Strange Street — OCI VM Setup Script (Ubuntu 22.04 / 24.04)
# Run this ONCE on a fresh OCI Always Free ARM instance.
# Usage: sudo bash oci-setup.sh
# ============================================================================

set -euo pipefail

APP_USER="strangestreet"
APP_DIR="/opt/strangestreet"
DB_NAME="strangestreet"
DB_USER="strangestreet"
DB_PASS=$(openssl rand -base64 24 | tr -d '=+/')

echo "============================================"
echo "  Strange Street — OCI Server Setup"
echo "============================================"

# ── 1. System Update ─────────────────────────────────────────────────────────
echo ">>> [1/8] Updating system packages..."
apt-get update && apt-get upgrade -y

# ── 2. Install Core Dependencies ─────────────────────────────────────────────
echo ">>> [2/8] Installing core dependencies..."
apt-get install -y \
    software-properties-common \
    build-essential \
    libpq-dev \
    curl \
    git \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw \
    unzip

# ── 3. Install Python 3.11 ──────────────────────────────────────────────────
echo ">>> [3/8] Installing Python 3.11..."
add-apt-repository ppa:deadsnakes/ppa -y
apt-get update
apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# ── 4. Install PostgreSQL 15 ────────────────────────────────────────────────
echo ">>> [4/8] Installing PostgreSQL 15..."
apt-get install -y postgresql postgresql-contrib

# Start PostgreSQL
systemctl enable postgresql
systemctl start postgresql

# Create database and user
echo ">>> Creating database: $DB_NAME, user: $DB_USER"
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || echo "User already exists"
sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || echo "Database already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
sudo -u postgres psql -c "ALTER USER $DB_USER CREATEDB;"

# ── 5. Create App User & Directory ──────────────────────────────────────────
echo ">>> [5/8] Setting up application directory..."
useradd --system --shell /bin/bash --home "$APP_DIR" "$APP_USER" 2>/dev/null || echo "User already exists"
mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

# ── 6. Configure Firewall ───────────────────────────────────────────────────
echo ">>> [6/8] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 7. Configure Nginx ──────────────────────────────────────────────────────
echo ">>> [7/8] Configuring Nginx..."
cat > /etc/nginx/sites-available/strangestreet <<'NGINX_CONF'
server {
    listen 80;
    server_name _;

    client_max_body_size 15M;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (for real-time features)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeout settings
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }

    # Cache static files
    location /static/ {
        alias /opt/strangestreet/app/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
NGINX_CONF

ln -sf /etc/nginx/sites-available/strangestreet /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# ── 8. Create systemd Services ──────────────────────────────────────────────
echo ">>> [8/8] Creating systemd services..."

# Main app service
cat > /etc/systemd/system/strangestreet.service <<EOF
[Unit]
Description=Strange Street FastAPI Application
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

# Resource limits (generous for ML workloads)
MemoryMax=8G
CPUQuota=300%

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=strangestreet

[Install]
WantedBy=multi-user.target
EOF

# ML Pipeline timer (runs daily at 2 AM)
cat > /etc/systemd/system/strangestreet-ml.service <<EOF
[Unit]
Description=Strange Street ML Pipeline
After=network.target postgresql.service

[Service]
Type=oneshot
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin:/usr/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python ml/run_pipeline.py
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/strangestreet-ml.timer <<EOF
[Unit]
Description=Run Strange Street ML Pipeline daily at 2 AM

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  ✅ Server setup complete!"
echo "============================================"
echo ""
echo "  SAVE THESE CREDENTIALS:"
echo "  ────────────────────────"
echo "  Database Name:     $DB_NAME"
echo "  Database User:     $DB_USER"
echo "  Database Password: $DB_PASS"
echo "  Database URL:      postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME"
echo ""
echo "  Next step: Run 'deploy.sh' to deploy the app"
echo "============================================"
