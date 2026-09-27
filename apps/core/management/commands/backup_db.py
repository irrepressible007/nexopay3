"""
Nightly MySQL/MariaDB dump → gzip → private object storage (R2), keeping N days.

    python manage.py backup_db --keep 14
"""
import gzip
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Dump the database and upload it to private storage."

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14, help="Days of backups to keep.")

    def handle(self, *args, keep=14, **options):
        db = settings.DATABASES["default"]
        if db["ENGINE"] != "django.db.backends.mysql":
            raise CommandError("backup_db supports MySQL/MariaDB only.")
        dump_bin = shutil.which("mysqldump") or shutil.which("mariadb-dump")
        if not dump_bin:
            raise CommandError("mysqldump not found on PATH.")

        stamp = timezone.now().strftime("%Y%m%d-%H%M")
        storage = storages["private"]
        env = {**os.environ, "MYSQL_PWD": db.get("PASSWORD", "")}
        cmd = [dump_bin, "--single-transaction", "--quick", "--routines", "--default-character-set=utf8mb4",
               "-h", db.get("HOST") or "localhost", "-u", db["USER"]]
        if db.get("PORT"):
            cmd += ["-P", str(db["PORT"])]
        cmd.append(db["NAME"])

        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            path = tmp.name
        try:
            with gzip.open(path, "wb") as out:
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
                if proc.returncode != 0:
                    raise CommandError(proc.stderr.decode(errors="replace")[:500])
                out.write(proc.stdout)
            with open(path, "rb") as fh:
                name = storage.save(f"backups/db/{db['NAME']}-{stamp}.sql.gz", File(fh))
        finally:
            os.unlink(path)
        self.stdout.write(f"Uploaded {name}")

        cutoff = (timezone.now() - timedelta(days=keep)).strftime("%Y%m%d")
        try:
            _dirs, files = storage.listdir("backups/db")
        except (FileNotFoundError, NotImplementedError):
            files = []
        for filename in files:
            date_part = filename.rsplit("-", 2)[-2] if filename.count("-") >= 2 else ""
            if date_part.isdigit() and date_part < cutoff:
                storage.delete(f"backups/db/{filename}")
