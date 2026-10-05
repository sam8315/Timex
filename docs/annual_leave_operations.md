# Annual Leave — Operations & Rollback

## Cutover path

Sole runtime switch: environment variable `TIMEX_AL_ENTITLEMENT_PATH`

| Value | Behavior |
|-------|----------|
| *(unset)* / `engine` | Resolver → Pure Engine; fail-closed parity vs legacy before mutation |
| `shadow` | Dual-run; always mutate via legacy; classify/log |
| `legacy` | Current Behavior formula path only |

Invalid values fall back to `legacy`.

## Rollback

```text
TIMEX_AL_ENTITLEMENT_PATH=legacy
restart Timex web service
```

No DB migration, no Contract snapshot rewrite, no LeaveBalance rebuild.

## Read-only diagnostic

```powershell
cd D:\Projects\Timex
.\.venv\Scripts\python.exe .\tools\shadow_parity_diagnostic.py
```

Optional: `--codes 1,2,3,4` / `--limit-per-code N`

Never commits. Always `rollback()` + `close()`.

## Admin UI

- `/admin/annual-leave/policies` — membership AL policy overview
- `/admin/annual-leave/employee?target_user_id=...` — per-user dashboard

Requires admin + `view_leave_balances` / `view_contracts` as enforced in routes.
