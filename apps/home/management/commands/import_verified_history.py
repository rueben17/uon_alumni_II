# apps/home/management/commands/import_verified_history.py
"""
Replaces the Article rows created by the now-retired
import_chosen_articles.py (sourced from docs/CHOSEN UONNAA WEB
ARTICLES.md, an unverified first draft) with the fact-checked,
date-corrected set in docs/origins/deepseek_markdown_20261028_ef6da2.md.

Why this exists (2026-10-28): the first draft went live with fabricated
or unconfirmed figures (invented membership-milestone and endowment-fund
numbers, a "60th Anniversary" article that's chronologically impossible,
an unrelated University academic-record article) and several wrong
chapter-launch dates. The Association flagged this as a serious accuracy
problem on a public, front-facing site -- "no guessing" on history,
motto, core values. The origins file is the Secretariat-reviewed
correction: verified dates (marked (dagger)), and an explicit list of
article topics that must NOT be published until someone confirms them
against a primary source.

SAFE BY DEFAULT: runs inside a transaction that's rolled back unless
--commit is passed. --commit also deletes every existing type=NEWS
Article first (the entire NEWS set came from the retired unverified
import; nothing else has ever used that type) before writing the
corrected set, so this is a full replace, not an additive import.

Exclusion rule: an article is skipped (not imported at all) if its
Editor's Note contains "do not publish" (case-insensitive), or if its
title is "UONAA Launches Strategic Plan 2024-2029" (flagged as
unconfirmed via different wording -- "no primary source located ...
unconfirmed" -- so the substring rule alone wouldn't catch it). This is
the same set the source file's own "Articles Removed -- Do Not
Reinstate" table calls out (13 articles: repeated membership-milestone
and endowment-fund figures with no primary source, plus the unconfirmed
2024 Strategic Plan).
"""
import html
import re
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.home.models import Article, Chapter

REAL_CHAPTER_NAMES = {
    "Human Medicine Chapter": "Medical Chapter",
    "Computing & Informatics Chapter": "Computing & Informatics Chapter",
    "Pharmacy Chapter": "Pharmacy Chapter",
    "Engineering Chapter": "Engineering Chapter",
    "Education Chapter": "Education Chapter",
    "Architecture, Design and Development": "Architecture, Design and Development Chapter",
    "Law Chapter": "Law Chapter",
}

MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
}

# Article 65's disclaimer doesn't contain "do not publish" literally
# ("no primary source located ... unconfirmed"), so it needs its own
# rule alongside the substring check below.
EXCLUDED_TITLES = {"UONAA Launches Strategic Plan 2024-2029"}

_ARTICLE_HEADER_RE = re.compile(r'^## Article \d+:\s*(.+?)\s*$')
_FIELD_RE = re.compile(r'^\*\*(Chapter|Date):\*\*\s*(.*)$')
_FEATURE_RE = re.compile(r'^\*\*Is Feature:\*\*\s*(Yes|No)\s*\|\s*\*\*Is Highlighted:\*\*\s*(Yes|No)\s*$')


def _clean(text):
    return html.unescape(text).strip()


def _parse_date(raw):
    # Strip the verified-checkmark emoji and any "(...)"/"*(...)* "
    # annotation trailing the real date (e.g. "5 February 2005 ✅",
    # "2004 (formation; original draft dated 10 Feb 2005)").
    raw = raw.split("✅")[0]
    raw = re.sub(r'\*?\(.*?\)\*?', '', raw).strip()

    m = re.match(r'^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$', raw)
    if m and m.group(2).upper() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).upper()], int(m.group(1)))
    m = re.match(r'^([A-Za-z]+)\s+(\d{4})$', raw)
    if m and m.group(1).upper() in MONTHS:
        return date(int(m.group(2)), MONTHS[m.group(1).upper()], 1)
    m = re.match(r'^(\d{4})$', raw)
    if m:
        return date(int(m.group(1)), 1, 1)
    # Ranges ("2015-2016", "March-December 2018") -- fall back to the
    # first 4-digit year found, 1 January.
    m = re.search(r'(\d{4})', raw)
    if m:
        return date(int(m.group(1)), 1, 1)
    raise ValueError(f"Could not parse date: {raw!r}")


class Command(BaseCommand):
    help = "Replace Article(type=news) with the verified set from docs/origins/"

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path", nargs="?",
            default="docs/origins/deepseek_markdown_20261028_ef6da2.md",
            help="Path to the verified history markdown file",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write (and delete the old NEWS set first). Without this, "
                 "runs in a transaction that's always rolled back.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file_path"])
        if not file_path.exists():
            raise CommandError(f"File not found: {file_path}")

        lines = file_path.read_text(encoding="utf-8").splitlines()
        articles = self._parse(lines)
        self.stdout.write(f"Parsed {len(articles)} article(s) from {file_path}")

        self.stats = {
            "existing_news_deleted": 0, "created": 0, "excluded": 0,
            "chapters_created": 0, "errors": 0,
        }
        self.error_rows = []
        self._chapter_cache = {}

        with transaction.atomic():
            existing = Article.objects.filter(type=Article.ArticleType.NEWS)
            self.stats["existing_news_deleted"] = existing.count()
            existing.delete()

            for i, art in enumerate(articles, start=1):
                if self._is_excluded(art):
                    self.stats["excluded"] += 1
                    continue
                try:
                    with transaction.atomic():
                        self._import_article(art)
                except Exception as exc:  # noqa: BLE001
                    self.stats["errors"] += 1
                    self.error_rows.append((i, art["title"], str(exc)))

            if options["commit"]:
                self.stdout.write(self.style.WARNING("--commit passed: changes WRITTEN."))
            else:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run (no --commit): all changes rolled back."))

        self._print_report()

    # ---- exclusion ---------------------------------------------------

    def _is_excluded(self, art):
        if art["title"] in EXCLUDED_TITLES:
            return True
        return "do not publish" in art["editor_note"].lower()

    # ---- parsing -------------------------------------------------

    def _parse(self, lines):
        header_idxs = [i for i, l in enumerate(lines) if _ARTICLE_HEADER_RE.match(l.strip())]
        articles = []
        for pos, start in enumerate(header_idxs):
            end = header_idxs[pos + 1] if pos + 1 < len(header_idxs) else len(lines)
            block = lines[start:end]

            title = _clean(_ARTICLE_HEADER_RE.match(block[0].strip()).group(1))

            chapter_label = ""
            date_raw = None
            is_feature = False
            is_highlighted = False
            body_start = 1
            for i, line in enumerate(block[1:], start=1):
                stripped = line.strip()
                field_m = _FIELD_RE.match(stripped)
                feature_m = _FEATURE_RE.match(stripped)
                if field_m and field_m.group(1) == "Chapter":
                    chapter_label = _clean(field_m.group(2))
                elif field_m and field_m.group(1) == "Date":
                    date_raw = field_m.group(2).strip()
                elif feature_m:
                    is_feature = feature_m.group(1) == "Yes"
                    is_highlighted = feature_m.group(2) == "Yes"
                    body_start = i + 1
                    break

            content_lines = block[body_start:]
            body, references, editor_note = self._split_content(content_lines)

            articles.append({
                "title": title,
                "chapter_label": chapter_label,
                "parsed_date": _parse_date(date_raw) if date_raw else None,
                "is_feature": is_feature,
                "is_highlighted": is_highlighted,
                "body": body,
                "references": references,
                "editor_note": editor_note,
            })
        return articles

    def _split_content(self, raw_lines):
        refs_idx = next((i for i, l in enumerate(raw_lines) if l.strip() == "**References:**"), None)
        note_idx = next((i for i, l in enumerate(raw_lines) if l.strip() == "**Editor's Note:**"), None)
        body_end = refs_idx if refs_idx is not None else (note_idx if note_idx is not None else len(raw_lines))
        refs_end = note_idx if note_idx is not None else len(raw_lines)

        body = self._join_paragraphs(raw_lines[:body_end])
        references = self._join_bullets(raw_lines[refs_idx + 1:refs_end]) if refs_idx is not None else ""
        editor_note = self._join_bullets(raw_lines[note_idx + 1:]) if note_idx is not None else ""
        return body, references, editor_note

    def _join_paragraphs(self, lines):
        paragraphs, current = [], []
        for line in lines:
            stripped = line.strip()
            if stripped == "---":
                continue
            if stripped:
                current.append(stripped)
            elif current:
                paragraphs.append(_clean(" ".join(current)))
                current = []
        if current:
            paragraphs.append(_clean(" ".join(current)))
        return "\n\n".join(p for p in paragraphs if p)

    def _join_bullets(self, lines):
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if stripped == "---" or not stripped:
                continue
            cleaned.append(_clean(stripped))
        return "\n".join(cleaned)

    # ---- import ------------------------------------------------------

    def _import_article(self, art):
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
