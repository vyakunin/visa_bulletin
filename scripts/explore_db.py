#!/usr/bin/env python3
"""
Generic database exploration tool for debugging and analysis.

Usage:
    bazel run //:explore_db -- --query "SELECT COUNT(*) FROM salary_record"
    bazel run //:explore_db -- --query "SELECT * FROM salary_record WHERE wage_annual > 1000000 LIMIT 5"
    bazel run //:explore_db -- --table salary_record --limit 10
"""

import argparse
import logging
import os
import sys

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

# Import models to ensure they're registered (required for Django setup)
from models.salary import SalaryRecord  # noqa: F401
from models.bulletin import Bulletin  # noqa: F401

from django.db import connection
from lib.utils.logging_utils import ScriptLogger
from django_config.logging_config import setup_logging

script_logger = ScriptLogger(__file__)
setup_logging(debug=False)
logger = logging.getLogger(__name__)


def run_query(query: str):
    """Execute a raw SQL query and print results"""
    with connection.cursor() as cursor:
        cursor.execute(query)
        
        # Get column names
        columns = [col[0] for col in cursor.description] if cursor.description else []
        
        # Fetch results
        rows = cursor.fetchall()
        
        # Print results
        if columns:
            # Print header
            print(" | ".join(columns))
            print("-" * (len(" | ".join(columns))))
            
            # Print rows
            for row in rows:
                print(" | ".join(str(val) for val in row))
        else:
            # No columns (e.g., COUNT(*))
            for row in rows:
                print(row[0] if len(row) == 1 else row)
        
        print(f"\n({len(rows)} row(s))")


def show_table(table_name: str, limit: int = 10):
    """Show table structure and sample data"""
    with connection.cursor() as cursor:
        # Get table structure
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        print(f"Table: {table_name}")
        print("Columns:")
        for col in columns:
            print(f"  {col[1]} ({col[2]})")
        
        print(f"\nSample data (limit {limit}):")
        cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
        rows = cursor.fetchall()
        
        if rows:
            col_names = [col[1] for col in columns]
            print(" | ".join(col_names))
            print("-" * 80)
            for row in rows:
                print(" | ".join(str(val)[:30] for val in row))


def main():
    parser = argparse.ArgumentParser(
        description='Explore database for debugging',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Count records:
    bazel run //:explore_db -- --query "SELECT COUNT(*) FROM salary_record"
  
  Find high salaries:
    bazel run //:explore_db -- --query "SELECT employer_name, wage_annual FROM salary_record WHERE wage_annual > 1000000 LIMIT 5"
  
  Show table structure:
    bazel run //:explore_db -- --table salary_record
        """
    )
    
    parser.add_argument(
        '--query', '-q',
        help='SQL query to execute'
    )
    
    parser.add_argument(
        '--table', '-t',
        help='Table name to explore'
    )
    
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Limit for table exploration (default: 10)'
    )
    
    args = parser.parse_args()
    
    # Log the call
    script_logger.log_call(
        args={'query': args.query, 'table': args.table, 'limit': args.limit},
        context='Database exploration'
    )
    
    if args.query:
        run_query(args.query)
    elif args.table:
        show_table(args.table, args.limit)
    else:
        parser.error('Either --query or --table must be specified')


if __name__ == '__main__':
    main()
