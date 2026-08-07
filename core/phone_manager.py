"""
ماژول مدیریت شماره موبایل کارمندان
- افزودن/حذف/ویرایش شماره
- تعیین شماره پیش‌فرض
- دریافت شماره پیش‌فرض برای ارسال SMS
"""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from database.engine import SessionLocal
from models.employee_phone import EmployeePhone


class PhoneManager:
    """مدیریت شماره موبایل کارمندان"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def add_phone(
            self,
            user_id: str,
            phone_number: str,
            label: str = "",
            is_default: bool = False
    ) -> Dict:
        """افزودن شماره جدید"""
        try:
            # اعتبارسنجی اولیه
            phone_number = phone_number.strip()
            if not phone_number:
                return {"success": False, "message": "شماره موبایل نمی‌تواند خالی باشد"}

            # بررسی تکراری نبودن
            existing = self.db.query(EmployeePhone).filter(
                EmployeePhone.user_id == user_id,
                EmployeePhone.phone_number == phone_number
            ).first()
            if existing:
                return {"success": False, "message": f"⚠️ شماره {phone_number} قبلاً ثبت شده"}

            # اگر این شماره پیش‌فرض است، بقیه را غیر پیش‌فرض کن
            if is_default:
                self.db.query(EmployeePhone).filter(
                    EmployeePhone.user_id == user_id
                ).update({EmployeePhone.is_default: False})

            # اگر اولین شماره کاربر است، خودکار پیش‌فرض شود
            if not is_default:
                count = self.db.query(EmployeePhone).filter(
                    EmployeePhone.user_id == user_id
                ).count()
                if count == 0:
                    is_default = True

            phone = EmployeePhone(
                user_id=user_id,
                phone_number=phone_number,
                label=label or "همراه",
                is_default=is_default
            )
            self.db.add(phone)
            self.db.commit()

            return {
                "success": True,
                "message": f"✅ شماره {phone_number} با موفقیت اضافه شد"
            }

        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"❌ خطا: {e}"}

    def set_default_phone(self, user_id: str, phone_id: int) -> Dict:
        """تعیین شماره پیش‌فرض"""
        try:
            # اول همه را غیر پیش‌فرض کن
            self.db.query(EmployeePhone).filter(
                EmployeePhone.user_id == user_id
            ).update({EmployeePhone.is_default: False})

            # حالا این را پیش‌فرض کن
            phone = self.db.query(EmployeePhone).filter(
                EmployeePhone.id == phone_id,
                EmployeePhone.user_id == user_id
            ).first()

            if not phone:
                return {"success": False, "message": "❌ شماره یافت نشد"}

            phone.is_default = True
            self.db.commit()

            return {
                "success": True,
                "message": f"✅ شماره {phone.phone_number} به عنوان پیش‌فرض تعیین شد"
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"❌ خطا: {e}"}

    def get_default_phone(self, user_id: str) -> Optional[str]:
        """دریافت شماره پیش‌فرض کاربر (اولویت: پیش‌فرض، سپس اولین شماره)"""
        # ابتدا شماره پیش‌فرض
        phone = self.db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user_id,
            EmployeePhone.is_default == True
        ).first()

        if phone:
            return phone.phone_number

        # اگر پیش‌فرض نبود، اولین شماره را برگردان
        phone = self.db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user_id
        ).order_by(EmployeePhone.created_at.asc()).first()

        return phone.phone_number if phone else None

    def get_user_phones(self, user_id: str) -> List[EmployeePhone]:
        """دریافت همه شماره‌های یک کاربر"""
        return self.db.query(EmployeePhone).filter(
            EmployeePhone.user_id == user_id
        ).order_by(EmployeePhone.is_default.desc(), EmployeePhone.created_at.asc()).all()

    def delete_phone(self, phone_id: int, user_id: str) -> Dict:
        """حذف یک شماره"""
        try:
            phone = self.db.query(EmployeePhone).filter(
                EmployeePhone.id == phone_id,
                EmployeePhone.user_id == user_id
            ).first()

            if not phone:
                return {"success": False, "message": "❌ شماره یافت نشد"}

            was_default = phone.is_default
            phone_number = phone.phone_number

            self.db.delete(phone)
            self.db.commit()

            # اگر این پیش‌فرض بود، شماره بعدی را پیش‌فرض کن
            if was_default:
                next_phone = self.db.query(EmployeePhone).filter(
                    EmployeePhone.user_id == user_id
                ).first()
                if next_phone:
                    next_phone.is_default = True
                    self.db.commit()

            return {
                "success": True,
                "message": f"✅ شماره {phone_number} حذف شد"
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"❌ خطا: {e}"}