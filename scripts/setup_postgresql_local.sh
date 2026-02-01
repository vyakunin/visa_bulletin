#!/bin/bash
# Setup PostgreSQL locally for development
# Creates database and user for local development

set -e

echo "=========================================="
echo "PostgreSQL Local Setup"
echo "=========================================="
echo

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo "PostgreSQL not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install postgresql@15
        brew services start postgresql@15
        export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt update
        sudo apt install -y postgresql postgresql-contrib
        sudo systemctl start postgresql
    else
        echo "Unsupported OS. Please install PostgreSQL manually."
        exit 1
    fi
fi

# Check if PostgreSQL is running
if ! pg_isready &> /dev/null; then
    echo "Starting PostgreSQL..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew services start postgresql@15
        sleep 2
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo systemctl start postgresql
        sleep 2
    fi
fi

# Database configuration
DB_NAME="${DB_NAME:-visa_bulletin_dev}"
DB_USER="${DB_USER:-visa_bulletin_user}"
DB_PASSWORD="${DB_PASSWORD:-dev_password}"

echo "Creating database and user..."
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"
echo

# Determine PostgreSQL superuser and admin database
if [[ "$OSTYPE" == "darwin"* ]]; then
    PG_SUPERUSER="${USER}"
    PG_ADMIN_DB="template1"  # Use template1 for admin operations (always exists)
    # Add PostgreSQL to PATH if needed
    export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"
else
    PG_SUPERUSER="postgres"
    PG_ADMIN_DB="postgres"
fi

# Create database (if not exists)
psql -U "$PG_SUPERUSER" -d "$PG_ADMIN_DB" -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    psql -U "$PG_SUPERUSER" -d "$PG_ADMIN_DB" -c "CREATE DATABASE $DB_NAME;"

# Create user (if not exists)
psql -U "$PG_SUPERUSER" -d "$PG_ADMIN_DB" -tc "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'" | grep -q 1 || \
    psql -U "$PG_SUPERUSER" -d "$PG_ADMIN_DB" -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"

# Grant privileges
psql -U "$PG_SUPERUSER" -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
psql -U "$PG_SUPERUSER" -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"

echo "PostgreSQL setup complete!"
echo
echo "Connection string:"
echo "  postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"
echo
echo "To use with Django:"
echo "  export DB_ENGINE=postgresql"
echo "  export DB_NAME=$DB_NAME"
echo "  export DB_USER=$DB_USER"
echo "  export DB_PASSWORD=$DB_PASSWORD"
echo "  bazel run //:migrate"










