# apps/home/management/commands/seed_program_areas.py
"""
Seeds ProgramArea rows (homepage "Ways We Engage" grid) from
docs/data/front page data.txt -- one bullet ("• ...") per line, no
sections/labels to parse (unlike core.txt). Idempotent via get_or_create
keyed on name; a second run with an unchanged file is a no-op.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.home.models import ProgramArea


class Command(BaseCommand):
    help = 'Seed ProgramArea rows from "docs/data/front page data.txt"'

    def add_arguments(self, parser):
        parser.add_argument("file_path", nargs="?", default="docs/data/front page data.txt")

    def handle(self, *args, **options):
        path = Path(options["file_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        names = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            # Bullets are "• Text;" or "• Text." -- strip the marker and
            # any single trailing punctuation, verbatim otherwise.
            name = line.lstrip("•").strip().rstrip(";.").strip()
            if name:
                names.append(name)

        if not names:
            raise CommandError("No bullet lines found in the source file.")

        created, updated, unchanged = [], [], []

        for order, name in enumerate(names):
            obj, was_created = ProgramArea.objects.get_or_create(
                name=name, defaults={"order": order},
            )
            if was_created:
                created.append(name)
            elif obj.order != order:
                obj.order = order
                obj.save(update_fields=["order"])
                updated.append(name)
            else:
                unchanged.append(name)

        self.stdout.write(self.style.SUCCESS(f"Created: {created or 'none'}"))
        self.stdout.write(self.style.SUCCESS(f"Updated: {updated or 'none'}"))
        self.stdout.write(f"Unchanged: {unchanged or 'none'}")
