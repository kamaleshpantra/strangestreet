#!/bin/bash
# ============================================================================
# Strange Street — Environment File Generator
# Run this on the OCI VM to create the .env file
# Usage: bash deploy/create-env.sh
# ============================================================================

APP_DIR="/opt/strangestreet"

echo "============================================"
echo "  Strange Street — Environment Setup"
echo "============================================"
echo ""

# Generate secure keys
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || echo "GENERATE_AFTER_INSTALL")

read -p "Database URL (from oci-setup.sh output): " DB_URL
read -p "Cloudinary Cloud Name (or press Enter to skip): " CLOUD_NAME
read -p "Cloudinary API Key (or press Enter to skip): " CLOUD_KEY
read -p "Cloudinary API Secret (or press Enter to skip): " CLOUD_SECRET

# Create .env file
cat > "$APP_DIR/.env" <<EOF
# Strange Street — Production Environment (OCI)

# Database
DATABASE_URL=$DB_URL

# Security
SECRET_KEY=$SECRET_KEY
ENCRYPTION_KEY=$ENCRYPTION_KEY

# Application
DEBUG=false
MAX_UPLOAD_SIZE_MB=10

# Cloudinary
CLOUDINARY_CLOUD_NAME=$CLOUD_NAME
CLOUDINARY_API_KEY=$CLOUD_KEY
CLOUDINARY_API_SECRET=$CLOUD_SECRET
EOF

# Also create a sourceable version for shell scripts
cat > "$APP_DIR/.env.sh" <<EOF
#!/bin/bash
export DATABASE_URL="$DB_URL"
export SECRET_KEY="$SECRET_KEY"
export ENCRYPTION_KEY="$ENCRYPTION_KEY"
export DEBUG="false"
export MAX_UPLOAD_SIZE_MB="10"
export CLOUDINARY_CLOUD_NAME="$CLOUD_NAME"
export CLOUDINARY_API_KEY="$CLOUD_KEY"
export CLOUDINARY_API_SECRET="$CLOUD_SECRET"
EOF

chmod 600 "$APP_DIR/.env" "$APP_DIR/.env.sh"

echo ""
echo "✅ Environment files created at:"
echo "   $APP_DIR/.env"
echo "   $APP_DIR/.env.sh"
