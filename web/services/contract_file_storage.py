"""ذخیره و سرو امن فایل قرارداد — adapter روی Unified File Storage."""
from pathlib import Path
from typing import Optional

from fastapi import UploadFile

from web.services.file_storage import (
    CATEGORY_CONFIGS,
    FileStorage,
    FileStorageError,
    get_default_storage,
    get_storage_root,
)

_CONTRACTS = CATEGORY_CONFIGS["contracts"]

# برای سازگاری با تست‌ها و فراخوانی‌های موجود
PRIVATE_PATH_PREFIX = _CONTRACTS.key_prefix
ALLOWED_EXTENSIONS = set(_CONTRACTS.allowed_extensions)
MAX_FILE_SIZE = _CONTRACTS.max_file_size

def _storage() -> FileStorage:
    return get_default_storage()


def __getattr__(name: str):
    """UPLOAD_DIR همیشه مسیر فعلی contracts تحت TIMEX_STORAGE_ROOT را برمی‌گرداند."""
    if name == "UPLOAD_DIR":
        return get_storage_root() / "contracts"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def resolve_contract_file_disk(stored_path: str) -> Path:
    """تبدیل مسیر ذخیره‌شده در DB به مسیر دیسک (legacy static یا private)."""
    try:
        return _storage().resolve(stored_path)
    except FileStorageError as exc:
        raise ValueError(str(exc)) from exc


def delete_contract_file(stored_path: Optional[str]) -> None:
    if not stored_path:
        return
    _storage().delete(stored_path)


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

    content = await upload.read()
    try:
        return _storage().save(
            "contracts",
            content,
            original_filename=upload.filename,
        )
    except FileStorageError as exc:
        if exc.code == "invalid_extension":
            raise ValueError("نوع فایل مجاز نیست (فقط PDF/JPG/PNG)") from exc
        if exc.code == "file_too_large":
            raise ValueError("حجم فایل بیش از ۱۰ مگابایت است") from exc
        if exc.code == "empty_file":
            raise ValueError("فایل خالی است") from exc
        if exc.code == "invalid_filename":
            raise ValueError("نام فایل نامعتبر است") from exc
        raise ValueError(str(exc)) from exc
