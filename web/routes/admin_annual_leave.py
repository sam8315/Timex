"""Admin Annual Leave overview — policies + per-user dashboard (read-mostly)."""
from __future__ import annotations

import jdatetime
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models.user import User
from web.dependencies import get_db, require_admin
from web.permissions import enforce_permission, has_permission
from web.services.annual_leave_dashboard_service import (
    build_user_annual_leave_dashboard,
    list_membership_al_policies,
)
from web.services.leave_settlement import resolve_membership_change_mode

router = APIRouter(tags=['Admin Annual Leave'])
templates = Jinja2Templates(directory='web/templates')


@router.get('/admin/annual-leave/policies', response_class=HTMLResponse)
async def annual_leave_policies_page(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Policy overview for AL — data from Membership Rules + settlement facades."""
    if not (
        has_permission(db, user, 'view_contracts')
        or has_permission(db, user, 'view_leave_balances')
    ):
        return RedirectResponse(url='/admin?error=no_permission', status_code=302)

    policies = list_membership_al_policies(db)
    from web.services.annual_leave_policy_authority import (
        audit_annual_policy_conflicts,
        is_engine_promotion_allowed,
    )
    from web.services.leave_entitlement_cutover import (
        get_effective_entitlement_path,
        get_entitlement_path,
    )

    conflicts = audit_annual_policy_conflicts(db)
    env_path = get_entitlement_path()
    effective_path = get_effective_entitlement_path(db)
    return templates.TemplateResponse(
        'admin/annual_leave_policies.html',
        {
            'request': request,
            'user': user,
            'policies': policies,
            'membership_change_mode': resolve_membership_change_mode(db).value,
            'path': env_path,
            'effective_path': effective_path,
            'engine_promotion_allowed': is_engine_promotion_allowed(db),
            'policy_conflicts': conflicts,
            'can_edit_membership': has_permission(db, user, 'edit_contracts'),
        },
    )


@router.get('/admin/annual-leave/employee', response_class=HTMLResponse)
async def annual_leave_employee_page(
    request: Request,
    target_user_id: str = Query(...),
    year: int | None = Query(None),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Per-employee Annual Leave dashboard (ledger + central estimate)."""
    enforce_permission(db, user, 'view_leave_balances')
    year_j = year if year is not None else jdatetime.date.today().year
    try:
        dash = build_user_annual_leave_dashboard(
            db, target_user_id, year_j=year_j
        )
    except Exception:
        return RedirectResponse(
            url=f'/admin/profile/{target_user_id}?error=leave_dashboard',
            status_code=302,
        )
    return templates.TemplateResponse(
        'admin/annual_leave_employee.html',
        {
            'request': request,
            'user': user,
            'dash': dash,
            'year_j': year_j,
            'target_user_id': target_user_id,
        },
    )


def get_entitlement_path_safe() -> str:
    try:
        from web.services.leave_entitlement_cutover import get_entitlement_path

        return get_entitlement_path()
    except Exception:
        return 'unknown'
