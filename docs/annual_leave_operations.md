# Annual Leave — Operations & Rollback

## Cutover path

Sole runtime switch: environment variable `TIMEX_AL_ENTITLEMENT_PATH`

| Value | Behavior |
|-------|----------|
| *(unset)* / `engine` | Resolver → Pure Engine; fail-closed parity vs legacy before mutation |
| `shadow` | Dual-run; always mutate via legacy; classify/log |
| `legacy` | Current Behavior formula path only |

Invalid values fall back to `legacy`.

**Promotion safety gate:** if env is `engine` but any
`MembershipTypeRule.annual_leave_base` vs PolicyValue `annual_leave_dept_*`
mirror conflict remains, runtime **downgrades to `shadow`**
(`get_effective_entitlement_path`). Align mirrors first (startup
`align_annual_leave_policy_mirrors` or migration `013_*`).

## Annual policy source of truth

| Concern | Authority |
|---------|-----------|
| Live annual base | `MembershipTypeRule.annual_leave_base` (+ region flags/overrides) |
| Compatibility mirror | PolicyValue `annual_leave_dept_{code}` (synced from Rule; not SoT when Rules exist) |
| Charge / mutation amount | `Contract.annual_leave_days` snapshot (Current Behavior; not rewritten by mirror sync) |

### Physician (code `5`)

- Seed / Foundation Rule base = **0** (Target Spec mismatch #11: policy-driven; no invented legal 30).
- Historical Production `annual_leave_dept_5=30` was an orphaned legacy mirror — sync Rule→mirror clears dual-run false conflicts.
- Existing contract snapshots may remain **30**; charge path continues to use the snapshot until contract edit/re-resolve.
- To grant physicians a non-zero **live** base going forward, set it on Membership Rules in Admin (not by editing PolicyValue mirrors).

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

Optional: `--codes 1,2,3,4,5` / `--limit-per-code N`

Never commits. Always `rollback()` + `close()`.

## Admin UI

- `/admin/annual-leave/policies` — membership AL policy overview
- `/admin/annual-leave/employee?target_user_id=...` — per-user dashboard

Requires admin + `view_leave_balances` / `view_contracts` as enforced in routes.
