# apps/home/management/commands/import_chosen_articles.py
"""
RETIRED (2026-10-28) -- do not run this against a real database again.

Its source, docs/CHOSEN UONNAA WEB ARTICLES.md, was an unverified first
draft that went live with fabricated/unconfirmed figures (invented
membership and endowment-fund numbers, a chronologically impossible
"60th Anniversary" article) and several wrong chapter-launch dates --
flagged by the Association as a serious accuracy problem on a public
site. Use apps/home/management/commands/import_verified_history.py
instead, which replaces everything this command created with the
fact-checked set in docs/origins/deepseek_markdown_20261028_ef6da2.md.
Left in place only for its own history / so the mistake and its fix are
both visible in the repo.

Original docstring follows, unmodified:

Imports docs/CHOSEN UONNAA WEB ARTICLES.md -- ~95 curated historical
UONAA/UoN news articles (2005-2015) -- as Article rows (apps/home/models.py).

SAFE BY DEFAULT: runs inside a transaction that's rolled back unless
--commit is passed. Always run without --commit first and read the report.

Three deliberate decisions behind the mapping below (Association call,
2026-10-27):

  - Chapter mapping: the doc's "Chapter:" line is mostly a topic beat
    ("Central", "Mombasa Campus", "Student Affairs", "Research &
    Innovation", "Journalism And Mass Communication"), not a real alumni
    interest group -- those stay unlinked (Article.chapter=None). Only
    the handful of labels naming a genuine alumni Chapter get a real
    Chapter row + FK link: see REAL_CHAPTER_NAMES.
  - References / Editor's Note sections have no dedicated Article field,
    so they're appended to body as trailing sections instead of dropped
    -- keeps the sourcing/fact-checking trail for whoever reviews these.
  - Imported articles publish immediately (is_published=True), despite
    many containing unresolved [VERIFY: ...]/[SOURCE NEEDED: ...]
    editorial flags in that appended Editor's Note section.

Parser notes: the source .md is hand/AI-curated and not perfectly
regular -- titles sometimes wrap onto a second bold line, the metadata
line ("Chapter: ... Date: ... Is Feature: ... | Is Highlighted: ...")
sometimes wraps too, a handful of articles have no Date at all, and the
only two "20XX ARTICLES" section headers in the whole file (2006, 2007)
run directly against the previous article's last line with no blank
line separating them. _parse() handles all of these against this exact
file; it is not a generic article-doc parser.
"""
import html
import re
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.home.models import Article, Chapter

# Chapter: label -> real Chapter.name. Everything else (Central, Mombasa
# Campus, Student Affairs, Research & Innovation, Journalism And Mass
# Communication, ...) is a topic beat, not a Chapter, and stays unlinked.
REAL_CHAPTER_NAMES = {
    "Human Medicine Chapter": "Medical Chapter",
    "Computing & Informatics Chapter": "Computing & Informatics Chapter",
    "Pharmacy Chapter": "Pharmacy Chapter",
    "Engineering Chapter": "Engineering Chapter",
    "Education Chapter": "Education Chapter",
    "Architecture, Design and Development": "Architecture, Design and Development Chapter",
}

MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

# Undoes the doc's markdown backslash-escaping (\&, \#, \|, \-, \(, \),
# \., \*, \[, \]...) -- applied BEFORE html.unescape(), since the doc
# escapes the literal "&" of "&quot;"/"&#39;"/"&amp;" too (e.g. \&quot;).
_ESCAPE_RE = re.compile(r'\\([\\`*_{}\[\]()#+\-.!|&])')
_YEAR_HEADER_RE = re.compile(r'^\*{0,2}(\d{4})\s+ARTICLES\*{0,2}\s*$')
_ARTICLE_PREFIX_RE = re.compile(r'^Article\s+\d+:\s*', re.IGNORECASE)
_TITLE_START_RE = re.compile(r'^#{0,3}\s*\*{0,2}Article\s+\d+:', re.IGNORECASE)
_CHAPTER_LINE_RE = re.compile(r'^Chapter:\s')
_NOTE_HEADER_RE = re.compile(r'^Editor.{0,12}Note:$')


def _clean(text):
    text = _ESCAPE_RE.sub(r'\1', text)
    return html.unescape(text).strip()


def _parse_date(raw, fallback_year):
    if raw:
        raw = raw.strip().rstrip('.')
        m = re.match(r'^([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})$', raw)
        if m and m.group(1).upper() in MONTHS:
            return date(int(m.group(3)), MONTHS[m.group(1).upper()], int(m.group(2)))
        m = re.match(r'^([A-Za-z]+)\s+(\d{4})$', raw)
        if m and m.group(1).upper() in MONTHS:
            return date(int(m.group(2)), MONTHS[m.group(1).upper()], 1)
        m = re.match(r'^(\d{4})$', raw)
        if m:
            return date(int(m.group(1)), 1, 1)
    return date(fallback_year, 1, 1)


class Command(BaseCommand):
    help = "Import docs/CHOSEN UONNAA WEB ARTICLES.md as Article rows"

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path", nargs="?",
            default="docs/CHOSEN UONNAA WEB ARTICLES.md",
            help="Path to the articles markdown file",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write. Without this, runs in a transaction that's always rolled back.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file_path"])
        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        lines = file_path.read_text(encoding="utf-8").splitlines()
        articles = self._parse(lines)
        self.stdout.write(f"Parsed {len(articles)} article(s) from {file_path}")

        self.stats = {"created": 0, "chapters_created": 0, "no_date_in_source": 0, "errors": 0}
        self.error_rows = []
        self._chapter_cache = {}

        with transaction.atomic():
            for i, art in enumerate(articles, start=1):
                try:
                    with transaction.atomic():
                        self._import_article(art)
                except Exception as exc:  # noqa: BLE001 -- one bad article must not abort the batch
                    self.stats["errors"] += 1
                    self.error_rows.append((i, art["title"], str(exc)))

            if options["commit"]:
                self.stdout.write(self.style.WARNING("--commit passed: changes WRITTEN."))
            else:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run (no --commit): all changes rolled back."))

        self._print_report()

    # ---- parsing ---------------------------------------------------

    def _parse(self, lines):
        # Anchoring on the blank line (or lack of one) before a title was
        # a dead end -- plenty of articles run directly against the
        # previous one's last Editor's Note bullet with NO blank line
        # between them, so a backward blank-line scan silently swallows
        # that bullet into the next title. The "Article N:" title line
        # itself is the one reliably distinctive marker in this doc, so
        # title starts are found by matching it directly (forward scan),
        # one per Chapter: line, in the same order.
        chapter_idxs = [i for i, l in enumerate(lines) if _CHAPTER_LINE_RE.match(l.strip())]
        title_start_idxs = [i for i, l in enumerate(lines) if _TITLE_START_RE.match(l.strip())]
        if len(title_start_idxs) != len(chapter_idxs):
            raise CommandError(
                f"Found {len(title_start_idxs)} 'Article N:' title line(s) but "
                f"{len(chapter_idxs)} 'Chapter:' line(s) -- the parser's assumptions "
                "about this file's structure no longer hold; fix _parse() before importing."
            )

        titles = {}
        year_at = {}
        # The doc's first ~20 articles (before the one and only "2006
        # ARTICLES" header) carry no section header at all -- they're
        # implicitly 2005, confirmed by every dated one of them actually
        # being 2005.
        current_year = 2005

        for pos, meta_start in enumerate(chapter_idxs):
            title_lines = [l.strip() for l in lines[title_start_idxs[pos]:meta_start] if l.strip()]
            title_raw = " ".join(title_lines)
            title_raw = re.sub(r'^#+\s*', '', title_raw).replace('*', '')
            title_raw = _ARTICLE_PREFIX_RE.sub('', title_raw.strip())
            titles[pos] = _clean(title_raw).rstrip(': ').strip()

            # a year-header crossed between the previous article's end
            # and this title updates the running year from here on
            scan_start = title_start_idxs[pos - 1] if pos > 0 else 0
            for scan in range(scan_start, title_start_idxs[pos]):
                year_m = _YEAR_HEADER_RE.match(lines[scan].strip())
                if year_m:
                    current_year = int(year_m.group(1))
            year_at[pos] = current_year

        articles = []
        for pos, meta_start in enumerate(chapter_idxs):
            meta_lines = [lines[meta_start].strip()]
            j = meta_start + 1
            while (
                "Highlighted" not in " ".join(meta_lines)
                and j < len(lines)
                and lines[j].strip()
                and not lines[j].strip().startswith("**Article")
                and not _CHAPTER_LINE_RE.match(lines[j].strip())
            ):
                meta_lines.append(lines[j].strip())
                j += 1
            meta_text = _clean(" ".join(meta_lines))

            content_start = meta_start + len(meta_lines)
            content_end = title_start_idxs[pos + 1] if pos + 1 < len(title_start_idxs) else len(lines)
            # Drop the one and only "20XX ARTICLES" section-header lines --
            # they run with no blank line before the next title, so they'd
            # otherwise end up glued onto this article's Editor's Note.
            content_lines = [l for l in lines[content_start:content_end] if not _YEAR_HEADER_RE.match(l.strip())]
            body, references, editor_note = self._split_content(content_lines)

            chapter_m = (
                re.match(r'Chapter:\s*(.+?)\s+Date:', meta_text)
                or re.match(r'Chapter:\s*(.+?)\s+Is Feature', meta_text)
                or re.match(r'Chapter:\s*(.+)$', meta_text)
            )
            date_m = re.search(r'Date:\s*(.+?)\s*(?:Is Feature|$)', meta_text)
            feature_m = re.search(r'Is Feature:\s*(Yes|No)', meta_text)
            highlighted_m = re.search(r'Is Highlighted:\s*(Yes|No)', meta_text)
            date_raw = date_m.group(1).strip() if date_m else None

            articles.append({
                "title": titles[pos],
                "chapter_label": chapter_m.group(1).strip() if chapter_m else "",
                "parsed_date": _parse_date(date_raw, year_at[pos]),
                "is_feature": bool(feature_m and feature_m.group(1) == "Yes"),
                "is_highlighted": bool(highlighted_m and highlighted_m.group(1) == "Yes"),
                "had_date": bool(date_raw),
                "body": body,
                "references": references,
                "editor_note": editor_note,
            })
        return articles

    def _split_content(self, raw_lines):
        refs_idx = next((i for i, l in enumerate(raw_lines) if l.strip() == "References:"), None)
        note_idx = next((i for i, l in enumerate(raw_lines) if _NOTE_HEADER_RE.match(l.strip())), None)
        body_end = refs_idx if refs_idx is not None else (note_idx if note_idx is not None else len(raw_lines))
        refs_end = note_idx if note_idx is not None else len(raw_lines)

        body = self._join_paragraphs(raw_lines[:body_end])
        references = self._join_bullets(raw_lines[refs_idx + 1:refs_end]) if refs_idx is not None else ""
        editor_note = self._join_bullets(raw_lines[note_idx + 1:]) if note_idx is not None else ""
        return body, references, editor_note

    def _join_paragraphs(self, lines):
        paragraphs, current = [], []
        for line in lines:
            if line.strip():
                current.append(line.strip())
            elif current:
                paragraphs.append(_clean(" ".join(current)))
                current = []
        if current:
            paragraphs.append(_clean(" ".join(current)))
        return "\n\n".join(p for p in paragraphs if p)

    def _join_bullets(self, lines):
        return "\n".join(_clean(l.strip()) for l in lines if l.strip())

    # ---- import ------------------------------------------------------

    def _import_article(self, art):
        if not art["had_date"]:
            self.stats["no_date_in_source"] += 1

        chapter = None
        real_name = REAL_CHAPTER_NAMES.get(art["chapter_label"])
        if real_name:
            chapter = self._chapter_cache.get(real_name)
            if chapter is None:
                chapter, created = Chapter.objects.get_or_create(name=real_name)
                self._chapter_cache[real_name] = chapter
                if created:
                    self.stats["chapters_created"] += 1

        body = art["body"]
        if art["references"]:
            body += f"\n\nReferences:\n{art['references']}"
        if art["editor_note"]:
            body += f"\n\nEditor's Note:\n{art['editor_note']}"

        created_at = timezone.make_aware(datetime.combine(art["parsed_date"], datetime.min.time()))

        Article.objects.create(
            type=Article.ArticleType.NEWS,
            chapter=chapter,
            title=art["title"],
            body=body,
            is_feature=art["is_feature"],
            is_highlighted=art["is_highlighted"],
            is_published=True,
            created_at=created_at,
        )
        self.stats["created"] += 1

    def _print_report(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Import report ==="))
        for key, count in self.stats.items():
            self.stdout.write(f"  {key}: {count}")
        if self.error_rows:
            self.stdout.write(self.style.WARNING(f"\n{len(self.error_rows)} article(s) failed:"))
            for i, title, msg in self.error_rows:
                self.stdout.write(f"  #{i} {title!r}: {msg}")
