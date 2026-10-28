# Correcting the UONAA history articles — applied 2026-10-28 (local only so far)

## What was wrong
The first batch of imported history articles (`import_chosen_articles.py`,
sourced from `docs/CHOSEN UONNAA WEB ARTICLES.md`) was an unverified
first draft. It went live — both local dev and production — with:

- **Fabricated content**: a "University of Nairobi Celebrates 60th
  Anniversary of Alumni Association" article (chronologically
  impossible — the Association was founded in 2005) and an unrelated
  University academic-record article (a Doctor of Science award) that
  isn't UONAA history at all.
- **Invented numbers presented as fact**: a standalone "Membership
  Surpasses N" or "Endowment Fund Reaches KSh N Million" article for
  nearly every year from 2005 to 2025, with no primary source for any
  of the figures.
- **Wrong dates**: e.g. the Education Chapter's launch was imported as
  July 2012; the real date is 30 April 2015. The 10th and 20th
  anniversary dates were off by three weeks and 23 days respectively.

The Association flagged this directly: front-facing pages — history,
motto, core values — have to be an accurate representation, not a
guess, and this wasn't meeting that bar.

## The fix
`docs/origins/` contains the Secretariat-reviewed correction:
- `deepseek_markdown_20261028_ef6da2.md` — the full history, fact-checked,
  with dates corrected against verified sources, and an explicit list
  of article topics that must not be published until confirmed.
- `deepseek_markdown_20261028_c0dc13.md` — governance/constitution
  reference (membership categories, fees, chapter-formation rules) —
  separately confirmed to already match what's seeded in
  `seed_membership_tiers.py` (sourced from the official membership
  form), so no correction needed there.

New command `apps/home/management/commands/import_verified_history.py`:
replaces every `Article(type=news)` row (the entire set came from the
retired command; nothing else used that type) with the 59 articles from
the verified file that don't carry a "do not publish" flag. The 13
excluded (all repeated membership-milestone/endowment-fund figures with
no primary source, plus an unconfirmed "Strategic Plan 2024-2029") are
simply not imported — matching the source file's own "Articles Removed
— Do Not Reinstate" list.

`import_chosen_articles.py` is left in the repo but marked RETIRED in
its own docstring — explains why, points at this command — rather than
deleted, so the mistake and its fix both stay visible.

## Result (local dev DB)
```
existing_news_deleted: 94
created: 59
excluded: 13
chapters_created: 1   (Law Chapter — new in the verified set)
errors: 0
```

## Not yet done
This only ran locally. Production still has the 94 unverified articles
— needs the same `--commit` run on the VPS to replace them.
