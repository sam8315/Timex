"""اپلیکیشن اصلی FastAPI"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime

from web.routes import auth, dashboard, attendance

# جلوگیری از ساخت خروج ضمنی برای ورود بازِ روز جاری.
# تاریخ جاری بر اساس timezone سرور محاسبه می‌شود.
_original_calculate_work_hours = attendance.calculate_work_hours


def _server_aware_calculate_work_hours(day_records, is_night_shift):
    if day_records and is_night_shift:
        server_today = datetime.now().date()
        has_current_day_open_entry = any(
            record.punch == 0 and record.timestamp.date() == server_today
            for record in day_records
        )
        if has_current_day_open_entry:
            return _original_calculate_work_hours(day_records, False)

    return _original_calculate_work_hours(day_records, is_night_shift)


attendance.calculate_work_hours = _server_aware_calculate_work_hours

from web.routes import leave, admin, contract, profile, holidays, admin_contracts, admin_leave, admin_daily_status, carry_forward, education, phones, reports, admin_policy, announcements, admin_announcements
BASE_PATH = Path(__file__).parent
from web.routes.admin_permissions import router as permissions_router
from web.routes.admin_user_create import router as admin_user_create_router
from web.error_handlers import register_exception_handlers

app = FastAPI(title="Timex - سامانه حضور و غیاب", version="1.0.0")

# 🆕 اضافه کردن SessionMiddleware برای ذخیره session
app.add_middleware(SessionMiddleware, secret_key="timex-web-secret-key-2024-change-in-production")

# 🆕 هندلر متمرکز خطاهای HTTP (403 → صفحه HTML برای مرورگر، JSON برای API)
register_exception_handlers(app)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")

# Routes
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(attendance.router)
app.include_router(leave.router)
app.include_router(admin.router)
app.include_router(contract.router)
app.include_router(profile.router)
app.include_router(holidays.router, prefix="/admin")
app.include_router(admin_contracts.router, prefix="/admin")
app.include_router(admin_leave.router, prefix="/admin")
app.include_router(admin_daily_status.router, prefix="/admin")
app.include_router(carry_forward.router)
app.include_router(education.router)
app.include_router(phones.router)
app.include_router(reports.router)
app.include_router(admin_policy.router)
app.include_router(announcements.router)
app.include_router(admin_announcements.router, prefix="/admin")
# 🆕 ماژول مدیریت دسترسی‌ها
app.include_router(permissions_router)
app.include_router(admin_user_create_router)

@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)