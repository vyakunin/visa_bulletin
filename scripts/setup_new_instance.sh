#!/bin/bash
# =============================================================================
# Complete Lightsail Instance Setup Script
# =============================================================================
#
# This script sets up a fresh Lightsail instance with all required components:
#   1. System packages and prerequisites
#   2. Docker and docker-compose
#   3. PostgreSQL with optimized settings
#   4. Swap and memory management
#   5. Monitoring tools (sysstat, atop, health checks)
#   6. Bazel memory limits
#   7. Project deployment
#
# Usage:
#   1. Launch a new Lightsail instance (Ubuntu 22.04, 2GB RAM recommended)
#   2. SSH into the instance
#   3. Clone the repository: git clone <repo-url> /opt/visa_bulletin
#   4. Run: cd /opt/visa_bulletin && ./scripts/setup_new_instance.sh
#
# Prerequisites:
#   - Ubuntu 22.04 LTS
#   - 2GB RAM minimum (4GB recommended)
#   - 60GB SSD minimum
#   - Root or sudo access
#
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTANCE_RAM_GB=2

echo "=============================================================="
echo "Visa Bulletin - New Instance Setup"
echo "=============================================================="
echo "Project root: $PROJECT_ROOT"
echo "Instance RAM: ${INSTANCE_RAM_GB}GB"
echo ""

# Check we're running as non-root with sudo access
if [[ "$EUID" -eq 0 ]]; then
    echo "ERROR: Do not run as root. Run as ubuntu user with sudo access."
    exit 1
fi

if ! sudo -n true 2>/dev/null; then
    echo "ERROR: This script requires sudo access"
    exit 1
fi

# =============================================================================
# Step 1: System Update and Prerequisites
# =============================================================================
echo ""
echo "[1/9] Installing system prerequisites..."
echo "--------------------------------------------------------------"

sudo apt update
sudo apt upgrade -y

# Essential packages
sudo apt install -y \
    curl \
    wget \
    git \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    certbot \
    python3-certbot-nginx \
    sysstat \
    atop \
    htop \
    jq

echo "✅ System prerequisites installed"

# Install Python dependencies for production web server
echo "Installing Python dependencies..."
cd "$PROJECT_ROOT"
pip3 install -r requirements.txt
echo "✅ Python dependencies installed (including gunicorn)"

# =============================================================================
# Step 2: Configure Swap
# =============================================================================
echo ""
echo "[2/9] Configuring swap..."
echo "--------------------------------------------------------------"

SWAP_SIZE=$((INSTANCE_RAM_GB * 1024))  # Match RAM size in MB
SWAPFILE="/swapfile"

if [[ ! -f "$SWAPFILE" ]]; then
    echo "Creating ${SWAP_SIZE}MB swap file..."
    sudo fallocate -l ${SWAP_SIZE}M "$SWAPFILE"
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap "$SWAPFILE"
    sudo swapon "$SWAPFILE"
    
    # Make permanent
    if ! grep -q "$SWAPFILE" /etc/fstab; then
        echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab
    fi
    echo "✅ Swap file created"
else
    echo "✅ Swap file already exists"
fi

# Set swappiness
echo "Setting vm.swappiness=60..."
sudo sysctl vm.swappiness=60
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=60" | sudo tee -a /etc/sysctl.conf
else
    sudo sed -i 's/vm.swappiness=.*/vm.swappiness=60/' /etc/sysctl.conf
fi

echo "✅ Swap configured"

# =============================================================================
# Step 3: Install Docker
# =============================================================================
echo ""
echo "[3/9] Installing Docker..."
echo "--------------------------------------------------------------"

if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    rm get-docker.sh
    sudo usermod -aG docker "$USER"
    echo "✅ Docker installed"
else
    echo "✅ Docker already installed"
fi

# Install docker-compose
if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "✅ docker-compose installed"
else
    echo "✅ docker-compose already installed"
fi

# =============================================================================
# Step 4: Install PostgreSQL
# =============================================================================
echo ""
echo "[4/9] Installing and configuring PostgreSQL..."
echo "--------------------------------------------------------------"

sudo apt install -y postgresql postgresql-contrib

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create custom config for bulk operations
CUSTOM_CONF="/etc/postgresql/14/main/conf.d/custom.conf"
sudo mkdir -p "$(dirname "$CUSTOM_CONF")"

sudo tee "$CUSTOM_CONF" > /dev/null << 'EOF'
# PostgreSQL Configuration for 2GB Lightsail Instance
# Optimized for bulk ingest operations

# Memory Settings (tuned for 2GB, reduced to relieve memory pressure)
shared_buffers = 128MB
work_mem = 2MB
maintenance_work_mem = 32MB
effective_cache_size = 512MB

# Parallel Workers (reduced for 2GB instance)
max_parallel_workers_per_gather = 1
max_parallel_workers = 2
max_parallel_maintenance_workers = 1

# Connection Limits
max_connections = 20

# Checkpoint Settings (spread I/O)
checkpoint_completion_target = 0.9
checkpoint_timeout = 10min
max_wal_size = 1GB

# Background Writer (reduced activity)
bgwriter_delay = 500ms
bgwriter_lru_maxpages = 100

# Autovacuum (less aggressive for bulk ops)
autovacuum_max_workers = 1
autovacuum_naptime = 5min
autovacuum_vacuum_cost_delay = 20ms

# WAL Settings
wal_compression = on

# Logging
log_min_duration_statement = 1000
log_checkpoints = on
EOF

# Ensure conf.d is included
PG_CONF="/etc/postgresql/14/main/postgresql.conf"
if ! grep -q "include_dir = 'conf.d'" "$PG_CONF"; then
    echo "include_dir = 'conf.d'" | sudo tee -a "$PG_CONF"
fi

# Allow Docker containers to connect (host.docker.internal; Docker uses 172.17.x and 172.18.x)
echo "listen_addresses = '*'" | sudo tee /etc/postgresql/14/main/conf.d/docker_listen.conf
PG_HBA="/etc/postgresql/14/main/pg_hba.conf"
for net in 172.17.0.0/16 172.18.0.0/16; do
    if ! sudo grep -q "$net" "$PG_HBA"; then
        echo "host    all    all    $net    scram-sha-256" | sudo tee -a "$PG_HBA"
    fi
done

sudo systemctl restart postgresql

echo "✅ PostgreSQL configured"

# =============================================================================
# Step 4b: Install Redis (shared cache for employer profile and salary pages)
# =============================================================================
echo ""
echo "[4b/9] Installing Redis..."
echo "--------------------------------------------------------------"

sudo apt install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
echo "✅ Redis installed and enabled (redis://127.0.0.1:6379)"

# =============================================================================
# Step 5: Create Database User and Databases
# =============================================================================
echo ""
echo "[5/9] Creating database user and databases..."
echo "--------------------------------------------------------------"

DB_USER="visa_bulletin_user"
DB_NAME="visa_bulletin"

# Generate password if not provided
if [[ -z "${DB_PASSWORD:-}" ]]; then
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    echo ""
    echo "⚠️  IMPORTANT: Save this database password!"
    echo "   DB_PASSWORD=$DB_PASSWORD"
    echo ""
fi

# Create user
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null || echo "0")
if [[ "$USER_EXISTS" != "1" ]]; then
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
    echo "Created user: $DB_USER"
fi

# Create single database (instance rotation: one DB per instance)
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "0")
if [[ "$DB_EXISTS" != "1" ]]; then
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
    echo "Created database: $DB_NAME"
fi

# Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"
sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;"
sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;"

echo "✅ Database created"

# =============================================================================
# Step 6: Configure Monitoring
# =============================================================================
echo ""
echo "[6/9] Setting up monitoring..."
echo "--------------------------------------------------------------"

# Enable sysstat (enable/start can hang in non-interactive - use timeout)
sudo sed -i 's/ENABLED="false"/ENABLED="true"/' /etc/default/sysstat
timeout 20 sudo systemctl enable sysstat 2>/dev/null || true
timeout 10 sudo systemctl start sysstat 2>/dev/null || true

# Enable and start atop (can hang in non-interactive/no-TTY - use timeout)
timeout 20 sudo systemctl enable atop 2>/dev/null || true
timeout 15 sudo systemctl start atop 2>/dev/null || true

# Ensure health check script exists and add to cron (every 5 min)
HEALTH_SCRIPT="$PROJECT_ROOT/scripts/health_check.sh"
if [[ ! -f "$HEALTH_SCRIPT" ]]; then
    echo "ERROR: $HEALTH_SCRIPT not found (expected in repo)"
    exit 1
fi
chmod +x "$HEALTH_SCRIPT"
(sudo crontab -l 2>/dev/null | grep -v health_check; echo "*/5 * * * * $HEALTH_SCRIPT") | sudo crontab -

echo "✅ Monitoring configured"

# =============================================================================
# Step 6b: Install Bazel (Bazelisk) if not present
# =============================================================================
if ! command -v bazel &>/dev/null; then
    echo ""
    echo "[6b/9] Installing Bazel (Bazelisk)..."
    echo "--------------------------------------------------------------"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64) BAZELISK_ARCH=amd64 ;;
        aarch64|arm64) BAZELISK_ARCH=arm64 ;;
        *) echo "⚠️  Unsupported arch $ARCH for Bazelisk; install Bazel manually"; BAZELISK_ARCH= ;;
    esac
    if [[ -n "$BAZELISK_ARCH" ]]; then
        BAZELISK_VERSION="v1.19.0"
        sudo wget -q -O /usr/local/bin/bazel "https://github.com/bazelbuild/bazelisk/releases/download/${BAZELISK_VERSION}/bazelisk-linux-${BAZELISK_ARCH}" || true
        if [[ -f /usr/local/bin/bazel ]]; then
            sudo chmod +x /usr/local/bin/bazel
            echo "✅ Bazel (Bazelisk) installed at /usr/local/bin/bazel"
        else
            echo "⚠️  Bazelisk download failed; install Bazel manually for build_all.sh and refresh_data.sh"
        fi
    fi
fi

# =============================================================================
# Step 7: Configure Bazel Memory Limits
# =============================================================================
echo ""
echo "[7/9] Configuring Bazel memory limits..."
echo "--------------------------------------------------------------"

BAZELRC="$PROJECT_ROOT/.bazelrc"

# Check if memory limits already exist
if ! grep -q "local_ram_resources" "$BAZELRC" 2>/dev/null; then
    cat >> "$BAZELRC" << 'BAZEL_EOF'

# ============================================================================
# Memory Limits for 2GB Instance (CRITICAL - prevents OOM)
# ============================================================================
build --local_ram_resources=1024
build --jobs=2
build --worker_max_instances=1
BAZEL_EOF
    echo "✅ Bazel memory limits added to .bazelrc"
else
    echo "✅ Bazel memory limits already configured"
fi

# =============================================================================
# Step 8: Create Environment File Template
# =============================================================================
# DB_PASSWORD from step 5 is written here so .env is the single source of truth.
# No need to save the password elsewhere unless you want a backup (e.g. password manager).
echo ""
echo "[8/9] Creating environment file..."
echo "--------------------------------------------------------------"

ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    # Include instance public IP in ALLOWED_HOSTS so external access works (Docker/nginx)
    PUBLIC_IP=""
    if command -v curl &>/dev/null; then
        PUBLIC_IP=$(timeout 3 curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)
        [[ -z "$PUBLIC_IP" ]] && PUBLIC_IP=$(timeout 3 curl -s --connect-timeout 2 https://ifconfig.me 2>/dev/null || true)
    fi
    ALLOWED_HOSTS_VALUE="localhost,127.0.0.1"
    if [[ -n "$PUBLIC_IP" ]]; then
        ALLOWED_HOSTS_VALUE="$ALLOWED_HOSTS_VALUE,$PUBLIC_IP"
        echo "   Detected public IP: $PUBLIC_IP (added to ALLOWED_HOSTS)"
    fi
    cat > "$ENV_FILE" << ENV_EOF
# Database Configuration
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
# localhost: Host-based services (Gunicorn, Bazel scripts) connect to PostgreSQL on localhost
DB_HOST=localhost
DB_PORT=5432

# Shared cache (employer profile, salary search). Omit for local-only LocMem cache.
REDIS_URL=redis://127.0.0.1:6379/1

# Django Settings
DEBUG=False
SECRET_KEY=$(openssl rand -base64 32)
ALLOWED_HOSTS=$ALLOWED_HOSTS_VALUE

# Add your domain here after setup: append to ALLOWED_HOSTS (e.g. visa-bulletin.us)
ENV_EOF
    echo "✅ Created .env file (DB password from step 5 saved here)"
    if [[ -z "$PUBLIC_IP" ]]; then
        echo "⚠️  Update ALLOWED_HOSTS in .env with this instance's public IP for external access"
    fi
else
    echo "✅ .env file already exists"
fi

# =============================================================================
# Step 8b: Orchestrator (instance-rotation refresh) setup
# =============================================================================
# For prod->staging refresh_and_switch: SSH key for staging + AWS credentials for Lightsail.
echo ""
echo "[8b/9] Orchestrator (instance-rotation refresh) setup..."
echo "--------------------------------------------------------------"

# AWS CLI required for Lightsail (get_instance_state, start/stop instance)
if ! command -v aws &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y awscli
    echo "✅ AWS CLI installed"
else
    echo "✅ AWS CLI already installed"
fi

# Ensure .ssh exists for SSH key used by refresh_and_switch (REFRESH_SSH_KEY_PATH)
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh" 2>/dev/null || true

# Append REFRESH_* and AWS placeholders to .env if not already present
if [[ -f "$ENV_FILE" ]] && ! grep -q "REFRESH_SSH_KEY_PATH" "$ENV_FILE" 2>/dev/null; then
    cat >> "$ENV_FILE" << 'REFRESH_EOF'

# Orchestrator (instance-rotation refresh): prod -> staging. Uncomment and set for refresh_and_switch.py
# REFRESH_ACTIVE_INSTANCE_NAME=VisaBulletin2GB
# REFRESH_ACTIVE_INSTANCE_IP=44.209.204.255
# REFRESH_INACTIVE_INSTANCE_NAME=VisaBulletinStaging
# REFRESH_INACTIVE_INSTANCE_IP=54.196.241.197
# REFRESH_MY_INSTANCE_NAME=VisaBulletin2GB
# REFRESH_SSH_USER=ubuntu
# REFRESH_SSH_KEY_PATH=/home/ubuntu/.ssh/lightsail_visa_bulletin
# REFRESH_REMOTE_PROJECT_ROOT=/opt/visa_bulletin
# REFRESH_REMOTE_DB_NAME=visa_bulletin
# Private IPs for inter-instance SSH (Lightsail instances cannot reach each other via public IPs).
# Get from Lightsail console → instance → Networking → Private IP. These survive stop/start.
# The orchestrator swaps these automatically on graduation so the next cycle has the right values.
# REFRESH_ACTIVE_PRIVATE_IP=172.26.x.x    # Private IP of the active (prod) instance
# REFRESH_INACTIVE_PRIVATE_IP=172.26.x.x  # Private IP of the inactive (staging) instance
# Lightsail static IP names (required for graduation). Get from: aws lightsail get-static-ips --region us-east-1
# REFRESH_STATIC_IP_NAME=    # Prod static IP name (traffic switch attaches this to new prod)
# REFRESH_STAGING_STATIC_IP_NAME=    # Staging static IP name (reattached to old prod after graduation so staging is reachable)
# AWS: for Lightsail start/stop (if staging is stopped). Put credentials on this instance:
#   - Copy from your machine: scp ~/.aws/credentials this-host:~/.aws/ (then set AWS_PROFILE below), or
#   - On this instance: aws configure (or create IAM key and set AWS_ACCESS_KEY_ID/SECRET in .env).
# AWS_PROFILE=visa-bulletin-deploy
# Or: AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=us-east-1
REFRESH_EOF
    echo "✅ Added REFRESH_* and AWS placeholders to .env (commented); copy SSH key to REFRESH_SSH_KEY_PATH and put AWS credentials on this instance (copy from your machine or aws configure)"
else
    echo "✅ Orchestrator env already present or .env not created by this run"
fi

# =============================================================================
# Step 9: Configure Nginx and Production Web Server
# =============================================================================
echo ""
echo "[9/9] Configuring Nginx and production web server..."
echo "--------------------------------------------------------------"

# Copy nginx configuration
sudo cp deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
sudo cp deployment/nginx/visa-bulletin-locations.conf /opt/visa_bulletin/deployment/nginx/
sudo cp deployment/nginx/rate-limiting.conf /opt/visa_bulletin/deployment/nginx/
# Log format (response time) and GPTBot rate limit (http context)
sudo cp deployment/nginx/visa-bulletin-log-format.conf /etc/nginx/conf.d/
sudo cp deployment/nginx/gptbot-rate-limit.conf /etc/nginx/conf.d/
# Default server block so app is reachable by IP (staging health checks, orchestrator smoke test).
# IMPORTANT: copy from repo, never create manually — nginx does not use shell escaping,
# so \$host in a heredoc/echo becomes a literal backslash in the header (Django rejects it).
sudo cp deployment/nginx/default-server.conf /etc/nginx/sites-enabled/default-server

# Enable site
sudo ln -sf /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
if sudo nginx -t; then
    echo "✅ Nginx configuration valid"
    sudo systemctl restart nginx
    sudo systemctl enable nginx
else
    echo "❌ Nginx configuration error"
    exit 1
fi

# Create systemd service for Gunicorn
echo "Creating systemd service for production web server..."
sudo cp deployment/systemd/visa-bulletin-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable visa-bulletin-web
echo "✅ Systemd service configured (not started yet - see next steps)"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "=============================================================="
echo "Instance Setup Complete!"
echo "=============================================================="
echo ""
echo "What was configured:"
echo "  ✅ System packages and prerequisites"
echo "  ✅ Python dependencies (including gunicorn)"
echo "  ✅ ${SWAP_SIZE}MB swap file (swappiness=60)"
echo "  ✅ Docker and docker-compose"
echo "  ✅ PostgreSQL (optimized for bulk operations)"
echo "  ✅ Redis (shared cache for employer/salary pages)"
echo "  ✅ Database: $DB_NAME"
echo "  ✅ Monitoring: sysstat, atop, health_check.sh"
echo "  ✅ Bazel memory limits"
echo "  ✅ Nginx reverse proxy"
echo "  ✅ Systemd service for production web server"
echo ""
echo "Database credentials:"
echo "  User: $DB_USER"
echo "  Password: $DB_PASSWORD"
echo ""
echo "Next steps:"
echo "  1. Log out and back in (for docker group)"
echo "  2. If external access returns 400: ensure ALLOWED_HOSTS in .env includes this instance's public IP"
echo "  3. Update deployment/nginx/visa-bulletin-nginx.conf with your domain"
echo "  4. Run: ./scripts/cron/build_all.sh  (pre-build Bazel binaries)"
echo "  5. Run: ./scripts/cron/refresh_data.sh  (migrations + full data ingest; first run loads everything)"
echo "  6. Start app with Docker: docker-compose -f deployment/docker-compose.yml up -d"
echo "  7. Verify: curl -I http://localhost/"
echo "  8. Setup SSL: sudo certbot --nginx -d your-domain.com"
echo "  9. Set up cron jobs: bash deployment/cron/setup-ingest-cron.sh"
echo "  10. Open AWS firewall ports 80 and 443 (Lightsail: instance Networking)"
echo "  11. For instance-rotation refresh: copy AWS credentials to this instance (e.g. scp ~/.aws/credentials from your machine to this host), uncomment REFRESH_* and AWS_* in .env, copy SSH key to REFRESH_SSH_KEY_PATH"
echo ""
echo "Data loading:"
echo "  - refresh_data.sh: Migrations + visa bulletin + DOL data (run once for initial load, then weekly via cron)"
echo ""
echo "Web server (Docker):"
echo "  Start:   docker-compose -f deployment/docker-compose.yml up -d"
echo "  Stop:    docker-compose -f deployment/docker-compose.yml down"
echo "  Logs:    docker-compose -f deployment/docker-compose.yml logs -f"
echo ""
echo "For detailed instructions, see: docs/deployment/NEW_INSTANCE_SETUP.md"
echo ""

# =============================================================================
# Step 10: Start application with Docker (no manual step required)
# =============================================================================
echo "--------------------------------------------------------------"
echo "Starting application with Docker..."
echo "--------------------------------------------------------------"
cd "$PROJECT_ROOT"
# Use sg docker so docker group is active without requiring logout
if sg docker -c "docker-compose -f deployment/docker-compose.yml pull && docker-compose -f deployment/docker-compose.yml up -d" 2>/dev/null; then
    echo "✅ Docker application started (blue on port 8000)"
    echo "   Verify: curl -I http://localhost:8000/"
else
    echo "⚠️  Docker start failed (e.g. permission - need to log out and back in for docker group)"
    echo "   After re-login, run: cd $PROJECT_ROOT && docker-compose -f deployment/docker-compose.yml up -d"
fi
echo ""

# =============================================================================
# Step 11: Set up cron jobs (hourly bulletin refresh + weekly full refresh)
# =============================================================================
echo "--------------------------------------------------------------"
echo "Setting up cron jobs..."
echo "--------------------------------------------------------------"
cd "$PROJECT_ROOT"
mkdir -p /var/log/visa-bulletin 2>/dev/null || sudo mkdir -p /var/log/visa-bulletin
sudo chown "$USER:$USER" /var/log/visa-bulletin 2>/dev/null || true
bash deployment/cron/setup-ingest-cron.sh
echo "Note: Cron entries are installed. The bulletin refresh binary must be built"
echo "  before the hourly cron will work (run: ./scripts/cron/build_all.sh)"
echo ""
