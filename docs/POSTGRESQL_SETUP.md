# PostgreSQL Setup and Discovery Guide (Local Development)

> **Note:** This guide is for **local macOS development**. For production PostgreSQL setup, see `deployment/NEW_INSTANCE_SETUP.md`.

## PostgreSQL Physical Storage Location (macOS)

- **Data Directory**: `/opt/homebrew/var/postgresql@15`
- **Current Size**: ~8.2 GB (as of Jan 2026)
- **Main Database**: 7.2 GB (OID 16384)
- **Installed via**: Homebrew (`brew install postgresql@15`)

## How to Discover PostgreSQL (macOS)

### 1. Check if PostgreSQL is Running

```bash
# Check if server is running on port 5432
lsof -i :5432

# Find PostgreSQL process and data directory
ps aux | grep "postgres.*-D" | grep -v grep

# Check server status (if psql is in PATH)
pg_isready -h localhost -p 5432
```

**Expected Output:**
```
COMMAND    PID     USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
postgres   715 vyakunin    7u  IPv6 0x6d14550e1c0bbc1f      0t0  TCP localhost:postgresql (LISTEN)
```

### 2. Check PostgreSQL Version

```bash
# From running process
ps aux | grep postgres | grep -v grep | head -1

# Check data directory version
cat /opt/homebrew/var/postgresql@15/PG_VERSION
```

### 3. Check Database Size

```bash
# Total PostgreSQL data size
du -sh /opt/homebrew/var/postgresql@15

# Individual database sizes
du -sh /opt/homebrew/var/postgresql@15/base/*
```

## How to Test PostgreSQL Connection

### Method 1: Via Bazel (Recommended)

Test database connectivity without actually running migrations:

```bash
# Check if migrations are up to date (tests DB connection without applying)
bazel run //:migrate -- --check

# Run migrations (applies pending migrations)
bazel run //:migrate

# Test with Django shell
bazel run //scripts:run_sql
```

**What to expect:**
- ✅ **Success**: No output or "System check identified no issues"
- ❌ **Connection Failed**: "could not connect to server" or "password authentication failed"
- ⚠️ **Database Missing**: "database 'visa_bulletin_dev' does not exist"

### Method 2: Check Bazel Dependencies

Verify psycopg2 is available:

```bash
# Check requirements.txt
grep psycopg requirements.txt

# Check BUILD files for PostgreSQL adapter
grep -r "psycopg2_binary" --include="BUILD"
```

**Expected Output:**
```
requirements.txt:psycopg2-binary>=2.9.0  # PostgreSQL adapter for Django
BUILD:requirement("psycopg2_binary"),
models/BUILD:requirement("psycopg2_binary"),
... (32+ references)
```

### Method 3: Django DB Connection Test

```python
# In scripts/run_sql or any Django script
from django.db import connection

# Test connection
with connection.cursor() as cursor:
    cursor.execute("SELECT version();")
    version = cursor.fetchone()
    print(f"PostgreSQL version: {version[0]}")
```

## Database Configuration

### Local Development (Current Settings)

**Location**: `django_config/settings.py`

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'visa_bulletin_dev'),
        'USER': os.environ.get('DB_USER', 'visa_bulletin_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'dev_password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}
```

**Default Credentials:**
- Database: `visa_bulletin_dev`
- User: `visa_bulletin_user`
- Password: `dev_password`
- Host: `localhost`
- Port: `5432`

### Override with Environment Variables

```bash
# Set custom database credentials
export DB_NAME=my_custom_db
export DB_USER=my_user
export DB_PASSWORD=my_password
export DB_HOST=localhost
export DB_PORT=5432

# Then run Bazel commands
bazel run //:migrate
```

## Creating the Database

If the database doesn't exist, create it:

```bash
# Using system psql (if available)
createdb -h localhost -p 5432 -U postgres visa_bulletin_dev

# Or via SQL
psql -h localhost -p 5432 -U postgres -c "CREATE DATABASE visa_bulletin_dev;"

# Create user with password
psql -h localhost -p 5432 -U postgres -c "CREATE USER visa_bulletin_user WITH PASSWORD 'dev_password';"
psql -h localhost -p 5432 -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE visa_bulletin_dev TO visa_bulletin_user;"
```

**Note**: If `psql` is not in PATH, you can access PostgreSQL via:
```bash
/opt/homebrew/opt/postgresql@15/bin/psql -h localhost -p 5432 -U postgres
```

## Common Issues

### Issue: Database Does Not Exist

**Error:**
```
django.db.utils.OperationalError: FATAL:  database "visa_bulletin_dev" does not exist
```

**Solution:**
```bash
createdb -h localhost -p 5432 -U postgres visa_bulletin_dev
```

### Issue: Password Authentication Failed

**Error:**
```
django.db.utils.OperationalError: FATAL:  password authentication failed for user "visa_bulletin_user"
```

**Solution:**
1. Check `pg_hba.conf`: `/opt/homebrew/var/postgresql@15/pg_hba.conf`
2. Add line: `host all all 127.0.0.1/32 md5`
3. Restart PostgreSQL: `brew services restart postgresql@15`

### Issue: PostgreSQL Not Running

**Error:**
```
django.db.utils.OperationalError: could not connect to server
```

**Solution:**
```bash
# Start PostgreSQL
brew services start postgresql@15

# Check status
brew services list | grep postgresql
```

## Production vs Local Differences

| Aspect | Local (macOS) | Production (Lightsail) |
|--------|--------------|------------------------|
| **Version** | PostgreSQL 15 | PostgreSQL 14 |
| **Data Location** | `/opt/homebrew/var/postgresql@15` | `/var/lib/postgresql/14/main` |
| **Install Method** | Homebrew | APT package manager |
| **Service Manager** | Homebrew Services | systemd |

> **Note:** For production setup details, see `deployment/NEW_INSTANCE_SETUP.md`.

## Bazel Integration

### How Bazel Accesses PostgreSQL

1. **psycopg2-binary** in `requirements.txt` (line 12)
2. **Bazel BUILD files** include `requirement("psycopg2_binary")` (32+ references)
3. **Django settings** point to `localhost:5432`
4. **Bazel sandbox** allows network access to PostgreSQL

### Testing Bazel PostgreSQL Integration

```bash
# 1. Verify psycopg2 is in requirements
grep psycopg2 requirements.txt

# 2. Build target with PostgreSQL deps
bazel build //:migrate

# 3. Test database connection
bazel run //:check_migrations

# 4. Run migrations
bazel run //:migrate
```

## Production Setup

Production uses PostgreSQL 14 on AWS Lightsail. For production setup details, see:
- `deployment/NEW_INSTANCE_SETUP.md` - Instance setup including PostgreSQL
- `DATA_REFRESH_STRATEGY.md` - Blue-green database architecture

