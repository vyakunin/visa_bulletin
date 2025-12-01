#!/usr/bin/env python3
"""
Database exploration script for visa bulletin data

Usage:
    python explore_db.py                    # Show summary
    python explore_db.py --bulletins        # List all bulletins
    python explore_db.py --query "F1 China" # Search for specific data
"""

import sqlite3
import sys
from datetime import datetime
from models.enums.visa_category import VisaCategory
from models.enums.action_type import ActionType
from models.enums.country import Country


def connect_db():
    """Connect to the database"""
    return sqlite3.connect('visa_bulletin.db')


def show_summary():
    """Show database summary"""
    conn = connect_db()
    cursor = conn.cursor()
    
    print("=" * 80)
    print("📊 VISA BULLETIN DATABASE SUMMARY")
    print("=" * 80)
    
    # Bulletins
    cursor.execute("SELECT COUNT(*), MIN(publication_date), MAX(publication_date) FROM bulletin")
    count, earliest, latest = cursor.fetchone()
    print(f"\n📅 Bulletins: {count} total")
    print(f"   Date range: {earliest} to {latest}")
    
    # Cutoff records
    cursor.execute("SELECT COUNT(*) FROM visa_cutoff_date")
    total_records = cursor.fetchone()[0]
    print(f"\n📈 Cutoff Records: {total_records:,} total")
    
    # By category
    cursor.execute("""
        SELECT visa_category, COUNT(*) as count 
        FROM visa_cutoff_date 
        GROUP BY visa_category
        ORDER BY count DESC
    """)
    print("\n📋 By Category:")
    for category, count in cursor.fetchall():
        print(f"   {category:20s}: {count:6,} records")
    
    # Current status counts
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN is_current = 1 THEN 1 ELSE 0 END) as current_count,
            SUM(CASE WHEN is_unavailable = 1 THEN 1 ELSE 0 END) as unavailable_count,
            SUM(CASE WHEN is_current = 0 AND is_unavailable = 0 THEN 1 ELSE 0 END) as dated_count
        FROM visa_cutoff_date
    """)
    current, unavailable, dated = cursor.fetchone()
    print(f"\n🎯 Status Distribution:")
    print(f"   Current (C):       {current:6,} records ({current/total_records*100:.1f}%)")
    print(f"   Unavailable (U):   {unavailable:6,} records ({unavailable/total_records*100:.1f}%)")
    print(f"   With dates:        {dated:6,} records ({dated/total_records*100:.1f}%)")
    
    # Sample recent data
    cursor.execute("""
        SELECT b.publication_date, v.visa_class, v.country, v.cutoff_value
        FROM visa_cutoff_date v
        JOIN bulletin b ON v.bulletin_id = b.id
        ORDER BY b.publication_date DESC
        LIMIT 5
    """)
    print(f"\n🔍 Recent Records (sample):")
    print(f"   {'Date':<12} {'Class':<6} {'Country':<20} {'Cutoff':<12}")
    print("   " + "-" * 52)
    for row in cursor.fetchall():
        print(f"   {row[0]:<12} {row[1]:<6} {row[2]:<20} {row[3]:<12}")
    
    conn.close()
    print("\n" + "=" * 80)


def list_bulletins():
    """List all bulletins"""
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT b.publication_date, COUNT(v.id) as record_count
        FROM bulletin b
        LEFT JOIN visa_cutoff_date v ON b.id = v.bulletin_id
        GROUP BY b.id
        ORDER BY b.publication_date DESC
    """)
    
    print("=" * 60)
    print("📅 ALL BULLETINS")
    print("=" * 60)
    print(f"{'Date':<15} {'Records':<10}")
    print("-" * 60)
    
    for date, count in cursor.fetchall():
        print(f"{date:<15} {count:<10,}")
    
    conn.close()


def query_data(search_term: str):
    """Search for specific visa class/country data"""
    conn = connect_db()
    cursor = conn.cursor()
    
    # Parse search term (e.g., "F1 China" or "EB2 India")
    parts = search_term.upper().split()
    if len(parts) < 2:
        print("❌ Usage: --query 'VISA_CLASS COUNTRY' (e.g., 'F1 China' or 'EB2 India')")
        return
    
    visa_class = parts[0]
    country_name = ' '.join(parts[1:])
    
    # Map country name to enum value
    country_map = {
        'ALL': Country.ALL.value,
        'CHINA': Country.CHINA.value,
        'INDIA': Country.INDIA.value,
        'MEXICO': Country.MEXICO.value,
        'PHILIPPINES': Country.PHILIPPINES.value,
    }
    
    country_value = country_map.get(country_name, country_name.lower())
    
    cursor.execute("""
        SELECT 
            b.publication_date,
            v.visa_category,
            v.action_type,
            v.cutoff_value,
            v.cutoff_date,
            v.is_current
        FROM visa_cutoff_date v
        JOIN bulletin b ON v.bulletin_id = b.id
        WHERE v.visa_class = ? AND v.country = ?
        ORDER BY b.publication_date DESC
        LIMIT 20
    """, (visa_class, country_value))
    
    results = cursor.fetchall()
    
    if not results:
        print(f"❌ No data found for {visa_class} {country_name}")
        conn.close()
        return
    
    print("=" * 100)
    print(f"📊 {visa_class} - {country_name.title()} (Last 20 bulletins)")
    print("=" * 100)
    print(f"{'Date':<12} {'Category':<20} {'Action':<15} {'Cutoff':<12} {'Current':<8}")
    print("-" * 100)
    
    for row in results:
        pub_date, category, action, cutoff_val, cutoff_date, is_current = row
        current_flag = "✓" if is_current else ""
        display_date = cutoff_date if cutoff_date else cutoff_val
        print(f"{pub_date:<12} {category:<20} {action:<15} {display_date:<12} {current_flag:<8}")
    
    conn.close()


def main():
    """Main entry point"""
    if len(sys.argv) == 1:
        show_summary()
    elif '--bulletins' in sys.argv:
        list_bulletins()
    elif '--query' in sys.argv:
        idx = sys.argv.index('--query')
        if idx + 1 < len(sys.argv):
            query_data(sys.argv[idx + 1])
        else:
            print("❌ Please provide a search term after --query")
    else:
        print("Usage:")
        print("  python explore_db.py                    # Show summary")
        print("  python explore_db.py --bulletins        # List all bulletins")
        print("  python explore_db.py --query 'F1 China' # Search for specific data")


if __name__ == '__main__':
    main()

