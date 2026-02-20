"""
Grant CREATEDB to DB_USER so tests can create test_postgres.

Called by django_setup on first DB test when PG_SUPERUSER_USER and PG_SUPERUSER_PASSWORD
are set (e.g. in .env). CI often uses the postgres user (has CREATEDB) so no grant needed.
"""

import os


def grant_createdb() -> bool:
    """
    Grant CREATEDB to DB_USER so test_postgres can be created. Idempotent.
    Reads DB_USER, PG_SUPERUSER_USER, PG_SUPERUSER_PASSWORD (or DB_PASSWORD), DB_HOST, DB_PORT from env.
    Returns True if grant succeeded or was skipped (postgres user / no DB_USER), False on failure.
    """
    db_user = os.environ.get("DB_USER", "")
    if not db_user:
        return True
    if db_user == "postgres":
        return True
    superuser = os.environ.get("PG_SUPERUSER_USER", "postgres")
    superpass = os.environ.get("PG_SUPERUSER_PASSWORD", "")
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    if not superpass and superuser != db_user:
        return True
    try:
        import psycopg2
        from psycopg2 import sql

        conn = psycopg2.connect(
            dbname="postgres",
            user=superuser,
            password=superpass or os.environ.get("DB_PASSWORD", ""),
            host=host,
            port=port,
            connect_timeout=5,
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql.SQL("ALTER USER {} CREATEDB").format(sql.Identifier(db_user)))
        cur.close()
        conn.close()
        return True
    except Exception:
        return False
