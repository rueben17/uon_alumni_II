# Stale `qr_manager` fixture repair — suite fully green

**Date:** 2026-09-01
**Branch:** `feature/qa-500-tests`
**Commit:** `397635d`
**Closes:** loose end #2 in [`qa-500-backfill-apply-2026-09-01.md`](qa-500-backfill-apply-2026-09-01.md)

Test-only. No production code, signal, migration, settings or real-data change.

---

## Headline

**The suite went from 94 tests with 4 errors to 113 tests with none.**

The count matters more than the errors did. A `setUpClass` failure takes the entire class down, so the 19 additional tests are ones these four classes **had never been running** — roughly 17% of the suite was silently absent. That is exactly the false-coverage baseline this pass existed to correct: those paths looked untested when in fact they were merely unexecuted.

| Before | After |
|---|---|
| 94 tests, 4 errors | **113 tests, 0 errors, 0 failures** |

---

## Root cause — confirmed, not assumed

```
TypeError: Employee() got unexpected keyword arguments: 'given_name', 'family_name'
```

`Employee` has not held name data since it moved to `UserProfile` per `docs/rebuild-schema.md`; `apps/staff/models.py:186` records that call sites read through `self.user.profile.*` instead. These fixtures were never updated.

Verified by introspection rather than taken on trust:

```
Employee concrete/relational fields:
  academic_rank, created_at, department, employed_on, employee_qrcode,
  employment_type, id, is_active, position, qr_code_image, research_unit,
  service_unit, slug, staff_id, staff_track, updated_at, user

  has given_name? False   |   has family_name? False
  Position fields: id, title, description, level
```

So the diagnosis in the backfill doc held, `Position.title` is correct, and no stop was needed.

---

## What changed

### Four classes, seven `Employee()` calls

| Class | Calls | Names preserved |
|---|---|---|
| `QRCodeAdminScopingTests` | 2 | Lib/Employee, Fin/Employee |
| `QRCodeAdminPermissionMethodTests` | 1 | Fin/Employee |
| `QRSupervisorSiteTests` | 2 | Lib/Employee3, Fin/Employee3 |
| `ScanLogAdminScopingTests` | 2 | Lib/Employee4, Fin/Employee4 |

Each now omits the moved kwargs and fills the auto-created profile instead, through a `_name_profile` helper mirroring the one already in `apps/staff/tests.py`:

```python
        cls.lib_emp = Employee.objects.create(
            user=cls.lib_emp_user,
            staff_track=Employee.StaffTrack.SERVICE, service_unit=cls.library,
        )
        _name_profile(cls.lib_emp_user, "Lib", "Employee")
```

Every original name value is preserved exactly.

**One wrinkle:** the `fin_emp` block is textually identical in `QRCodeAdminScopingTests` and `QRCodeAdminPermissionMethodTests`, so a single replacement served both — worth knowing before anyone edits one of them in isolation.

### One in-body read repointed

`QRSupervisorSiteTests` asserted that a blocked admin POST mutated nothing:

```python
        self.lib_emp.refresh_from_db()
        self.assertEqual(self.lib_emp.given_name, "Lib")      # field no longer exists
```

now:

```python
        self.lib_emp.refresh_from_db()
        self.assertEqual(self.lib_emp.user.profile.given_name, "Lib")
```

The assertion's point is unchanged.

**The POST payload was deliberately left alone.** It sends `data={"given_name": "Changed"}`, a field the form no longer has — but the request is rejected with `403` before form processing, and `403` is what the test actually asserts. Changing the payload would have been restructuring rather than repair, so it stays as-is.

---

## Scope

`git status` showed only `apps/qr_manager/tests.py`, plus the eight deliberately-untracked items carried over from the previous pass (two `media/` upload directories and the six orphan snippets).

No other `qr_manager` test class was touched.

---

## Where things stand

- **All nine QA-500 findings closed.**
- **Suite fully green: 113 tests, 0 errors.**
- **Branch merge-safe** — every code-referenced template and module is tracked.
- 35 commits on `feature/qa-500-tests`, each independently revertable.

There is now a genuine baseline to measure coverage against, which was the point.

### Still open, none blocking

1. **`media/` is not in `.gitignore`** — the only reason those upload directories surface as untracked. One line, but its own decision.
2. **Six orphan snippet templates** — verified unreferenced by any `{% include %}`, `{% extends %}`, `render()` or `template_name`. Either wire them up or delete them; left untracked they resurface in every status check.
3. **The branch is unmerged**, and whether to squash the documentation commits is your call.
