#!/bin/bash
# Setup PostgreSQL on Lightsail production server (2GB instance)
# Run this script on the production server after initial OS setup
#
# This script:
#   1. Installs and configures PostgreSQL
#   2. Creates blue-green databases
#   3. Tunes settings for 2GB instance with bulk operations
#   4. Sets up swap and monitoring tools
#
# Usage: ./setup_postgresql_production.sh

set -euo pipefail

echo "=========================================="
echo "PostgreSQL Production Setup (Lightsail 2GB)"
echo "=========================================="
echo

# Configuration
INSTANCE_RAM_GB=2
DB_BLUE="visa_bulletin_blue"
DB_GREEN="visa_bulletin_green"
DB_USER="${DB_USER:-visa_bulletin_user}"

# =============================================================================
# Step 1: System Prerequisites
# =============================================================================
echo "Step 1: Installing system prerequisites..."

sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Install monitoring tools
echo "Installing monitoring tools (sysstat, atop)..."
sudo apt install -y sysstat atop

# Enable sysstat
sudo sed -i 's/ENABLED="false"/ENABLED="true"/' /etc/default/sysstat
sudo systemctl enable sysstat
sudo systemctl start sysstat

# Enable atop
sudo systemctl enable atop
sudo systemctl start atop

# =============================================================================
# Step 2: Configure Swap (prevents OOM)
# =============================================================================
echo "Step 2: Configuring swap..."

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
else
    echo "Swap file already exists"
fi

# Set swappiness to 60 (encourage swapping before OOM)
echo "Setting vm.swappiness=60..."
sudo sysctl vm.swappiness=60
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=60" | sudo tee -a /etc/sysctl.conf
else
    sudo sed -i 's/vm.swappiness=.*/vm.swappiness=60/' /etc/sysctl.conf
fi

# =============================================================================
# Step 3: Start PostgreSQL
# =============================================================================
echo "Step 3: Starting PostgreSQL service..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# =============================================================================
# Step 4: Create Database User
# =============================================================================
echo "Step 4: Creating database user..."

if [ -z "${DB_PASSWORD:-}" ]; then
    DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    echo "Generated secure password for user '$DB_USER'"
    echo "⚠️  IMPORTANT: Save this password - it won't be shown again!"
    echo "   Password: $DB_PASSWORD"
    echo ""
fi

# Check if user exists
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")
if [[ "$USER_EXISTS" != "1" ]]; then
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
else
    echo "User $DB_USER already exists"
fi

# =============================================================================
# Step 5: Create Blue-Green Databases
# =============================================================================
echo "Step 5: Creating blue-green databases..."

for DB_NAME in "$DB_BLUE" "$DB_GREEN"; do
    DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")
    if [[ "$DB_EXISTS" != "1" ]]; then
        sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"
        echo "Created database: $DB_NAME"
    else
        echo "Database $DB_NAME already exists"
    fi
    
    # Grant privileges
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"
    sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;"
    sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;"
done

# =============================================================================
# Step 6: Tune PostgreSQL for 2GB Instance with Bulk Operations
# =============================================================================
echo "Step 6: Tuning PostgreSQL for 2GB instance with bulk operations..."

# Create custom config file
CUSTOM_CONF="/etc/postgresql/14/main/conf.d/custom.conf"
sudo mkdir -p "$(dirname "$CUSTOM_CONF")"

sudo tee "$CUSTOM_CONF" > /dev/null << 'EOF'
# =============================================================================
# PostgreSQL Configuration for 2GB Lightsail Instance
# Optimized for bulk ingest operations
# =============================================================================

# -----------------------------------------------------------------------------
# Memory Settings (tuned for 2GB RAM)
# -----------------------------------------------------------------------------
shared_buffers = 128MB           # 6% of RAM (conservative for bulk ops)
work_mem = 4MB                   # Per-operation memory
maintenance_work_mem = 64MB      # For VACUUM, CREATE INDEX
effective_cache_size = 512MB     # Planner hint (conservative)

# -----------------------------------------------------------------------------
# Connection Limits (reduced for memory savings)
# -----------------------------------------------------------------------------
max_connections = 20             # We don't need 100

# -----------------------------------------------------------------------------
# Checkpoint Settings (spread I/O to avoid spikes)
# -----------------------------------------------------------------------------
checkpoint_completion_target = 0.9
checkpoint_timeout = 10min       # Less frequent checkpoints
max_wal_size = 1GB

# -----------------------------------------------------------------------------
# Background Writer (reduced activity)
# -----------------------------------------------------------------------------
bgwriter_delay = 500ms           # Less aggressive
bgwriter_lru_maxpages = 100

# -----------------------------------------------------------------------------
# Autovacuum (less aggressive during bulk operations)
# -----------------------------------------------------------------------------
autovacuum_max_workers = 1       # Single worker (was 3)
autovacuum_naptime = 5min        # Check less frequently
autovacuum_vacuum_cost_delay = 20ms

# -----------------------------------------------------------------------------
# WAL Settings
# -----------------------------------------------------------------------------
wal_compression = on             # Reduce I/O

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
log_min_duration_statement = 1000   # Log queries > 1s
log_checkpoints = on
log_lock_waits = on
EOF

echo "Created custom PostgreSQL config: $CUSTOM_CONF"

# Ensure conf.d is included
PG_CONF="/etc/postgresql/14/main/postgresql.conf"
if ! grep -q "include_dir = 'conf.d'" "$PG_CONF"; then
    echo "include_dir = 'conf.d'" | sudo tee -a "$PG_CONF"
fi

# Reload configuration
sudo systemctl reload postgresql

# =============================================================================
# Step 7: Create Health Check Script
# =============================================================================
echo "Step 7: Setting up health check monitoring..."

HEALTH_SCRIPT="/opt/visa_bulletin/scripts/health_check.sh"
sudo mkdir -p "$(dirname "$HEALTH_SCRIPT")"

sudo tee "$HEALTH_SCRIPT" > /dev/null << 'HEALTH_EOF'
#!/bin/bash
# Log system state every 5 minutes for debugging freezes
LOG=/var/log/health_check.log
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Get key metrics
CPU=$(top -bn1 | grep 'Cpu(s)' | awk '{print $2}')
MEM=$(free | awk '/Mem/{printf("%.1f", $3/$2 * 100)}')
SWAP=$(free | awk '/Swap/{if($2>0) printf("%.1f", $3/$2 * 100); else print "0"}')
LOAD=$(cat /proc/loadavg | awk '{print $1}')

# Log it
echo "$DATE | CPU: ${CPU}% | MEM: ${MEM}% | SWAP: ${SWAP}% | LOAD: $LOAD" >> $LOG

# Keep log from growing too large (keep last 1000 lines)
tail -1000 $LOG > $LOG.tmp && mv $LOG.tmp $LOG 2>/dev/null || true
HEALTH_EOF

sudo chmod +x "$HEALTH_SCRIPT"

# Add to cron
(sudo crontab -l 2>/dev/null | grep -v health_check; echo "*/5 * * * * $HEALTH_SCRIPT") | sudo crontab -

# =============================================================================
# Step 8: Verify Setup
# =============================================================================
echo "Step 8: Verifying setup..."

echo ""
echo "PostgreSQL version:"
sudo -u postgres psql -c "SELECT version();" | head -3

echo ""
echo "Databases:"
sudo -u postgres psql -c "\l" | grep visa_bulletin

echo ""
echo "Key settings:"
sudo -u postgres psql -t -c "SELECT name, setting FROM pg_settings WHERE name IN ('shared_buffers', 'work_mem', 'max_connections', 'autovacuum_max_workers');"

echo ""
echo "Swap status:"
free -h | grep -E "Mem|Swap"

echo ""
echo "Swappiness:"
cat /proc/sys/vm/swappiness

echo ""
echo "Monitoring tools:"
systemctl is-active sysstat atop

# =============================================================================
# Summary
# =============================================================================
echo
echo "=========================================="
echo "PostgreSQL Setup Complete"
echo "=========================================="
echo
echo "Databases created:"
echo "  - $DB_BLUE (primary)"
echo "  - $DB_GREEN (standby)"
echo
echo "User: $DB_USER"
echo "Host: localhost"
echo "Port: 5432"
echo
echo "System optimizations applied:"
echo "  - 2GB swap file"
echo "  - vm.swappiness=60"
echo "  - PostgreSQL tuned for bulk operations"
echo "  - Monitoring: sysstat, atop, health_check.sh"
echo
echo "To use with Django, set in .env:"
echo "  DB_NAME=$DB_BLUE"
echo "  DB_USER=$DB_USER"
echo "  DB_PASSWORD='<password>'"
echo "  DB_HOST=localhost"
echo "  DB_PORT=5432"
echo
echo "Next steps:"
echo "  1. Update .env with database credentials"
echo "  2. Run migrations: bazel run //:migrate"
echo "  3. Run build_all.sh to pre-build binaries"
echo "  4. Configure Bazel memory limits in .bazelrc"
echo
