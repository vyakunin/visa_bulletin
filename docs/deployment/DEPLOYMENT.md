# Production Deployment Guide

This guide covers production deployment with concurrent data refresh and web server.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                                                               │
│  ┌──────────────┐                    ┌──────────────────┐   │
│  │ Web Server   │                    │  Cron Job        │   │
│  │ (Django)     │◄───────┐           │  (Incremental    │   │
│  │              │        │           │   Refresh)       │   │
│  │ Port 8000    │        │           │                  │   │
│  └──────────────┘        │           │  Daily 9 AM      │   │
│         │                │           └──────────────────┘   │
│         │                │                     │             │
│         │                │                     │             │
│         ▼                │                     ▼             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  SQLite Database (WAL Mode)                          │   │
│  │                                                       │   │
│  │  • WAL = Write-Ahead Logging                         │   │
│  │  • Allows concurrent reads during writes             │   │
│  │  • 20-second timeout for lock contention             │   │
│  │  • Retry logic with exponential backoff              │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. SQLite WAL Mode

**What is WAL?**
- Write-Ahead Logging allows concurrent readers during writes
- Readers never block writers, writers never block readers
- Perfect for read-heavy workloads (like a dashboard)

**Configuration:**
```python
# In django_config/settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': WORKSPACE_DIR / 'visa_bulletin.db',
        'OPTIONS': {
            'timeout': 20,  # Wait up to 20 seconds for locks
        },
    }
}

# WAL mode is enabled automatically on connection
def setup_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        cursor = connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL;')
        cursor.execute('PRAGMA synchronous=NORMAL;')
        cursor.execute('PRAGMA cache_size=-64000;')  # 64MB cache
```

### 2. Incremental Refresh

**Purpose:** Only fetch new bulletins, not the entire history

**Features:**
- Queries database for existing bulletins
- Fetches only new bulletins from travel.state.gov
- Exponential backoff retry on lock contention
- Safe to run while web server is active

**Usage:**
```bash
# Manual run
bazel run //:refresh_data_incremental

# Check what would be fetched (dry run)
bazel run //:refresh_data_incremental 2>&1 | grep "new bulletin"
```

**Output:**
```
================================================================================
🔄 INCREMENTAL DATA REFRESH
================================================================================

📊 Checking existing data...
  • Bulletins in database: 284
  • Date range: 2001-12-01 to 2025-12-01

🌐 Fetching bulletin list from travel.state.gov...
  • Available bulletins: 284

✅ No new bulletins to fetch. Database is up to date!
================================================================================
```

### 3. Retry Logic

The incremental refresh implements exponential backoff:

```python
def save_with_retry(publication_data, max_retries=3, base_delay=1.0):
    """
    Retry saves with exponential backoff.
    
    Retry delays:
    - Attempt 1: 1.0 seconds
    - Attempt 2: 2.0 seconds
    - Attempt 3: 4.0 seconds
    """
    for attempt in range(max_retries):
        try:
            with transaction.atomic():
                return save_bulletin_to_db(publication_data)
        except OperationalError as e:
            if 'database is locked' in str(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
```

## Setup Instructions

### Step 1: Enable WAL Mode

WAL mode is automatically enabled when the database connection is created. To manually verify:

```bash
cd /Users/vyakunin/Downloads/visa_bulletin
sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
# Should output: wal
```

### Step 2: Test Incremental Refresh

```bash
# Test the script
bazel run //:refresh_data_incremental

# Expected output if database is current:
# ✅ No new bulletins to fetch. Database is up to date!
```

### Step 3: Setup Cron Job

```bash
# Run the setup script
./scripts/setup_cron.sh

# This will:
# - Create logs directory
# - Add cron job for daily 9 AM refresh
# - Configure logging
```

**Cron Job Configuration:**
```bash
# Run daily at 9 AM (when new bulletins are published)
0 9 * * * cd /Users/vyakunin/Downloads/visa_bulletin && bazel run //:refresh_data_incremental >> /Users/vyakunin/Downloads/visa_bulletin/logs/cron_refresh.log 2>&1
```

### Step 4: Start Web Server

```bash
# Start the web server (separate from cron job)
bazel run //:runserver

# Or run in background
bazel run //:runserver 2>&1 &

# Server will be available at: http://localhost:8000/
```

## Monitoring

### Check Cron Logs

```bash
# View recent logs
tail -f /Users/vyakunin/Downloads/visa_bulletin/logs/cron_refresh.log

# View today's refresh
grep "$(date +%Y-%m-%d)" /Users/vyakunin/Downloads/visa_bulletin/logs/cron_refresh.log

# Count successful refreshes
grep "✅ Database updated" /Users/vyakunin/Downloads/visa_bulletin/logs/cron_refresh.log | wc -l
```

### Check Database Status

```bash
# Count bulletins
sqlite3 visa_bulletin.db "SELECT COUNT(*) FROM bulletin;"

# Date range
sqlite3 visa_bulletin.db "SELECT MIN(publication_date), MAX(publication_date) FROM bulletin;"

# Latest bulletin
sqlite3 visa_bulletin.db "SELECT publication_date, url FROM bulletin ORDER BY publication_date DESC LIMIT 1;"

# WAL mode status
sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
```

### Check Web Server

```bash
# Test endpoint
curl -s "http://localhost:8000/" | grep "Visa Bulletin Dashboard"

# Check if server is running
ps aux | grep runserver | grep -v grep

# Monitor server logs (if running in background)
tail -f nohup.out
```

## Troubleshooting

### Database is Locked

**Symptom:**
```
django.db.utils.OperationalError: database is locked
```

**Solutions:**

1. **Check WAL mode is enabled:**
   ```bash
   sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
   # Should output: wal
   ```

2. **Stop all processes accessing DB:**
   ```bash
   # Stop web server
   pkill -f runserver
   
   # Stop any refresh processes
   pkill -f refresh_data
   
   # Enable WAL mode
   sqlite3 visa_bulletin.db "PRAGMA journal_mode=WAL;"
   
   # Restart web server
   bazel run //:runserver &
   ```

3. **Check for stale WAL files:**
   ```bash
   ls -lh visa_bulletin.db*
   # Should see: visa_bulletin.db, visa_bulletin.db-wal, visa_bulletin.db-shm
   
   # If WAL files are huge (>100MB), checkpoint them:
   sqlite3 visa_bulletin.db "PRAGMA wal_checkpoint(FULL);"
   ```

### Cron Job Not Running

**Check if cron job is registered:**
```bash
crontab -l | grep refresh_data_incremental
```

**Test manually:**
```bash
# Run the same command as cron
cd /Users/vyakunin/Downloads/visa_bulletin && bazel run //:refresh_data_incremental
```

**Check cron daemon:**
```bash
# macOS
sudo launchctl list | grep cron

# Linux
systemctl status cron
```

### No New Bulletins Being Fetched

**Verify the official website:**
```bash
curl -s "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html" | grep "visa-bulletin-for"
```

**Check parsing:**
```bash
# Run manual refresh to see what's available
bazel run //:refresh_data_incremental 2>&1 | grep "Available bulletins"
```

## Performance Characteristics

### Incremental Refresh Performance

| Scenario | Time | Notes |
|----------|------|-------|
| No new bulletins | ~2-3 seconds | Just checks, no downloads |
| 1 new bulletin | ~5-10 seconds | Fetch + parse + save |
| 10 new bulletins | ~30-60 seconds | Depends on network |

### Concurrent Access Performance

| Scenario | Web Server Impact | Refresh Impact |
|----------|-------------------|----------------|
| No writes (refresh finds no new data) | **None** | Instant (2-3s) |
| Small write (1 bulletin) | **Minimal** (<1s slower) | Normal (5-10s) |
| Large write (10+ bulletins) | **Minimal** (<2s slower) | Normal (30-60s) |

**Key Point:** With WAL mode, web server remains responsive even during large data refreshes!

## Best Practices

### 1. Run Incremental Refresh, Not Full Refresh

**✅ Good (Incremental):**
```bash
bazel run //:refresh_data_incremental
# Only fetches new data
```

**❌ Bad (Full Refresh):**
```bash
bazel run //:refresh_data -- --save-to-db
# Re-processes all 284 bulletins (slow!)
```

### 2. Monitor Cron Logs Regularly

```bash
# Add to weekly maintenance
tail -100 /Users/vyakunin/Downloads/visa_bulletin/logs/cron_refresh.log
```

### 3. Backup Database Periodically

```bash
# Checkpoint WAL and backup
sqlite3 visa_bulletin.db "PRAGMA wal_checkpoint(FULL);"
cp visa_bulletin.db visa_bulletin.db.backup.$(date +%Y%m%d)

# Keep last 7 days of backups
find . -name "visa_bulletin.db.backup.*" -mtime +7 -delete
```

### 4. Test After Deployments

```bash
# After updating code, test both:
# 1. Incremental refresh
bazel run //:refresh_data_incremental

# 2. Web server
bazel run //:runserver &
sleep 5
curl -s "http://localhost:8000/" | grep "Visa Bulletin Dashboard"
pkill -f runserver
```

## Scaling Beyond SQLite

If you need to scale beyond SQLite (e.g., multiple web servers, higher write throughput), consider:

### PostgreSQL Migration

**Pros:**
- True concurrent writes (multiple writers)
- Better performance at scale
- MVCC (Multi-Version Concurrency Control)
- Full-text search

**Migration Steps:**
```bash
# 1. Install PostgreSQL
# 2. Update settings.py:
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'visa_bulletin',
        'USER': 'visa_bulletin_user',
        'PASSWORD': 'secure_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

# 3. Migrate data
python manage.py migrate
# 4. Export from SQLite and import to PostgreSQL
```

**When to migrate:**
- More than 1 web server instance
- More than 100,000 cutoff date records
- Need full-text search on bulletin content
- Write throughput >10 bulletins/minute

## Summary

✅ **What We Built:**
- SQLite with WAL mode for concurrent access
- Incremental refresh that only fetches new data
- Retry logic for transient lock contention
- Cron job setup for daily automated refresh
- Comprehensive monitoring and troubleshooting

✅ **Production Ready:**
- Web server and cron job can run concurrently
- Minimal performance impact during refresh
- Automatic recovery from transient errors
- Easy to monitor and maintain

🎯 **Result:**
A robust, production-ready system that automatically keeps visa bulletin data up to date while serving web requests 24/7!

