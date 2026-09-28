"""
Make sure the MySQL/MariaDB database and every table use utf8mb4, so Bangla
(and emoji) can be stored. cPanel creates databases with the server default
(often latin1), which rejects Bangla text. Safe to run on every deploy: it only
changes what isn't utf8mb4 yet.

    python manage.py ensure_utf8mb4
"""
from django.core.management.base import BaseCommand
from django.db import connection

CHARSET, COLLATION = "utf8mb4", "utf8mb4_unicode_ci"


class Command(BaseCommand):
    help = "Convert the database and its tables to utf8mb4 (needed for Bangla text)."

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            self.stdout.write("Not MySQL/MariaDB - nothing to do.")
            return
        name = connection.settings_dict["NAME"]
        quote = connection.ops.quote_name
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DEFAULT_CHARACTER_SET_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s", [name]
            )
            row = cursor.fetchone()
            if row and row[0] != CHARSET:
                cursor.execute(f"ALTER DATABASE {quote(name)} CHARACTER SET {CHARSET} COLLATE {COLLATION}")
                self.stdout.write(f"Database {name}: {row[0]} -> {CHARSET}")

            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
                "AND (TABLE_COLLATION IS NULL OR TABLE_COLLATION NOT LIKE 'utf8mb4%%')",
                [name],
            )
            tables = cursor.fetchall()
            if tables:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    for table, collation in tables:
                        cursor.execute(
                            f"ALTER TABLE {quote(table)} CONVERT TO CHARACTER SET {CHARSET} COLLATE {COLLATION}"
                        )
                        self.stdout.write(f"Table {table}: {collation} -> {COLLATION}")
                finally:
                    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        self.stdout.write(self.style.SUCCESS("Database character set OK (utf8mb4)."))
