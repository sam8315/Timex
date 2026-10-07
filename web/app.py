"""اپلیکیشن اصلی FastAPI"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import PlainTextResponse

from web.routes import auth, dashboard, attendance, leave, admin, contract, profile, holidays, admin_contracts, admin_leave, admin_daily_status, carry_forward, education, phones, addresses, reports, admin_policy, bank_accounts, employee_documents, employee_relatives, admin_verifications
from web.routes import admin_cities, admin_service_locations, admin_travel_leave_policy, travel_leave_preview, admin_travel_leave_preview
from web.routes import admin_positions
from web.routes import admin_employee_document_types
from web.routes import admin_membership_types
from web.routes import admin_service_adjustments
from web.routes import admin_service_duty_regions
from web.routes import admin_system
from web.routes import admin_annual_leave
BASE_PATH = Path(__file__).parent
from web.config import WebConfig
from web.jobs.relative_study_expiry import start_scheduler, stop_scheduler
from web.routes.admin_permissions import router as permissions_router
from web.routes.admin_user_create import router as admin_user_create_router
from web.error_handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


class GuardedStaticFiles(StaticFiles):
    """Serve /static but block direct HTTP access to legacy private upload trees.

    Exception: the public avatar placeholder ``uploads/avatars/image.png``.
    """

    _BLOCKED_PREFIXES = (
        "uploads/contracts/",
        "uploads/certificates/",
        "uploads/avatars/",
    )
    _ALLOWED_PLACEHOLDERS = frozenset({"uploads/avatars/image.png"})

    async def get_response(self, path: str, scope):
        normalized = (path or "").replace("\\", "/").lstrip("/")
        normalized_lower = normalized.lower()
        # Placeholder exception: path matches case-insensitively, but filename
        # must be exactly image.png (not Image.PNG / IMAGE.PNG).
        if (
            normalized_lower in self._ALLOWED_PLACEHOLDERS
            and normalized.rsplit("/", 1)[-1] == "image.png"
        ):
            return await super().get_response(path, scope)
        for prefix in self._BLOCKED_PREFIXES:
            if normalized_lower.startswith(prefix):
                return PlainTextResponse("Not Found", status_code=404)
        return await super().get_response(path, scope)


app = FastAPI(
    title="Timex - سامانه حضور و غیاب",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=WebConfig.SESSION_MIDDLEWARE_SECRET_KEY,
    session_cookie="timex_app_session",
    max_age=WebConfig.SESSION_MAX_AGE,
    same_site="lax",
    https_only=os.getenv("WEB_COOKIE_SECURE", "0") == "1",
)
register_exception_handlers(app)
app.mount("/static", GuardedStaticFiles(directory=str(BASE_PATH / "static")), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(attendance.router)
app.include_router(travel_leave_preview.router)

# Authoritative admin Travel Leave preview (policy-aware).
app.include_router(admin_travel_leave_preview.router)
app.include_router(leave.router)
app.include_router(admin.router)
app.include_router(contract.router)
app.include_router(profile.router)
app.include_router(holidays.router, prefix="/admin")
app.include_router(admin_contracts.router, prefix="/admin")
app.include_router(admin_leave.router, prefix="/admin")
app.include_router(admin_daily_status.router, prefix="/admin")
app.include_router(admin_cities.router, prefix="/admin")
app.include_router(admin_positions.router, prefix="/admin")
app.include_router(admin_employee_document_types.router, prefix="/admin")
app.include_router(admin_membership_types.router, prefix="/admin")
app.include_router(admin_service_adjustments.router, prefix="/admin")
app.include_router(admin_system.router, prefix="/admin")
app.include_router(admin_annual_leave.router)
app.include_router(admin_service_locations.router, prefix="/admin")
app.include_router(carry_forward.router)
app.include_router(education.router)
app.include_router(phones.router)
app.include_router(addresses.router)
app.include_router(bank_accounts.router)
app.include_router(employee_documents.router)
app.include_router(employee_relatives.router)
app.include_router(admin_verifications.router)
app.include_router(reports.router)
app.include_router(admin_policy.router)
app.include_router(admin_service_duty_regions.router)
app.include_router(admin_travel_leave_policy.router)
app.include_router(permissions_router)
app.include_router(admin_user_create_router)

@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)
