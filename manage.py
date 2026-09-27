#!/usr/bin/env python
import os
import sys
from pathlib import Path


def default_settings() -> str:
    """Use DJANGO_SETTINGS_MODULE from .env when present (servers), else local development settings."""
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("DJANGO_SETTINGS_MODULE="):
                return line.split("=", 1)[1].strip()
    return "nexopay.settings.local"


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings())
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
