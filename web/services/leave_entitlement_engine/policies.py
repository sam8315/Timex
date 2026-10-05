"""
Policy Protocol stubs for future Resolver / Settlement layers.

Phase 1: design-only. No DB wiring. No new models/tables/fields.
See docs/leave_entitlement_target_spec.md for Target Rules.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class AnnualBasePolicy(Protocol):
    """Target: membership annual base (Policy-driven)."""

    def annual_base(self, membership_code: str, as_of: date) -> float: ...


@runtime_checkable
class RegionApplyPolicy(Protocol):
    """Target: whether region applies for a membership as-of date."""

    def region_applies(self, membership_code: str, as_of: date) -> bool: ...


@runtime_checkable
class RegionAnnualPolicy(Protocol):
    """Target: region annual amount when region applies."""

    def region_annual(self, region_code: str, as_of: date) -> Optional[float]: ...


@runtime_checkable
class CoveragePolicy(Protocol):
    """Target: membership coverage / midyear start-end rules."""

    def describe(self) -> str: ...


@runtime_checkable
class ServiceDurationPolicy(Protocol):
    """
    Target (Conscript): legal / extra / effective service duration.

    Phase 1: no model/field/table. Spec only.
    """

    def legal_service_duration_days(self, **service_context) -> int: ...


@runtime_checkable
class ServiceStartDatePolicy(Protocol):
    """
    Target (Conscript): entitlement start basis (default: unit entry date).

    Phase 1: no model/field/table. Spec only.
    """

    def entitlement_start(self, **service_context) -> date: ...


@runtime_checkable
class YearEndStoragePolicy(Protocol):
    """Target: year-end storage ceiling / burn. Settlement layer."""

    def storage_cap(self, membership_code: str, as_of: date) -> Optional[int]: ...


@runtime_checkable
class BuybackPolicy(Protocol):
    """Target: era + region buyback caps. Settlement layer; outside Engine."""

    def buyback_cap(
        self,
        membership_code: str,
        *,
        region_code: Optional[str],
        year_j: int,
    ) -> Optional[int]: ...


@runtime_checkable
class MembershipChangeSettlementPolicy(Protocol):
    """
    Target: settle prior membership remainder on membership change.

    Phase 1: no model/field/table. Spec only.
    """

    def describe(self) -> str: ...


@runtime_checkable
class OtherMembershipDefaultPolicy(Protocol):
    """Target: unspecified memberships → entitlement/region/storage/buyback = 0."""

    def default_annual(self, membership_code: str) -> float: ...
