# Untracked-file commit pass — branch made merge-safe

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Executes:** [`qa-500-untracked-inventory-2026-09-01.md`](qa-500-untracked-inventory-2026-09-01.md), Step 2

**Commits:** `72ec019` (template), `7a3c1d3` (docs)

No behaviour change. No source, settings, migration or `.gitignore` edit.

---

## Precondition check

`git status --porcelain` was re-run before committing and matched the signed-off inventory exactly — the same fifteen entries, nothing added or changed since. No divergence, so no stop was needed.

---

## Commit 1 — `72ec019` — merge safety

```
templates/qr_manager/staff_verify.html | 50 ++++++++++++++++++++++++++++++++++
1 file changed, 50 insertions(+)
```

`apps/qr_manager/views.py:222` renders `"qr_manager/staff_verify.html"` by name, but the template had never been committed. It predates this sweep — it was added when the staff badge scan was repointed away from the full employee detail page — and simply never entered version control.

**Merging without it would have deployed a view whose template is absent, 500ing every staff badge scan.** That is the entire reason this pass existed.

Established as the only such file by extracting every template name appearing in Python across `apps/` and `main/` and checking each against the index. Exactly one came back missing.

## Commit 2 — `7a3c1d3` — project history

```
docs/payment-confirmation-workflow.md      |  76 +++++
docs/qa-audit-2auth-apply-2026-08-21.md    |  64 ++++++
docs/qa-audit-2auth-proposal-2026-08-21.md |  74 ++++++
docs/qa-audit-phase0-2026-08-21.md         | 110 +++++++
docs/qa-audit-phase1-2026-08-21.md         | 103 ++++++
docs/qa_audit_report.md                    | 115 +++++++
6 files changed, 542 insertions(+)
```

Documentation from the 2026-08-21 QA audit plus the payment-confirmation workflow write-up. No code depends on any of them; they are committed as project history alongside this sweep's own docs.

**Kept deliberately separate from commit 1** — deployment correctness and record-keeping are different concerns, and the first should be revertable without disturbing the second.

Both commits were verified with `git show --stat`: one file in the first, exactly six in the second, no strays in either.

---

## Final state — deliberately still untracked

```
?? media/banner/alumni_qr_watermark/2026/08/21/
?? media/scholarship_applications/
?? templates/snippets/article.html
?? templates/snippets/chapter_card.html
?? templates/snippets/ec_profile_card.html
?? templates/snippets/front_page_card.html
?? templates/snippets/in_memoriam_card.html
?? templates/snippets/secretariat_card.html
```

Two runtime upload directories and the six unreferenced orphan snippets, all left as signed off.

**No depended-on untracked files remain. The branch is merge-safe.**

---

## Two open items — neither blocking

1. **`media/` is not in `.gitignore`.** That is the only reason the upload directories surface as untracked at all. A one-line change, but its own decision, and out of scope for this pass.
2. **The six orphan snippets** — `article.html`, `chapter_card.html`, `ec_profile_card.html`, `front_page_card.html`, `in_memoriam_card.html`, `secretariat_card.html`. Verified unreferenced by any `{% include %}`, `{% extends %}`, `render()` or `template_name`. Either finish wiring them up or delete them; leaving them untracked indefinitely just means they resurface in every future status check.

---

## Where the sweep stands

All nine QA-500 findings closed, across 33 commits on `feature/qa-500-tests`, each independently revertable. Suite: 94 tests, 4 errors — all four pre-existing `qr_manager` fixture errors (`Employee()` kwargs for fields that moved to `UserProfile`), untouched throughout as out of scope.

The branch is unmerged; merging, and whether to squash the documentation commits, remain your call.
