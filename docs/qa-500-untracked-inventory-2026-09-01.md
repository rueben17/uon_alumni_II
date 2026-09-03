# Untracked-file inventory — merge safety for `feature/qa-500-tests`

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Status:** 🛑 **Step 1 only — nothing committed.** Awaiting confirmation before adding anything.

Addresses loose end #1 in [`qa-500-backfill-apply-2026-09-01.md`](qa-500-backfill-apply-2026-09-01.md): an untracked file is not in the branch, so a merge that looks complete would ship code whose template is absent.

---

## Headline

**One file must be committed:** `templates/qr_manager/staff_verify.html`.

It is the **only** untracked file that committed code depends on. Merging without it would 500 every staff badge scan in production, because `verify_scan` renders it by name.

**Nothing depended-on is git-ignored.** `.env`, `alumni/` and the `__pycache__` directories are correctly excluded and stay that way. `.gitignore` was not touched.

**There are no modified-unstaged files** — the working tree is otherwise clean.

---

## (a) Must commit — depended on by committed code

| File | Referenced by |
|---|---|
| `templates/qr_manager/staff_verify.html` | `apps/qr_manager/views.py:222` — `template = "qr_manager/staff_verify.html"` |

### How this was established

Every template name appearing in Python across `apps/` and `main/` was extracted and checked against `git ls-files`. Exactly one came back untracked, and it is this file.

The same sweep confirmed every module the QA-500 work added is already tracked:

| Module | State |
|---|---|
| `apps/user/signals.py` | tracked |
| `apps/student/site_urls.py` | tracked |
| `apps/user/migrations/0002_backfill_user_profiles.py` | tracked |
| `apps/home/migrations/0016_seed_tier_benefits.py` | tracked |

---

## (b) Must not commit

| Path | Reason |
|---|---|
| `media/banner/alumni_qr_watermark/2026/08/21/` | Runtime upload, not source |
| `media/scholarship_applications/` | Runtime upload, not source |

**Reported, not acted on:** `media/` is not listed in `.gitignore`, which is why these surface as untracked at all. That looks like a gap worth closing, but editing `.gitignore` is outside this pass's scope and would need its own decision.

---

## (c) Unclear — needs a human decision

### Six orphan snippet templates

`templates/snippets/` — `article.html`, `chapter_card.html`, `ec_profile_card.html`, `front_page_card.html`, `in_memoriam_card.html`, `secretariat_card.html`.

**None is referenced by any `{% include %}`, `{% extends %}`, `render()` or `template_name`**, and they do not include one another. They appear to be unfinished work from a prior session.

Two apparent references were **substring false positives**, worth recording so they are not re-investigated later:

- `templates/home/alumni_home.html:162` and `:175` include `feature_article.html` and `highlighted_article.html` — different files that merely end in `article.html`.
- `templates/home/alumni_home.html:64` mentions `front_page_card.html` **inside a comment**, not an include.

Not needed for merge safety. Committing them is a content decision, not a hygiene one.

### Six documentation files from the 2026-08-21 audit

`docs/payment-confirmation-workflow.md`, `docs/qa-audit-2auth-apply-2026-08-21.md`, `docs/qa-audit-2auth-proposal-2026-08-21.md`, `docs/qa-audit-phase0-2026-08-21.md`, `docs/qa-audit-phase1-2026-08-21.md`, `docs/qa_audit_report.md`.

Prior-session documentation with no code dependency. Probably worth tracking alongside this sweep's own docs, but that is an editorial call rather than a merge-safety one.

---

## One non-issue, for completeness

`templates/admin/login.html` appeared as "referenced but missing from `templates/`". It is fine:

- Referenced only in an assertion at `apps/qr_manager/tests.py:351`.
- Resolves from Django's own admin app via `APP_DIRS`, confirmed at
  `alumni/Lib/site-packages/django/contrib/admin/templates/admin/login.html`.

No project template is needed, and nothing is missing.

---

## Proposed Step 2

One commit, adding a single file:

```
git add templates/qr_manager/staff_verify.html
git commit -m "Track untracked templates/assets required by the QA-500 sweep"
```

**Awaiting confirmation.** Say the word to proceed with just that file, or to fold in the six documentation files and/or the six orphan snippets at the same time.
