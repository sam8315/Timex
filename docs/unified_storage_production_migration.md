# Unified Storage — Production Migration Runbook

This document describes the **controlled production procedure** for activating
Timex Unified File Storage for Contracts, Education certificates, and Avatars.

> **Scope of the current tooling phase**
>
> - Read-only preflight and dry-run are implemented.
> - Real execute (`dry_run=False` / `--execute`) is **not** implemented in this phase.
> - Legacy source files are **never** deleted by migration tooling.
> - Employee Documents are reported under storage layout only; they are **not** migrated here.

---

## Tools

```text
# Storage + DB readiness (read-only)
python -m web.services.storage_production_preflight

# Same checks + StorageActivationService.execute(dry_run=True)
python -m web.services.storage_production_preflight --dry-run

# Persist machine-readable report
python -m web.services.storage_production_preflight --dry-run --json-out backups/storage_preflight.json
```

Exit codes:

- `0` — overall `READY`
- `1` — overall `NOT READY` (blockers listed in the report)
- `2` — unsupported / unsafe flags (e.g. `--execute` in this phase)

---

## مرحله 1 — قبل از Migration

1. **Specify `TIMEX_STORAGE_ROOT`**
   - Prefer an absolute path **outside** the Timex source tree.
   - Example: `D:\data\timex-storage` or `/var/lib/timex/storage`.
   - Confirm the process user can read/write that directory.

2. **Confirm storage is outside the source tree**
   - Avoid `<repo>/storage` in production when possible.
   - Preflight warns when the root resolves under the project directory.

3. **Disk space**
   - Compare free space against the total size of legacy roots in the preflight report.
   - Keep a comfortable margin (at least the size of all candidate files + headroom).

4. **Full PostgreSQL backup**
   - Take a restorable dump/snapshot before any execute phase.
   - Record backup path, timestamp, and operator.

5. **Legacy file backup**
   - Back up at least:
     - `web/static/uploads/contracts`
     - `web/static/uploads/certificates`
     - `web/static/uploads/avatars`
     - `web/private_uploads/contracts`
   - Prefer a filesystem snapshot or archive with checksums.

6. **Timestamp and checksum inventory (recommended)**
   - Save the preflight/dry-run JSON report.
   - Optionally record SHA-256 samples of high-value contract/education files.

7. **Maintenance window / upload freeze**
   - Prefer a short maintenance window so new uploads do not race the migration.
   - If a full freeze is impossible, document the residual risk and re-run preflight immediately before execute.

8. **Run preflight**
   ```text
   python -m web.services.storage_production_preflight --json-out backups/storage_preflight.json
   ```

9. **Run dry-run**
   ```text
   python -m web.services.storage_production_preflight --dry-run --json-out backups/storage_dry_run.json
   ```

10. **Store reports**
    - Keep human output and JSON under an auditable backup location.
    - Do not discard reports until post-migration verification is signed off.

---

## مرحله 2 — تصمیم Go / No-Go

Migration execute is allowed **only** when all of the following are true:

| Gate | Requirement |
|------|-------------|
| DB backup | PostgreSQL backup completed and verified restorable |
| Legacy backup | Legacy upload trees backed up |
| Storage root | Exists, accessible, writable, preferably outside source tree |
| Conflicts | Destination conflicts = 0 |
| Invalid refs | Invalid/unrecognized references reviewed and accepted or fixed |
| Dry-run | Dry-run report reviewed by operator |
| Disk space | Free space sufficient for all ready candidates |
| Window | Maintenance window (or upload freeze) agreed |

If preflight overall status is `NOT READY`, **do not** proceed to execute.

Missing sources should be reviewed: they may be historical orphans. Decide whether to fix, skip, or accept before go.

---

## مرحله 3 — اجرای واقعی

> **Not implemented in this phase.**

When a later phase adds a controlled execute command, the intended procedure is:

1. Re-run preflight + dry-run immediately before execute.
2. Confirm Go/No-Go checklist again.
3. Run the dedicated execute tooling against the intended target only.
4. Capture logs and the final activation report.
5. Keep legacy sources intact.

Do **not** invent ad-hoc scripts that call `StorageActivationService.execute(dry_run=False)` outside the approved tooling.

---

## مرحله 4 — Verification

After a future real migration:

1. Compare DB reference counts (contracts / education / avatars) before vs after.
2. Spot-check SHA-256 for a sample of migrated files (source vs destination).
3. Test secure Contract download (admin + owner paths as applicable).
4. Test secure Education certificate download.
5. Test Avatar serving via the secure profile route.
6. Confirm direct `/static/uploads/contracts|certificates|avatars/...` access returns 404 (except the public `uploads/avatars/image.png` placeholder).
7. **Retain legacy sources** until final sign-off. Deletion is a separate, explicit decision — not part of activation.

---

## مرحله 5 — Rollback

Principles:

- Migration tooling **does not delete** legacy sources.
- The PostgreSQL backup is the primary rollback reference for DB paths.
- Destination files under `TIMEX_STORAGE_ROOT` are not deleted automatically; removing them is a separate operational decision.
- If migration is partial/incomplete, inspect DB state first (which rows still point at legacy vs unified keys).
- Filesystem rollback and DB rollback are **independent**:
  - Restoring DB paths without touching destinations is usually enough to restore serving via legacy resolve.
  - Deleting destinations while DB already points at unified keys will break downloads — avoid that unless coordinated.

Suggested order if aborting after a partial execute (future phase):

1. Stop further writes / uploads if needed.
2. Restore DB from the pre-migration backup (or surgically revert affected path columns).
3. Verify secure downloads again via legacy keys.
4. Leave destinations in place until cleanup is deliberately approved.

---

## Related code

- `web/services/file_storage.py` — unified storage layout
- `web/services/storage_migration.py` — filesystem copy helpers (no DB)
- `web/services/storage_activation.py` — DB-backed activation
- `web/services/storage_production_preflight.py` — production readiness CLI (this phase)
