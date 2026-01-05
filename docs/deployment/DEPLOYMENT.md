# Production Deployment Guide

This guide covers production deployment with concurrent data refresh and web server using PostgreSQL.

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
│  │  PostgreSQL Database                                 │   │
│  │                                                       │   │
│  │  • Full Concurrency (MVCC)                           │   │
│  │  • Multiple writers supported                        │   │
│  │  • Production-grade reliability                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Key Features

### 1. PostgreSQL Database

**Why PostgreSQL?**
- **Concurrency:** Uses MVCC (Multi-Version Concurrency Control) to allow simultaneous reads and writes without locking.
- **Reliability:** ACID compliant and robust against corruption.
- **Performance:** Optimized for complex queries and large datasets.

**Configuration:**
```python
# In django_config/settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'visa_bulletin'),
        'USER': os.environ.get('DB_USER', 'visa_bulletin_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'secure_password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}
```

### 2. Incremental Refresh

**Purpose:** Only fetch new bulletins, not the entire history

**Features:**
- Queries database for existing bulletins
- Fetches only new bulletins from travel.state.gov
- Safe to run while web server is active

**Usage:**
```bash
# Manual run (unified ingest pipeline)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain visa_bulletin

# Check what would be fetched (discover only)
bazel run //scripts/ingest:run_pipeline -- discover --domain visa_bulletin
```

## Setup Instructions

### Step 1: Database Setup

Ensure PostgreSQL is running and the database is created.
```bash
# Example (local)
createdb visa_bulletin
```

### Step 2: Run Migrations

```bash
bazel run //:migrate
```

### Step 3: Test Data Refresh

```bash
# Test the unified ingest pipeline
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain visa_bulletin
```

### Step 4: Setup Cron Job

```bash
# Run the setup script
./scripts/setup_cron.sh
```

**Cron Job Configuration:**
```bash
# Run daily at 9 AM (when new bulletins are published)
0 9 * * * cd /opt/visa_bulletin && bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains >> /var/log/visa_bulletin/cron_refresh.log 2>&1
```

### Step 5: Start Web Server

```bash
# Start the web server
bazel run //:runserver
```

## Monitoring

### Check Cron Logs

```bash
tail -f /var/log/visa_bulletin/cron_refresh.log
```

### Check Web Server

```bash
# Test endpoint
curl -s "http://localhost:8000/" | grep "Visa Bulletin Dashboard"
```

## Troubleshooting

### Connection Issues

**Symptom:**
```
django.db.utils.OperationalError: connection to server at "localhost" (::1), port 5432 failed: Connection refused
```

**Solutions:**
1. Check if PostgreSQL service is running.
2. Verify environment variables (`DB_HOST`, `DB_PORT`, etc.) are correct.
3. Check network connectivity/firewall rules.

### Performance Tuning

- Use connection pooling (configured in `settings.py` via `CONN_MAX_AGE`).
- Monitor slow queries using PostgreSQL logs.
