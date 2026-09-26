"""اپلیکیشن اصلی FastAPI"""
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from web.routes import auth, dashboard, attendance, leave, admin, contract, profile, holidays, admin_contracts, admin_leave, admin_daily_status, carry_forward, education, phones, addresses, reports, admin_policy, bank_accounts
from web.routes import admin_cities, admin_service_locations, admin_travel_leave_policy, travel_leave_preview, admin_travel_leave_preview
BASE_PATH = Path(__file__).parent
from web.config import WebConfig
from web.routes.admin_permissions import router as permissions_router
from web.routes.admin_user_create import router as admin_user_create_router
from web.error_handlers import register_exception_handlers

app = FastAPI(title="Timex - سامانه حضور و غیاب", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=WebConfig.SESSION_MIDDLEWARE_SECRET_KEY,
    session_cookie="timex_app_session",
    max_age=WebConfig.SESSION_MAX_AGE,
    same_site="lax",
    https_only=os.getenv("WEB_COOKIE_SECURE", "0") == "1",
)
register_exception_handlers(app)
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(attendance.router)
app.include_router(travel_leave_preview.router)

# The Travel Leave preview endpoint in admin_travel_leave_preview.py is the
# single source of truth for admin preview calculations. admin_leave.py still
# contains a legacy endpoint at the same effective URL; remove that cloned
# route after inclusion so FastAPI cannot dispatch the old contract-dependent
# implementation by mistake.
app.include_router(admin_travel_leave_preview.router)
app.include_router(leave.router)
app.include_router(admin.router)
app.include_router(contract.router)
app.include_router(profile.router)
app.include_router(holidays.router, prefix="/admin")
app.include_router(admin_contracts.router, prefix="/admin")
app.include_router(admin_leave.router, prefix="/admin")
app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/admin/leave-requests/travel-preview"
        and getattr(getattr(route, "endpoint", None), "__module__", "") == "web.routes.admin_leave"
        and getattr(getattr(route, "endpoint", None), "__name__", "") == "admin_travel_leave_preview"
    )
]
app.include_router(admin_daily_status.router, prefix="/admin")
app.include_router(admin_cities.router, prefix="/admin")
app.include_router(admin_service_locations.router, prefix="/admin")
app.include_router(carry_forward.router)
app.include_router(education.router)
app.include_router(phones.router)
app.include_router(addresses.router)
app.include_router(bank_accounts.router)
app.include_router(reports.router)
app.include_router(admin_policy.router)
app.include_router(admin_travel_leave_policy.router)
app.include_router(permissions_router)
app.include_router(admin_user_create_router)

@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
