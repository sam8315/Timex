"""
Independent Pure Annual Leave Entitlement Engine (Phase 1).

Not wired into production paths. Parity target:
  compute_annual_entitlement(...).raw_amount
  == leave_entitlement_service.charge_amount_for_segment(...)
"""
from web.services.leave_entitlement_engine.calendar import (
    get_jalali_year_days,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_engine.context import (
    AnnualLeaveContext,
    CoverageInterval,
    EntitlementResult,
)
from web.services.leave_entitlement_engine.engine import compute_annual_entitlement

__all__ = [
    'AnnualLeaveContext',
    'CoverageInterval',
    'EntitlementResult',
    'compute_annual_entitlement',
    'get_jalali_year_days',
    'jalali_year_bounds_g',
]
