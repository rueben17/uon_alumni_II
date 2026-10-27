# Legacy membership import — applied 2026-10-27

## What happened
Bulk-imported the Secretariat's legacy membership spreadsheet
(`docs/data/ALL MEMBERS AS AT 27-7-26.xlsx`, 4,611 rows, gitignored — never
committed, real PII) into both the local dev DB and production, via the
existing `apps/home/management/commands/import_legacy_memberships.py`.

Sequence: dry-run locally → `--commit` locally → dry-run on the VPS
(numbers matched local exactly) → `--commit` on the VPS.

## Result (identical on both local and production)
```
created: 4021
updated: 131
skipped_no_email: 459
errors: 0
```

## Known, non-blocking issues surfaced by the run
- **459 rows skipped** — no email on the source row, and `User.email` is
  required+unique, so there's no account to attach them to. Not
  recoverable without going back to the Secretariat for an email per
  person; left for a future pass.
- **61 phone numbers already claimed** by another account (logged with
  row/number/existing-owner-email) — left blank on the new row rather than
  failing it, since a shared office line between two alumni is plausible
  and shouldn't block the import. Needs manual review to confirm whether
  any of these are actually duplicate people.
- **Unmapped free-text values** logged for `Title`, `Nationality`,
  `College`, `Faculty`, and `Course` — the command's `*_MAP` normalization
  tables don't cover every historical spelling/abbreviation in the sheet
  (e.g. faculty name variants, course title variants accumulated over
  decades of manual data entry). These rows still imported successfully
  (the unmapped value is kept as free text rather than mapped to a
  canonical FK), so nothing is broken — just not as normalized as it could
  be. Extending the `*_MAP` tables to cover more of these is a worthwhile
  follow-up but wasn't required to get the data online.

## Note on a bug found and fixed during this work
The import command didn't originally set `Membership.subscription_amount`/
`amount_paid`, so the analytics revenue dashboard read zero for every
imported membership. Fixed in the command and backfilled on the
already-imported rows before the production run.
