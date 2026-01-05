#!/bin/bash
# Setup PostgreSQL on Lightsail production server
# Run this script on the production server

set -e

echo "=========================================="
echo "PostgreSQL Production Setup (Lightsail)"
echo "=========================================="
echo

# Update system
echo "Step 1: Updating system packages..."
sudo apt update
sudo apt upgrade -y

# Install PostgreSQL
echo "Step 2: Installing PostgreSQL..."
sudo apt install -y postgresql postgresql-contrib

# Start and enable PostgreSQL
echo "Step 3: Starting PostgreSQL service..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Get database configuration from environment or prompt
DB_NAME="${DB_NAME:-visa_bulletin}"
DB_USER="${DB_USER:-visa_bulletin_user}"

if [ -z "$DB_PASSWORD" ]; then
    # Generate a secure random password if not provided
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    echo "Generated secure password for user '$DB_USER'"
    echo "⚠️  IMPORTANT: Save this password - it won't be shown again!"
    echo "   Password: $DB_PASSWORD"
    echo ""
fi

# Create database
echo "Step 4: Creating database and user..."
sudo -u postgres psql << EOF
-- Create database
CREATE DATABASE $DB_NAME;

-- Create user
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connect to database and grant schema privileges
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;
EOF

# Configure PostgreSQL for Lightsail (1 GB RAM)
echo "Step 5: Tuning PostgreSQL for 1 GB RAM instance..."
sudo -u postgres psql -d "$DB_NAME" << EOF
-- Memory settings for 1 GB RAM instance
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '768MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET max_connections = '50';
EOF

# Reload PostgreSQL configuration
sudo systemctl reload postgresql

# Verify setup
echo "Step 6: Verifying setup..."
sudo -u postgres psql -d "$DB_NAME" -c "SELECT version();"
sudo -u postgres psql -d "$DB_NAME" -c "\dt" || echo "No tables yet (run migrations first)"

echo
echo "=========================================="
echo "PostgreSQL Setup Complete"
echo "=========================================="
echo
echo "Database: $DB_NAME"
echo "User: $DB_USER"
echo "Host: localhost"
echo "Port: 5432"
echo
echo "To use with Django, set environment variables:"
echo "  export DB_ENGINE=postgresql"
echo "  export DB_NAME=$DB_NAME"
echo "  export DB_USER=$DB_USER"
echo "  export DB_PASSWORD='<password>'"
echo "  export DB_HOST=localhost"
echo "  export DB_PORT=5432"
echo
echo "Next steps:"
echo "  1. Run migrations: bazel run //:migrate"
echo "  2. Import data from SQLite (if migrating)"
echo "  3. Test connection and ingest pipeline"










