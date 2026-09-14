# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Timex

- **Type**: Python web/app with device manager (`core/`), database (`database/`), web server (`run_web.py` / uvicorn), admin (`run_adms.py` / `core/adms_server.py`), tests (`tests/`), and config (`config/`)
- **Tests**: `pytest` (see `pytest.ini`: `testpaths = tests`). Run single: `python -m pytest tests/<file> -v`; all: `python -m pytest -v`
- **Web server**: `python run_web.py` (uvicorn + SQLAlchemy + dotenv)
- **Admin server**: `python run_adms.py` (ADMS sync + device manager)
- **Main CLI**: `python main.py` (console UI + device manager)
- **DB init**: `database/init_db.py` / `recreate_db.py`
- **Architecture**: `core/` = business logic (attendance, leave, employee managers); `models/` = SQLAlchemy models; `web/` = templates/routes; `config/` = settings; attendance policy engine centralizes calculation (`attendance_policy_service.py` per docs/phase5)
- **Policy engine**: `resolve_policy()` → `resolve_required_minutes()` → `compute_late()` / `compute_early_leave()` / `calculate_daily_attendance()` (database-driven, replaces hardcoded 7:20 / 7.33 / DAILY_DUTY_HOURS)
- **Key docs**: `docs/phase5_final_report.md` (attendance policy design); audit reports (`audit-attendance-policy-*.html`)
- **No Cursor rules / Copilot instructions / Codex / Gemini configs found.** No `CLAUDE.md` existed; created now.
