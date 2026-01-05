#!/usr/bin/env python3
"""Quick script to check which migrations have been applied"""
import os
import sys

# Set environment variables before Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
os.environ['DB_ENGINE'] = 'postgresql'
os.environ['DB_NAME'] = 'visa_bulletin_dev'
os.environ['DB_USER'] = 'vyakunin'
os.environ['DB_PASSWORD'] = ''
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'

import django
django.setup()

from django.db import connection

cursor = connection.cursor()
cursor.execute("""
    SELECT app, name, applied 
    FROM django_migrations 
    WHERE app='models' 
    ORDER BY id;
""")

# Get all migration files
import os
from pathlib import Path
# In Bazel sandbox, need to use BUILD_WORKSPACE_DIRECTORY
workspace_dir = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent))
migration_dir = workspace_dir / 'models' / 'migrations'
migration_files = sorted([f.stem for f in migration_dir.glob('*.py') if f.name != '__init__.py'])

# Get applied migrations
applied_migrations = {row[1] for row in cursor.fetchall()}

print('\nMigration Status:')
print('=' * 80)
for mig in migration_files:
    status = '✓ APPLIED' if mig in applied_migrations else '✗ PENDING'
    print(f'{status:12} | {mig}')

pending = [mig for mig in migration_files if mig not in applied_migrations]
if pending:
    print(f'\n⚠️  {len(pending)} migration(s) still pending:')
    for mig in pending:
        print(f'   - {mig}')
else:
    print('\n✅ All migrations applied!')

cursor.close()









