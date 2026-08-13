"""اجرای سرور وب"""
import uvicorn
from dotenv import load_dotenv
import sys
import io, os

load_dotenv()
import logging

# فعال‌سازی لاگ برای دیباگ
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# تنظیم کدگذاری خروجی به UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
if __name__ == "__main__":
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8082"))

    print(f"🚀 سرور وب در http://{host}:{port} اجرا می‌شود...")

    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=False
    )