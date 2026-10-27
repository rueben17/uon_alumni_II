# Chosen UONAA web articles import — applied 2026-10-27 (local only)

## What happened
Built `apps/home/management/commands/import_chosen_articles.py` to parse
`docs/CHOSEN UONNAA WEB ARTICLES.md` (~95 curated historical UONAA/UoN
news articles, 2005–2015) into `Article` rows, and ran it against the
local dev DB.

```
created: 94
chapters_created: 6
no_date_in_source: 1
errors: 1
```

## Decisions behind the mapping (confirmed with the Association)
- **Chapter FK**: the doc's `Chapter:` label is mostly a topic beat
  ("Central", "Mombasa Campus", "Student Affairs", "Research &
  Innovation", "Journalism And Mass Communication") rather than a real
  alumni interest group, and the `Chapter` table was empty beforehand.
  Only labels naming a genuine chapter got a real `Chapter` row + FK
  link: **Medical, Computing & Informatics, Pharmacy, Engineering,
  Education, Architecture/Design/Development**. Everything else stays
  `chapter=None`. These 6 new `Chapter` rows have no `faculty` or
  `year_launched` set — worth filling in via the admin if wanted.
- **Publish state**: all imported articles are `is_published=True` —
  live immediately, despite most containing unresolved
  `[VERIFY: ...]`/`[SOURCE NEEDED: ...]` editorial flags.
- **References / Editor's Note**: `Article` has no dedicated field for
  either, so both are appended to `body` as trailing sections (so the
  sourcing/fact-checking trail isn't lost), not shown as separate
  structured data.
- All imported as `type="news"`; `is_feature`/`is_highlighted` map
  directly from the doc's own `Is Feature`/`Is Highlighted` flags.
  `created_at` is set to the article's own historical date (parsed from
  the doc), not the import date, so these sort/display correctly
  alongside future news.

## Known issues, not blocking
- **1 genuine duplicate skipped**: two articles in the source doc are
  both titled "University of Nairobi Mourns Prof. George Magoha," dated
  identically (27 Jan 2023), under two different yearly sections. The
  second hit `Article`'s `unique_together('title', 'created_at')` and
  was skipped — not a parser bug, the source document really does
  contain the same article twice.
- **1 article with no date at all in the source** ("The First Alumni
  Newsletter") — fell back to 1 Jan of its section's year (2005).
- **Title casing**: `Article.title` is a custom `Title` field
  (`apps/home/models.py`) that runs `.title()` on every value before
  saving — pre-existing, site-wide behaviour, not introduced by this
  import. It affects these rows the same way it already affects every
  other `Article`: acronyms lose their caps (e.g. "UONAA" → "Uonaa",
  "KSh" → "Ksh" wherever they land in a title). Flagging this because it
  visibly affects how these specific titles will read on the public
  site — not fixing it here since it's an existing, unrelated model
  behaviour out of this task's scope.

## Not yet done
This only ran against the **local dev DB**. Nothing has been imported to
production — that needs an explicit decision, per this repo's guardrail
on touching production data.
