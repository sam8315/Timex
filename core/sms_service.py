"""
سرویس ارسال پیامک
- ارسال از طریق API
- قالب‌های آماده برای مرخصی
- مدیریت خطا بدون تأثیر بر فرآیند اصلی
"""
import requests
import os
import logging
from typing import List, Dict
from dotenv import load_dotenv
import jdatetime
from datetime import date

load_dotenv()

logger = logging.getLogger(__name__)


class SmsService:
    """سرویس ارسال پیامک"""

    # نام فارسی انواع مرخصی
    LEAVE_TYPE_NAMES = {
        'AL': 'استحقاقی',
        'SL': 'استعلاجی',
        'RL': 'تشویقی',
        'UL': 'بدون حقوق',
        'CW': 'ذخیره سال قبل'
    }

    def __init__(self):
        self.api_url = os.getenv("SMS_API_URL")
        self.api_key = os.getenv("SMS_API_KEY")
        self.enabled = os.getenv("SMS_ENABLED", "false").lower() == "true"
        self.campaign_name = os.getenv("SMS_CAMPAIGN_NAME", "Timex Notifications")

    def _is_config_valid(self) -> bool:
        """بررسی پیکربندی"""
        if not self.enabled:
            logger.info("ℹ️ سرویس پیامک غیرفعال است")
            return False
        if not self.api_url or not self.api_key:
            logger.warning("⚠️ تنظیمات SMS ناقص است (SMS_API_URL یا SMS_API_KEY)")
            return False
        return True

    def send_sms(self, phones: List[str], message: str) -> Dict:
        """ارسال پیامک به یک یا چند شماره"""
        if not self._is_config_valid():
            return {"success": False, "message": "سرویس پیامک غیرفعال یا تنظیم نشده"}

        if not phones:
            return {"success": False, "message": "شماره‌ای برای ارسال وجود ندارد"}

        try:
            headers = {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "phones": phones,
                "message": message,
                "campaign_name": self.campaign_name
            }

            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                logger.info(f"✅ پیامک ارسال شد به {phones}")
                return {"success": True, "response": response.json()}
            else:
                logger.error(f"❌ خطای API: {response.status_code} - {response.text}")
                return {
                    "success": False,
                    "message": f"خطای سرور SMS: {response.status_code}"
                }

        except requests.exceptions.Timeout:
            logger.error("⏱️ Timeout در ارسال پیامک")
            return {"success": False, "message": "Timeout در ارتباط با سرور پیامک"}
        except requests.exceptions.ConnectionError:
            logger.error("🔌 خطای اتصال به سرور پیامک")
            return {"success": False, "message": "عدم اتصال به سرور پیامک"}
        except Exception as e:
            logger.error(f"❌ خطای غیرمنتظره: {e}")
            return {"success": False, "message": str(e)}

    def send_leave_approval_sms(
            self,
            phones: List[str],
            leave_type: str,
            from_date: date,
            to_date: date,
            days_count: int
    ) -> Dict:
        """ارسال پیامک تأیید مرخصی"""
        type_name = self.LEAVE_TYPE_NAMES.get(leave_type, leave_type)

        # تبدیل به تاریخ شمسی
        j_from = jdatetime.date.fromgregorian(date=from_date)
        j_to = jdatetime.date.fromgregorian(date=to_date)

        message = (
            f"✅ مرخصی {type_name} شما تأیید شد.\n"
            f"از تاریخ {j_from.strftime('%Y/%m/%d')} "
            f"تا {j_to.strftime('%Y/%m/%d')}\n"
            f"به مدت {days_count} روز\n"
            f"سامانه حضور و غیاب"
        )

        return self.send_sms(phones, message)

    def send_leave_rejection_sms(
            self,
            phones: List[str],
            leave_type: str,
            from_date: date,
            to_date: date,
            reason: str = ""
    ) -> Dict:
        """ارسال پیامک رد مرخصی"""
        type_name = self.LEAVE_TYPE_NAMES.get(leave_type, leave_type)

        j_from = jdatetime.date.fromgregorian(date=from_date)
        j_to = jdatetime.date.fromgregorian(date=to_date)

        message = (
            f"❌ درخواست مرخصی {type_name} شما رد شد.\n"
            f"از تاریخ {j_from.strftime('%Y/%m/%d')} "
            f"تا {j_to.strftime('%Y/%m/%d')}\n"
        )

        if reason:
            message += f"دلیل: {reason}\n"

        message += "سامانه حضور و غیاب"

        return self.send_sms(phones, message)