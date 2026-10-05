"""
Independent Pure Annual Leave Entitlement Engine.

DB-free, side-effect-free. Production charge math delegates here via
leave_entitlement_service.charge_amount_for_segment and the cutover engine path.
"""
from web.services.leave_entitlement_engine.calendar import (
    get_jalali_year_days,
    jalali_year_bounds_g,
)
from web.services.leave_entitlement_engine.context import (
    CHARGE_MODE_PERMANENT,
    CHARGE_MODE_PHYSICIAN,
    CHARGE_MODE_PRORATE,
    AnnualLeaveContext,
    CoverageInterval,
    EntitlementResult,
)
from web.services.leave_entitlement_engine.engine import (
    build_context_for_segment,
    compute_annual_entitlement,
    compute_annual_entitlement_for_slices,
)

__all__ = [
    'AnnualLeaveContext',
    'CoverageInterval',
    'EntitlementResult',
    'CHARGE_MODE_PERMANENT',
    'CHARGE_MODE_PHYSICIAN',
    'CHARGE_MODE_PRORATE',
    'build_context_for_segment',
    'compute_annual_entitlement',
    'compute_annual_entitlement_for_slices',
    'get_jalali_year_days',
    'jalali_year_bounds_g',
]
