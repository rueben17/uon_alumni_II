# feature/qa-500-tests — merge readiness

**Date:** 2026-09-03
**Branch:** `feature/qa-500-tests`
**Status:** Ready for you to merge to `main` and push. Not done by me — see commands below.

---

## Verified

| Check | Result |
|---|---|
| Working tree | Clean — only two pre-existing untracked media folders, unrelated to any commit |
| Suite | **261 tests, OK** |
| `makemigrations --check` | No changes detected |

---

## What this branch carries

- **The full QA-500 sweep** — every reproduced Server 500 across the project, tagged Tier A/B, fixed or documented
- **The coverage build**, priorities 1–6: membership lifecycle, OAuth adapter, payment confirmation, forms, QR-code generation (59% → 69% overall; several modules to 96–100%)
- **Fixes:**
  - **B** — bare `home:` reverse 500ing staff login
  - **D** — payment completed outside the bulk admin action never activated the membership
  - **F** — registration rejected the registrant's own phone number
  - **K** — `installment_amount` wrongly required, blocking lump-sum registration
  - **J** — no size limit on the Digital ID photo; now capped at 2 MB
- **Finding L, code half** — `STORAGES` defined so Cloudinary and WhiteNoise are actually active, test isolation added, `migrate_media_to_cloudinary` command written. **The production runbook has not run** — that is separate, host-only work.
- **E and H recorded as settled decisions** — refund policy and instalment-activation, neither a defect.

---

## Merge and push — yours to run

```
git checkout main
git merge --no-ff feature/qa-500-tests
git push origin main
```

I have not run these. I also have not touched the finding-L runbook.

---

## What happens after you merge and push

1. **Run the finding-L runbook** on the production host, in order — [`finding-L-runbook-2026-09-03.md`](finding-L-runbook-2026-09-03.md). It precedes the Neon → VPS migration.
2. **Verify the Cloudinary copies** before telling me to continue.
3. Only once you've confirmed both of those: I untrack the 114 already-committed media files (`git rm --cached`, working files left in place) and delete the three fix branches now folded into this one.

Tell me to continue once the runbook is done and verified.
