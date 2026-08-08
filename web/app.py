"""اپلیکیشن اصلی FastAPI"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path

from web.routes import auth, dashboard, attendance, leave, admin, contract
BASE_PATH = Path(__file__).parent

app = FastAPI(title="Timex - سامانه حضور و غیاب", version="1.0.0")

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")

# Routes
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(attendance.router)
app.include_router(leave.router)
app.include_router(admin.router)
app.include_router(contract.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8082)