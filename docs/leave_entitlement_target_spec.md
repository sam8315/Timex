# Annual Leave Entitlement — Target Business Specification

**Status:** Phase 1 Pure Engine + Phase 2 read-only Resolver documented; Target Rules not enforced by production

**Baseline reference (Phase 1 engine):** `164d130cab635741f5f8b9c80164501b312b731b`

**Membership-aware characterization baseline:** `f3d490a881e098b0c6eccf7935243f2bd0964115`

**Branch context:** `work`

**Distinction:**

- **Current Behavior** → locked by characterization tests (`tests/characterization/test_current_*`)
- **Phase 2 Resolver** → builds `AnnualLeaveContext` from DB with Current Behavior compatibility (`tests/resolver/`); not production-wired
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
11. Physician math = contractual; static annual 0 in `CONTRACT_TYPES` → Keep policy-driven; no Phase 1 invention → Future: only if Spec later differentiates  
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
| Phase 2 DB → Context Resolver | `web/services/leave_entitlement_resolver.py` (read-only; not production-wired) |

---

## 7. Phase boundaries

### Phase 1 (delivered)

- Characterize Current Behavior
- Document Target Rules (this file)
- Independent Pure Engine package with raw parity to `charge_amount_for_segment`
- No production wiring / refactor / migration / data rewrite

### Phase 2 (Resolver — no production cutover)

- Read-only Resolver: DB facts → `AnnualLeaveContext` → Pure Engine
- Current Behavior compatible coverage / annual / region precedence
- Deterministic `year_j` + required `as_of_date` (does not copy `date.today()` year coupling)
- Tests under `tests/resolver/`
- **Not in Phase 2:** production wiring into `admin_contracts` / `charge_leave_for_new_contract`, Mutation Layer cutover, Target Rule defaults, mid-year Policy/Region slices, union coverage, Service Duration / Start-Date / Bomi, Membership Change Settlement, Permanent History rebuild

### Phase 3+

- Resolver production wiring
- Mutation Layer cutover
- Settlement Layer
- Service Duration / Start-Date / Bomi / Unit history models (when designed)
- Membership Change Settlement
- Align defaults (contractual 26, contractual `apply_region` false)
- Mid-year Policy/Region slicing
- Union coverage
- Legacy path deprecation
