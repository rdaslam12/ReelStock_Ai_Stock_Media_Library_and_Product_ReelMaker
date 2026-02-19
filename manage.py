#!/usr/bin/env python
"""
Management utility for the ReelStock project.

This script is the command‑line interface for administrative tasks such
as starting a development server or running migrations.  It simply
configures the environment and delegates to Django’s built‑in
management functions.  See Django’s documentation on ``manage.py`` for
more details【140022745920203†L131-L167】.
"""
import os
import sys


def main() -> None:
    """Run administrative tasks."""
    # Set the default settings module for the 'django' program.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reelstock.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and available "
            "on your PYTHONPATH environment variable? Did you forget to activate "
            "a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()