# apps/home/management/commands/seed_core_content.py
"""
Seeds the Foundations/Motto/Vision/Mission/Core Values Article rows
(page_key-keyed) from docs/data/core.txt -- the sole source of this
content. Rendered together on uon_alumni_mission_vision via
snippets/uon_alumni_core.html (see apps/home/views.py's
uon_alumni_mission_vision).

Idempotent via get_or_create keyed on page_key (never title): a second
run with an unchanged file is a no-op; correcting the txt file and
rerunning updates only the rows whose title/body actually changed.
core.txt is read-only input -- never written to.
"""
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.home.models import Article

# (page_key, exact anchor line to search for in the file, title stored on
# the Article). Anchor and title differ only for Foundations: Article.title
# uses the custom Title field (apps/home/models.py:99-104), whose
# get_prep_value() silently applies Python's str.title() on save --
# "FOUNDATIONS OF UONAA" would be persisted as "Foundations Of Uonaa"
# (mangling the UONAA abbreviation). Using the plain word "Foundations" as
# the title sidesteps that -- the anchor (what's searched for in the file)
# stays the verbatim heading either way.
LABELS = [
    (Article.PageKey.FOUNDATIONS, "FOUNDATIONS OF UONAA", "Foundations"),
    (Article.PageKey.MOTTO, "Motto", "Motto"),
    (Article.PageKey.VISION, "Vision", "Vision"),
    (Article.PageKey.MISSION, "Mission", "Mission"),
    (Article.PageKey.CORE_VALUES, "Core Values", "Core Values"),
]

NUMBERED_ITEM_RE = re.compile(r'^\d+\.')


class Command(BaseCommand):
    help = "Seed Foundations/Motto/Vision/Mission/Core Values Article rows from docs/data/core.txt"

    def add_arguments(self, parser):
        parser.add_argument("file_path", nargs="?", default="docs/data/core.txt")

    def handle(self, *args, **options):
        path = Path(options["file_path"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        sections = self._parse(lines)

        created, updated, unchanged, skipped = [], [], [], []

        for page_key, label, name in LABELS:
            body = sections.get(page_key, "")
            if not body:
                skipped.append(name)
                continue

            # Compare against title.title(), not title, since Article's
            # custom Title field persists str.title()-cased text -- an
            # already-title-cased name (all of ours are) round-trips
            # unchanged, so this only matters if that ever stops being true.
            title = name
            obj, was_created = Article.objects.get_or_create(
                page_key=page_key,
                defaults={"title": title, "body": body, "type": Article.ArticleType.PAGE},
            )
            if was_created:
                created.append(name)
            elif obj.title != title.title() or obj.body != body:
                obj.title = title
                obj.body = body
                obj.type = Article.ArticleType.PAGE
                obj.save(update_fields=["title", "body", "type"])
                updated.append(name)
            else:
                unchanged.append(name)

        self.stdout.write(self.style.SUCCESS(f"Created: {created or 'none'}"))
        self.stdout.write(self.style.SUCCESS(f"Updated: {updated or 'none'}"))
        self.stdout.write(f"Unchanged: {unchanged or 'none'}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped (empty/not found in file): {skipped}"))

    def _parse(self, lines):
        """
        lines is the file's non-empty lines, stripped, in order. Structure
        is fixed and known (docs/data/core.txt) -- each label is an exact
        standalone line, its value is the line immediately after it, except
        Core Values, whose "value" is its intro sentence plus every
        subsequent numbered ("1.", "2.", ...) line, preserved verbatim and
        joined with newlines so the six items stay individually readable
        (the "cohesive" single Core Values section).
        """
        sections = {}

        for page_key, label, name in LABELS:
            try:
                idx = lines.index(label)
            except ValueError:
                raise CommandError(f"Expected label '{label}' ({name}) not found in {name!r} section of the source file.")

            if page_key == Article.PageKey.CORE_VALUES:
                intro = lines[idx + 1]
                items = []
                i = idx + 2
                while i < len(lines) and NUMBERED_ITEM_RE.match(lines[i]):
                    items.append(lines[i])
                    i += 1
                if not items:
                    raise CommandError("Core Values: intro line found but no numbered items followed it.")
                sections[page_key] = "\n".join([intro] + items)
            else:
                sections[page_key] = lines[idx + 1]

        return sections
