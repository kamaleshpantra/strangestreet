#!/bin/bash
# ============================================================================
# Strange Street — SSL Setup Script
# Run AFTER deploy.sh and AFTER you've pointed a domain to your VM's IP.
# Usage: sudo bash deploy/setup-ssl.sh yourdomain.com
# ============================================================================

set -euo pipefail

DOMAIN="${1:?Usage: sudo bash deploy/setup-ssl.sh yourdomain.com}"

echo "============================================"
echo "  Setting up SSL for: $DOMAIN"
echo "============================================"

# Update Nginx config with the domain
sed -i "s/server_name _;/server_name $DOMAIN;/" /etc/nginx/sites-available/strangestreet
nginx -t && systemctl reload nginx

# Get SSL certificate from Let's Encrypt
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" --redirect

# Auto-renewal (certbot installs a timer by default, verify it)
systemctl enable certbot.timer
systemctl start certbot.timer

echo ""
echo "============================================"
echo "  ✅ SSL configured!"
echo "  Your app is now live at: https://$DOMAIN"
echo "============================================"
