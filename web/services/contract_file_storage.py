"""ذخیره و سرو امن فایل قرارداد (خارج از static عمومی)."""
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import UploadFile

WEB_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_UPLOAD_DIR = WEB_ROOT / "private_uploads" / "contracts"

# برای سازگاری با تست‌ها
UPLOAD_DIR = PRIVATE_UPLOAD_DIR

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
PRIVATE_PATH_PREFIX = "/private/contracts/"


def resolve_contract_file_disk(stored_path: str) -> Path:
    """تبدیل مسیر ذخیره‌شده در DB به مسیر دیسک (legacy static یا private)."""
    normalized = (stored_path or "").replace("\\", "/").strip()
    if not normalized:
        raise ValueError("مسیر فایل خالی است")

    if normalized.startswith("/static/"):
        rel = normalized[len("/static/"):].lstrip("/")
        return WEB_ROOT / "static" / rel

    if normalized.startswith(PRIVATE_PATH_PREFIX):
        return PRIVATE_UPLOAD_DIR / Path(normalized).name

    # فقط نام فایل → پوشه private
    return PRIVATE_UPLOAD_DIR / Path(normalized).name


def delete_contract_file(stored_path: Optional[str]) -> None:
    if not stored_path:
        return
    try:
        path = resolve_contract_file_disk(stored_path)
        if path.is_file():
            path.unlink()
    except (OSError, ValueError):
        pass


async def save_contract_file(
    upload: UploadFile,
    *,
    user_id: str = "",
    contract_id: int = 0,
) -> str:
    """ذخیره فایل با نام UUID و برگرداندن مسیر منطقی غیرعمومی."""
    del user_id, contract_id  # فقط برای سازگاری امضای فراخوانی‌های قبلی
    if not upload.filename:
        raise ValueError("نام فایل نامعتبر است")
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("نوع فایل مجاز نیست (فقط PDF/JPG/PNG)")
    content = await upload.read()
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("حجم فایل بیش از ۱۰ مگابایت است")
    if not content:
        raise ValueError("فایل خالی است")

    PRIVATE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    disk_path = PRIVATE_UPLOAD_DIR / filename
    with open(disk_path, "wb") as f:
        f.write(content)
    return f"{PRIVATE_PATH_PREFIX}{filename}"
