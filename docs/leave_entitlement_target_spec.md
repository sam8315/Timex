# Annual Leave Entitlement — Target Business Specification

**Status:** Phases 1–5 delivered for Current Behavior central path. Target Rule
mismatches (register §5) remain **not activated** until an explicit approved phase.

**Baseline reference (Phase 1 engine):** `164d130cab635741f5f8b9c80164501b312b731b`

**Membership-aware characterization baseline:** `f3d490a881e098b0c6eccf7935243f2bd0964115`

**Branch context:** `work`

**Distinction:**

- **Current Behavior** → locked by characterization tests (`tests/characterization/test_current_*`)
- **Phase 2 Resolver** → builds `AnnualLeaveContext` from DB; wired via cutover engine/shadow
- **Phase 5 default path** → `TIMEX_AL_ENTITLEMENT_PATH` unset ⇒ `engine` (fail-closed parity)
- **Target Rule** → documented here; skipped in `tests/spec/` until a later approved phase

This document is the Layer 2 specification for the Central Annual Leave Entitlement Engine. Target Rules must not change Current Behavior until an explicit cutover phase.

---

## 1. Architecture Target

```
Resolver (DB / Membership / Contract / Region / Policy / Service Context)
  → AnnualLeaveContext
Pure Engine (no DB, no session, no date.today(), deterministic)
  → EntitlementResult
Mutation Layer → LeaveBalance / LeaveTransaction
Settlement Layer → Year End Storage / Buyback / Membership Change Settlement
```

Phase 1 delivers only: Target Spec, characterization of Current Behavior, and an **independent** Pure Engine under `web/services/leave_entitlement_engine/` with raw parity to `charge_amount_for_segment`. No production wiring.

---

## 2. General Principles (Target Rules)

1. Policies are **date-effective**. Mid-year Policy change splits the year into intervals; each interval uses the Policy valid for that date.
2. Mid-year Region change splits intervals; each interval uses the Region Policy of that period.
3. Mid-year Membership change does **not** sum entitlements. Each Membership owns its period. Prior Membership remainder is handled by an independent **Membership Change Settlement Policy**.
4. Base formula:

   `entitlement = annual_amount × effective_covered_days / year_days`

5. Year days follow Timex Jalali calendar (leap / non-leap). Days are inclusive. No rounding inside the raw formula. Final rounding must eventually preserve agreed production parity rules after cutover.
6. Carry Forward and Buyback stay outside the Entitlement Engine (Settlement).

---

## 3. Membership Target Rules

### 3.1 Official (رسمی) — code `1`

- Base currently intended: 30 days (Policy-driven, changeable)
- Midyear start: Prorata
- Midyear end: Prorata
- Region applicable; default `apply_region`: enabled
- No multiple contracts in one year for official
- Service deduction / extra / positive seniority: no effect on entitlement
- Historical leave usage required **by year**
- Unused year-end remainder stored; no storage ceiling currently
- Buyback separate Policy (eras):
  - through 1389: full unused each year
  - 1390–1398: max 15 days/year
  - 1399+: Buyback Policy + Region

### 3.2 Conscript (وظیفه) — code `2`

- Base: 30 days (Policy-driven)
- Region applicable; default `apply_region`: enabled
- Midyear start/end: Prorata
- Service deduction reduces effective service duration → reduces entitlement
- Service extra: no effect
- Long-term historical usage store not required
- No prior-year storage
- Entitlement from a single engine source
- Service info inputs (future Resolver, not Phase 1 schema):
  - dispatch date, unit entry date, department/clinic entry date
  - service type, bomi/non-bomi, service deduction, service unit
- Default entitlement start basis: **unit entry date** (Service Start-Date Policy)
- Legal service duration via **Service Duration Policy** (type + bomi/non-bomi + location/region)
- Concepts kept separate: `legal_service_duration`, `service_deduction`, `effective_service_duration`
- Public bomi/non-bomi thresholds must not be hard-coded as Timex law without owner confirmation

### 3.3 Purchased service (خریدخدمت) — code `3`

- Base: 30 days (Policy-driven)
- Region applicable; default `apply_region`: enabled
- Midyear start/end: Prorata
- Deduction / extra / seniority: N/A
- Historical usage by year required
- Full year-end remainder stored; no ceiling
- Full stored remainder buyable at end of collaboration

### 3.4 Contractual (قراردادی) — code `4`

- Base: 26 days (Policy-driven, changeable)
- Region applicable; default `apply_region`: **disabled**
- Midyear start/end: Prorata
- Multiple contracts in a year allowed
- Entitlement from real year coverage; overlapping coverage must not double-count (**union / unique covered days**)
- Prior-year usage history not required at contract create
- Year-end storage exists; current ceiling 9 days (Policy-driven)
- Above ceiling: **burned** (not stored)
- Buyback via independent Policy
- Deduction / extra / seniority: no effect

### 3.5 Other memberships without specific law

- Default entitlement = 0
- Default region effect = 0
- Storage = 0
- Buyback = 0
- Must be Policy-driven, not hard-coded inside Engine

---

## 4. Policy Interfaces (design only in Phase 1)

Documented as Protocol stubs in `web/services/leave_entitlement_engine/policies.py`:

| Interface | Purpose |
|---|---|
| `AnnualBasePolicy` | Membership annual base |
| `RegionApplyPolicy` | Whether region replaces/applies |
| `RegionAnnualPolicy` | Region annual amount |
| `CoveragePolicy` | Membership coverage / midyear rules |
| `ServiceDurationPolicy` | Conscript legal/extra/effective duration |
| `ServiceStartDatePolicy` | Conscript entitlement start basis |
| `YearEndStoragePolicy` | Storage ceiling / burn |
| `BuybackPolicy` | Era + region buyback caps |
| `MembershipChangeSettlementPolicy` | Prior membership remainder |
| `OtherMembershipDefaultPolicy` | Zero defaults for unspecified memberships |

**Phase 1 explicitly does not create** DB models/fields/tables/migrations for Service Duration, Start-Date Policy, Bomi/Non-Bomi, Unit History, or Membership Change Settlement.

---

## 5. Mismatch Register

Format: `Current Behavior → Target Rule → Future Change`

1. Contractual base 30 (`CONTRACT_TYPES` / `DEPT_DEFAULT_ANNUAL`) → Contractual base 26 Policy-driven → Future: Policy defaults only; no rewrite of existing Contracts  
2. `region_applies` missing ⇒ True for all → Default `apply_region` for contractual = false → Future: per-membership defaults in Resolver/Policy  
3. Overlap rejected by `find_overlapping_contract` → Union/unique covered days → Future: CoveragePolicy + multi-interval Engine + possible admin rule change  
4. Single annual snapshot per charge year → Date-effective Policy slices mid-year → Future: Resolver PolicySlice timeline  
5. Region resolved once (ESL/today or `employee.region_code`) → Region change mid-year segments → Future: as-of region history slicing  
6. Membership change charges each contract; no settlement → Membership Change Settlement Policy → Future: Settlement Layer  
7. Permanent midyear end ignored (segment to year end) → Official midyear end Prorata → Future: CoveragePolicy change after parity era  
8. Conscript only `service_deduction_days` on end → ServiceDurationPolicy + StartDatePolicy + effective duration → Future: service inputs + Engine Context (no Phase 1 models)  
9. No bomi / service-type / unit entitlement inputs → Reference-driven service context → Future: Resolver inputs; no hard-coded public thresholds  
10. Service extra / positive seniority absent → Official: no effect; Conscript: deduction affects, extra does not → Future: explicit Context fields when models exist  
11. Physician math = contractual; static annual 0 in `CONTRACT_TYPES` / Membership seed → Keep policy-driven via `MembershipTypeRule` (SoT); PolicyValue `annual_leave_dept_5` is compatibility mirror only (aligned by `align_annual_leave_policy_mirrors`); no invented legal 30 → Future: only if Spec later differentiates physician law
12. Types 6/7 map to dept 4 editable → Other membership defaults 0 via policy → Future: OtherMembershipDefaultPolicy  
13. Dual buyback paths (`resolve_max_buyback` vs CF `calculate_leave_ceiling`) → Single Buyback Policy outside Engine → Future: Settlement consolidation  
14. Some CF flows use Gregorian 365 → Uniform Jalali calendar in Settlement → Future: outside Engine  
15. Path G Gregorian/365 and Path H full multi-year diverge from Path B → Deprecate after production cutover → Future: Phase 2+; Phase 1 keep  
16. History live policy vs charge snapshot → Single Context source per year → Future: Resolver unification; no historical rebuild in Phase 1  

---

## 6. Repository mapping note

Updated for Membership Foundation baseline (`f3d490a` / Phase 2):

| Concept | Actual current location |
|---|---|
| Membership CRUD / effective rules | `web/services/membership_service.py` |
| Behavior profiles (coverage/charge) | `web/services/membership_semantics.py` + `MembershipType.behavior_profile` |
| Service deduction on contract | `Contract.service_deduction_days` (+ `models/service_adjustment.py` exists but is not the entitlement coverage source) |
| Membership identity / rules | `models/membership_type.py`, `models/membership_type_rule.py` |
| Phase 2 DB → Context Resolver | `web/services/leave_entitlement_resolver.py` (read-only; cutover engine/shadow) |
| Cutover / Shadow / Engine path | `web/services/leave_entitlement_cutover.py` + `TIMEX_AL_ENTITLEMENT_PATH` |
| Ops read-only shadow diagnostic | `tools/shadow_parity_diagnostic.py` |

---

## 7. Phase boundaries

### Phase 1 (delivered)

- Characterize Current Behavior
- Document Target Rules (this file)
- Independent Pure Engine package with raw parity to `charge_amount_for_segment`
- No production wiring / refactor / migration / data rewrite

### Phase 2 (Resolver — delivered)

- Read-only Resolver: DB facts → `AnnualLeaveContext` → Pure Engine
- Current Behavior compatible coverage / annual / region precedence
- Deterministic `year_j` + required `as_of_date` (does not copy `date.today()` year coupling)
- Tests under `tests/resolver/`

### Phase 3 (first production cutover — contract charge calc only)

- Controlled wire of `leave_service.calculate_prorated_leave_by_year` via
  `web/services/leave_entitlement_cutover.py`
- Env switch `TIMEX_AL_ENTITLEMENT_PATH`: `legacy` (default) | `shadow` | `engine`
- Engine path uses **snapshot** annual (`annual_override` / `Contract.annual_leave_days`)
- Mutation layer (`round` + LeaveBalance + LeaveTransaction) unchanged
- Fail-closed parity in `engine` mode; `shadow` mutates via legacy and logs diffs
- Rollback: set `TIMEX_AL_ENTITLEMENT_PATH=legacy` (no data rewrite)
- **Not in Phase 3:** Permanent History, Target Rule defaults (26 / apply_region false),
  mid-year Policy/Region slices, union coverage, Service Duration / Start-Date / Bomi,
  Membership Change Settlement, admin live-snapshot resolve changes, legacy deletion

### Phase 4 (Shadow Validation / Parity Evidence — delivered)

**Phase 4 default = legacy**

**Phase 4 does not promote to engine automatically**

Scope remains the Phase 3 consumer only:
`leave_service.calculate_prorated_leave_by_year` via
`web/services/leave_entitlement_cutover.py`.

#### Shadow semantics

```text
Legacy calculation
      +
Resolver → Context → Pure Engine
      ↓
Compare / Classify / Metrics / Log
      ↓
return Legacy
      ↓
existing mutation
```

Engine under shadow never writes LeaveBalance / LeaveTransaction / Contract /
region sync / snapshot — even on mismatch.

#### ShadowOutcome taxonomy (deterministic precedence)

First match wins:

| Code | Name | Meaning |
|------|------|---------|
| G | resolver failure | Context cannot be built |
| H | engine failure | Pure Engine exception |
| C | coverage mismatch | year keys / empty-vs-nonempty / covered-days shape |
| D | annual source mismatch | snapshot/override invariant broken |
| F | membership mismatch | membership identity ≠ contract identity |
| E | region mismatch | unexpected on snapshot path (meta flag) |
| A | raw mismatch | raw amounts disagree beyond tolerance |
| B | rounded mismatch | raw close, `round()` differs |
| OK | match | parity holds |

No mismatch class is suppressed.

#### In-process metrics (local evidence only)

API: `get_shadow_metrics()` / `reset_shadow_metrics()`

Counters:

- `shadow_total` — every shadow execution
- `shadow_match` — classification `OK` only
- `shadow_mismatch` — A–F only
- `resolver_failure` — G
- `engine_failure` — H
- `raw_mismatch` / `rounded_mismatch` / `coverage_mismatch` — A / B / C detail

**Multi-worker note:** these counters are in-process only. They are **not** a
global production metric across workers/processes. Do not add DB/Redis/Prometheus
for Phase 4. Production evidence aggregation uses structured logs.

#### Structured logging

Prefix: `al_entitlement_shadow`

Minimum fields: `user_id`, `contract_id`, `year_j`, `membership_code`,
`legacy_raw`, `engine_raw`, `legacy_rounded`, `engine_rounded`, `diff`,
`mismatch_type`, `resolver_engine_status`, `mutation=legacy`,
`annual_source=snapshot`.

Logging / metrics / classifier failures must not change the business result
(`logging failure != business failure`).

#### Failure isolation

| Failure | Behavior |
|---------|----------|
| Resolver (G) | log + `resolver_failure` += 1 + return legacy |
| Engine (H) | log + `engine_failure` += 1 + return legacy |
| Logging | ignored; legacy returned unchanged |
| Classifier | log + bump `shadow_total` if needed; return legacy |

#### Operational procedure (human; agent has no Production access)

```text
TIMEX_AL_ENTITLEMENT_PATH=shadow
restart service
verify log (prefix al_entitlement_shadow)
collect evidence (aggregate logs; optional per-process get_shadow_metrics)
evaluate mismatch taxonomy
rollback:
TIMEX_AL_ENTITLEMENT_PATH=legacy
restart service
```

Phase 4 does **not** change Production ENV from this codebase/agent session.
Auto-promotion is forbidden.

Acceptance criterion (manual gate, not runtime auto-promote):
`TIMEX_AL_SHADOW_PROMOTION_MIN_MATCH_RATE` is a documentation / ops threshold only
in Phase 4 (not wired as auto-promotion).

#### Evidence report format (manual)

```text
Shadow Window:
Consumer:
Environment:
shadow_total:
shadow_match:
shadow_mismatch:
match_rate:

A:
B:
C:
D:
E:
F:
G:
H:

Unexpected Critical:
Unexpected High:
Unresolved:
Recommendation:
```

This is a report template only — not an auto-promotion mechanism.

#### Rollback

Set `TIMEX_AL_ENTITLEMENT_PATH=legacy` and restart. No migration, no data rewrite,
no Contract snapshot rewrite.

#### Target Rules still inactive in Phase 4

Same as Phase 3: contractual base 26, contractual region default false, union
overlap, mid-year Policy/Region slicing, Service Duration, Start-Date Policy,
Bomi/Non-Bomi, Membership Settlement, new storage, new buyback — **not activated**.

### Phase 5 (engine promotion + central formula — delivered)

**Phase 5 default = engine** (when `TIMEX_AL_ENTITLEMENT_PATH` is unset)

**Rollback:** `TIMEX_AL_ENTITLEMENT_PATH=legacy` or `shadow` + restart service

(No migration / data rewrite / Contract snapshot rewrite.)

Delivered:

- Code default path promoted to `engine` with fail-closed parity vs legacy
- Pure Engine branching by `AnnualLeaveContext.charge_mode` (not membership hard-codes)
- Resolver sets `charge_mode` from `membership_semantics.charge_mode`
- `charge_amount_for_segment` delegates raw math to Pure Engine (single formula source)
- Permanent History continues live-annual Current Behavior; raw math via Engine delegate
- Contract charge / edit / remove already go through `calculate_prorated_leave_by_year` → cutover
- Ops diagnostic (read-only): `tools/shadow_parity_diagnostic.py`
- Shadow remains available for observation; not required for default path

Promotion evidence (Development diagnostic, Production skipped by ops decision):

```text
Membership 1: 2/2 OK
Membership 2: 0 contracts
Membership 3: 2/2 OK
Membership 4: 36/36 OK
Total: 40/40 OK; A–H = 0
```

### Phase 6 (architecture + settlement facades + AL UI — delivered)

Delivered without inventing legal thresholds:

- Multi-slice Pure Engine: `compute_annual_entitlement_for_slices`
- Resolver Rule timeline + `resolve_sliced_contexts_for_contract` (Target-ready;
  **does not** replace Current Behavior snapshot charge path)
- Settlement package `web/services/leave_settlement/` (year-end storage, buyback,
  membership-change mode; default `keep_separate` = Current Behavior)
- Conscript service context builder (facts from Contract/ServiceAdjustment;
  legal duration remains owner-dependent / unresolved until Policy exists)
- Admin UI: `/admin/annual-leave/policies`
- User leave page shows buyback quota + storage cap labels from central facades
- Ops diagnostic retained: `tools/shadow_parity_diagnostic.py` (not a runtime dependency)

#### Owner-dependent rules (explicitly unresolved — do not invent)

- Contractual base 26 / contractual `apply_region` default false (Policy data change)
- Union / unique covered days for overlaps (admin rule + CoveragePolicy)
- Permanent mid-year end prorata Target change
- ServiceDurationPolicy / StartDatePolicy numeric thresholds
- Bomi/Non-Bomi / unit master duration tables
- Membership Change modes other than `keep_separate` (transfer/expire/cash_out)
- Settlement consolidation of Gregorian CF paths

#### Deployment / rollback

```text
Default path: engine (unset TIMEX_AL_ENTITLEMENT_PATH)
Rollback: TIMEX_AL_ENTITLEMENT_PATH=legacy|shadow + restart
No migration required for Phase 6 architecture/UI
Production ENV not changed by this repository push
```

### Phase 7+

- Activate Target Rule defaults only after owner-approved Policy data changes
- Persist Conscript unit/service-type/bomi fields when models are approved
- Execute Membership Change settlement ledger when owner sets Policy mode
- Union coverage + mid-year Region history tables
- Legacy path deprecation after sustained engine stability
