# Unified Storage — Production Migration Runbook

This document describes the **controlled production procedure** for activating
Timex Unified File Storage for Contracts, Education certificates, and Avatars.

> **Safety invariants**
>
> - Legacy source files are **never** deleted by migration tooling.
> - Employee Documents are reported under storage layout only; they are **not** migrated here.
> - Real `--execute` requires backup manifest verification, dry-run, hard Go/No-Go gates,
>   and explicit `--confirm-production`.
> - Activate a **maintenance window / upload freeze** before execute.

---

## Tools

### Read-only readiness (unchanged)

```text
python -m web.services.storage_production_preflight
python -m web.services.storage_production_preflight --dry-run
python -m web.services.storage_production_preflight --dry-run --json-out backups/storage_dry_run.json
```

### Controlled migration CLI

```text
# Evaluate execute gates (no migration)
python -m web.services.storage_production_migration --preflight \
  --backup-manifest backups/storage_migration_backup.json

# Controlled execute (ONLY after Go/No-Go)
python -m web.services.storage_production_migration --execute \
  --backup-manifest backups/storage_migration_backup.json \
  --confirm-production \
  --journal-dir backups
```

Optional:

```text
--allow-missing N          # default 0 — reject any missing candidates
--journal-out PATH         # explicit journal JSON path
--json-out PATH            # summary JSON
```

Exit codes:

- `0` — gates allowed / execute succeeded
- `1` — blocked by gates or execute aborted
- `2` — reserved for unsupported/unsafe usage

---

## Recommended procedure

```text
Backup
→ Manifest verification
→ Preflight
→ Dry-run
→ Go/No-Go
→ Explicit production confirmation
→ Execute
→ Verification
→ Keep legacy sources
```

---

## مرحله 1 — Backup

1. Set `TIMEX_STORAGE_ROOT` to an absolute path **outside** the Timex source tree.
2. Take a full PostgreSQL backup (restorable dump/snapshot).
3. Archive legacy trees:
   - `web/static/uploads/contracts`
   - `web/static/uploads/certificates`
   - `web/static/uploads/avatars`
   - `web/private_uploads/contracts`
4. Record checksums (SHA-256) for both backup artifacts.
5. Write a backup manifest, for example `backups/storage_migration_backup.json`:

```json
{
  "created_at": "2026-10-04T10:00:00+00:00",
  "operator": "ops-user",
  "database_backup": {
    "path": "D:/backups/timex_db_pre_storage.dump",
    "size_bytes": 123456789,
    "sha256": "..."
  },
  "legacy_backup": {
    "path": "D:/backups/timex_legacy_uploads.zip",
    "size_bytes": 4567890,
    "sha256": "..."
  }
}
```

The migration tool **does not create** these backups. It only verifies the registered
manifest paths exist, are non-empty, and match SHA-256 when provided.

---

## مرحله 2 — Manifest verification + Preflight + Dry-run

```text
python -m web.services.storage_production_preflight --dry-run \
  --json-out backups/storage_dry_run.json

python -m web.services.storage_production_migration --preflight \
  --backup-manifest backups/storage_migration_backup.json \
  --json-out backups/storage_gates.json
```

Confirm the gate report shows:

- Database target / Storage root / Environment / Target id
- Candidate count and total ready bytes
- `free_bytes >= ready_bytes` (headroom is reported; not hard-coded)
- Backup manifest OK
- Overall `ALLOWED` only when blockers are empty

---

## مرحله 3 — Go / No-Go

Execute is allowed only when all gates pass:

| Gate | Requirement |
|------|-------------|
| DB backup | Manifest path exists, non-empty, checksum OK if provided |
| Legacy backup | Manifest path exists, non-empty, checksum OK if provided |
| Storage root | Exists, directory, accessible, writable, **outside source tree** |
| Conflicts | 0 |
| Invalid refs | 0 |
| Missing | 0 (unless explicit `--allow-missing N`) |
| Disk space | `free_space >= total_ready_source_bytes` |
| Dry-run | Successful with `db_changed == false` and `filesystem_changed == false` |
| Confirmation | `--confirm-production` present |
| Window | Maintenance window / upload freeze active |

If overall is `BLOCKED`, **do not** execute.

---

## مرحله 4 — Execute (controlled)

> Run only after Go/No-Go and during the maintenance window.

```text
python -m web.services.storage_production_migration --execute \
  --backup-manifest backups/storage_migration_backup.json \
  --confirm-production \
  --journal-dir backups
```

Flow enforced by the tool:

```text
preflight
→ backup verification
→ dry-run
→ explicit confirmation
→ StorageActivationService.execute(dry_run=False)
```

Activation order (unchanged):

```text
preflight all → copy → SHA-256 verify → DB transaction
```

Sources are retained. An audit journal is written, e.g.:

```text
backups/storage_migration_YYYYMMDD_HHMMSS.json
```

Journals are written even when gates block execute or activation aborts.

---

## مرحله 5 — Verification

After a successful execute:

1. Compare DB reference counts (contracts / education / avatars) before vs after.
2. Spot-check SHA-256 for a sample of migrated files (source vs destination).
3. Test secure Contract download.
4. Test secure Education certificate download.
5. Test Avatar serving via the secure profile route.
6. Confirm `/static/uploads/contracts|certificates|avatars/...` returns 404
   (except public placeholder `uploads/avatars/image.png`).
7. **Keep legacy sources** until final sign-off. Deletion is a separate decision.

---

## مرحله 6 — Rollback

- Migration tooling **does not delete** legacy sources.
- PostgreSQL backup is the primary DB rollback reference.
- Destinations under `TIMEX_STORAGE_ROOT` are not auto-deleted.
- If migration is partial, inspect which rows still point at legacy vs unified keys.
- Filesystem rollback and DB rollback are independent and must be deliberate.

Suggested abort order:

1. Stop further uploads if needed.
2. Restore DB from the pre-migration backup (or surgically revert path columns).
3. Verify secure downloads via legacy keys.
4. Leave destinations until cleanup is explicitly approved.

---

## Resume / Retry

The activation path is idempotent:

- Already-unified / identical destinations → `ALREADY_MIGRATED` (no overwrite)
- After DB rollback with identical destination → DB update retry without recopy
- Destination conflict → abort
- Destination missing → copy again

---

## Related code

- `web/services/file_storage.py` — unified storage layout / path safety
- `web/services/storage_migration.py` — filesystem copy helpers (no DB)
- `web/services/storage_activation.py` — DB-backed activation
- `web/services/storage_production_preflight.py` — read-only / dry-run readiness CLI
- `web/services/storage_production_migration.py` — gated production execute CLI
