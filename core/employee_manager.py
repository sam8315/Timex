"""
ماژول مدیریت اطلاعات تکمیلی کارمندان
"""
from datetime import date
from typing import List, Dict, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
import jdatetime

from database.engine import SessionLocal
from models.user import User
from models.employee import Employee


class EmployeeManager:
    """مدیریت اطلاعات تکمیلی کارمندان"""

    def __init__(self):
        self.db: Session = SessionLocal()

    def close(self):
        if self.db:
            self.db.close()

    def add_employee(
            self,
            user_id: str,
            first_name: str,
            last_name: str,
            national_code: Optional[str] = None,
            father_name: Optional[str] = None,
            birth_date: Optional[date] = None,
            gender: Optional[str] = None,
            marital_status: Optional[str] = None,
            email: Optional[str] = None,
            hire_date: Optional[date] = None,
            department: Optional[str] = None,
            position: Optional[str] = None,
            notes: Optional[str] = None
    ) -> Dict:
        """افزودن اطلاعات تکمیلی کارمند"""
        # بررسی وجود کاربر
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return {'success': False, 'message': f'❌ کاربر {user_id} یافت نشد'}

        # بررسی تکراری نبودن کد ملی
        if national_code:
            existing = self.db.query(Employee).filter(
                Employee.national_code == national_code
            ).first()
            if existing:
                return {
                    'success': False,
                    'message': f'❌ کد ملی {national_code} قبلاً ثبت شده است'
                }

        # بررسی وجود اطلاعات قبلی
        existing = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if existing:
            return {
                'success': False,
                'message': f'⚠️  اطلاعات این کاربر قبلاً ثبت شده است. از ویرایش استفاده کنید'
            }

        try:
            employee = Employee(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                national_code=national_code,
                father_name=father_name,
                birth_date=birth_date,
                gender=gender,
                marital_status=marital_status,
                email=email,
                hire_date=hire_date,
                department=department,
                position=position,
                notes=notes
            )
            self.db.add(employee)
            self.db.commit()

            return {
                'success': True,
                'message': f'✅ اطلاعات کارمند {first_name} {last_name} با موفقیت ثبت شد',
                'employee_id': employee.id
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def update_employee(self, user_id: str, **kwargs) -> Dict:
        """به‌روزرسانی اطلاعات کارمند"""
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            return {'success': False, 'message': '❌ اطلاعات کارمند یافت نشد'}

        try:
            for key, value in kwargs.items():
                if hasattr(employee, key):
                    setattr(employee, key, value)

            self.db.commit()
            return {'success': True, 'message': '✅ اطلاعات با موفقیت به‌روز شد'}

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}

    def get_employee(self, user_id: str) -> Optional[Employee]:
        """دریافت اطلاعات کارمند"""
        return self.db.query(Employee).filter(Employee.user_id == user_id).first()

    def get_all_employees(self, active_only: bool = False) -> List[Employee]:
        """دریافت تمام کارمندان"""
        query = self.db.query(Employee)
        if active_only:
            query = query.filter(Employee.is_active == True)
        return query.order_by(Employee.last_name, Employee.first_name).all()

    def search_employees(
            self,
            query: str,
            field: str = 'all'
    ) -> List[Employee]:
        """جستجو در اطلاعات کارمندان"""
        q = self.db.query(Employee)

        if field == 'all':
            q = q.filter(
                or_(
                    Employee.first_name.ilike(f'%{query}%'),
                    Employee.last_name.ilike(f'%{query}%'),
                    Employee.national_code.ilike(f'%{query}%'),
                    Employee.department.ilike(f'%{query}%'),
                    Employee.position.ilike(f'%{query}%')
                )
            )
        elif field == 'name':
            q = q.filter(
                or_(
                    Employee.first_name.ilike(f'%{query}%'),
                    Employee.last_name.ilike(f'%{query}%')
                )
            )
        elif field == 'national_code':
            q = q.filter(Employee.national_code.ilike(f'%{query}%'))
        elif field == 'department':
            q = q.filter(Employee.department.ilike(f'%{query}%'))
        elif field == 'position':
            q = q.filter(Employee.position.ilike(f'%{query}%'))

        return q.all()

    def get_employees_by_department(self, department: str) -> List[Employee]:
        """دریافت کارمندان یک دپارتمان"""
        return self.db.query(Employee).filter(
            Employee.department == department
        ).order_by(Employee.last_name).all()

    def get_departments(self) -> List[str]:
        """دریافت لیست دپارتمان‌ها"""
        results = self.db.query(Employee.department).distinct().all()
        return sorted([r[0] for r in results if r[0]])

    def get_statistics(self) -> Dict:
        """آمار کارمندان"""
        total = self.db.query(Employee).count()
        active = self.db.query(Employee).filter(Employee.is_active == True).count()
        inactive = total - active

        with_national_code = self.db.query(Employee).filter(
            Employee.national_code != None,
            Employee.is_active == True
        ).count()
        with_email = self.db.query(Employee).filter(
            Employee.email != None,
            Employee.is_active == True
        ).count()

        # آمار جنسیت (فقط فعال‌ها)
        males = self.db.query(Employee).filter(
            Employee.gender == 'M',
            Employee.is_active == True
        ).count()
        females = self.db.query(Employee).filter(
            Employee.gender == 'F',
            Employee.is_active == True
        ).count()

        # آمار تاهل (فقط فعال‌ها)
        married = self.db.query(Employee).filter(
            Employee.marital_status == 'M',
            Employee.is_active == True
        ).count()
        single = self.db.query(Employee).filter(
            Employee.marital_status == 'S',
            Employee.is_active == True
        ).count()

        # تعداد دپارتمان‌ها (فقط فعال‌ها)
        departments = self.db.query(Employee.department).filter(
            Employee.is_active == True
        ).distinct().count()

        return {
            'total': total,
            'active': active,
            'inactive': inactive,
            'with_national_code': with_national_code,
            'with_email': with_email,
            'males': males,
            'females': females,
            'married': married,
            'single': single,
            'departments': departments
        }

    def get_full_name(self, user_id: str) -> str:
        """
        دریافت نام کامل کاربر از جدول employee
        """
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee:
            return employee.full_name

        # اگر در employee نبود، کد پرسنلی را برگردان
        return f"کاربر {user_id}"

    @staticmethod
    def get_full_name_static(db: Session, user_id: str) -> str:
        """نسخه استاتیک"""
        from models.employee import Employee

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee:
            return employee.full_name

        return f"کاربر {user_id}"

    @staticmethod
    def get_full_name_static(db: Session, user_id: str) -> str:
        """نسخه استاتیک برای استفاده در جاهایی که instance نداریم"""
        from models.employee import Employee

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee:
            return employee.full_name

        user = db.query(User).filter(User.user_id == user_id).first()
        return user.name if user else user_id

    def get_group_name(self, user_id: str) -> str:
        """
        دریافت نام گروه از فیلد department جدول employee
        """
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee and employee.department:
            return employee.department

        return "بدون گروه"

    @staticmethod
    def get_group_name_static(db: Session, user_id: str) -> str:
        """نسخه استاتیک"""
        from models.employee import Employee

        employee = db.query(Employee).filter(Employee.user_id == user_id).first()
        if employee and employee.department:
            return employee.department

        return "بدون گروه"

    def set_employee_status(
            self,
            user_id: str,
            is_active: bool,
            termination_date: Optional[date] = None,
            termination_reason: Optional[str] = None
    ) -> Dict:
        """
        تغییر وضعیت فعال/غیرفعال کارمند
        """
        employee = self.db.query(Employee).filter(Employee.user_id == user_id).first()
        if not employee:
            return {'success': False, 'message': '❌ اطلاعات کارمند یافت نشد'}

        try:
            employee.is_active = is_active

            if not is_active:
                # اگر غیرفعال شد، تاریخ ترک کار را ثبت کن
                employee.termination_date = termination_date or date.today()
                employee.termination_reason = termination_reason
            else:
                # اگر فعال شد، تاریخ ترک کار را پاک کن
                employee.termination_date = None
                employee.termination_reason = None

            self.db.commit()

            status_name = "فعال" if is_active else "غیرفعال"
            return {
                'success': True,
                'message': f'✅ وضعیت کارمند به "{status_name}" تغییر کرد'
            }

        except Exception as e:
            self.db.rollback()
            return {'success': False, 'message': f'❌ خطا: {e}'}