"""
منطق پردازش پیام‌های ربات
"""
from datetime import date, timedelta
import jdatetime

from bot import bale_api, db
from bot.config import KEYWORDS, SessionLocal


# 🆕 مدیریت state برای ورودی چندمرحله‌ای (تاریخ روز خاص)
user_states = {}  # {chat_id: 'waiting_for_date'}


def parse_jalali_date(date_str: str):
    """🆕 پارس تاریخ شمسی و تبدیل به میلادی"""
    date_str = date_str.strip().replace('-', '/')
    try:
        j_date = jdatetime.datetime.strptime(date_str, "%Y/%m/%d").date()
        return j_date.togregorian()
    except (ValueError, TypeError):
        return None


def is_keyword(text: str, keyword_group: str) -> bool:
    """بررسی تطابق متن با کلیدواژه‌ها"""
    if not text:
        return False
    text = text.strip().lower()
    return text in [k.lower() for k in KEYWORDS.get(keyword_group, [])]


def format_attendance_message(full_name: str, target_date: date, records: list, day_label: str) -> str:
    """ساخت پیام تردد"""
    # تبدیل تاریخ به شمسی
    j_date = jdatetime.date.fromgregorian(date=target_date)
    date_str = j_date.strftime('%Y/%m/%d')

    # نام روز هفته شمسی
    week_days = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
    week_day = week_days[j_date.weekday()]

    message = f"👤 <b>{full_name}</b>\n"

    # 🆕 اگر day_label خالی باشد، فقط تاریخ نمایش داده می‌شود
    if day_label:
        message += f"📅 {day_label} - {date_str} ({week_day})\n"
    else:
        message += f"📅 {date_str} ({week_day})\n"

    message += f"━━━━━━━━━━━━━━━\n"
    message += f"📊 تعداد رکوردها: <b>{len(records)}</b>\n\n"

    if not records:
        message += "⚪ هیچ ترددی ثبت نشده است."
        return message

    for record in records:
        time_str = record.timestamp.strftime('%H:%M:%S')
        if record.punch == 0:
            message += f"🟢 ورود: <b>{time_str}</b>\n"
        elif record.punch == 1:
            message += f"🔴 خروج: <b>{time_str}</b>\n"
        else:
            message += f"⚪ رکورد: <b>{time_str}</b>\n"

    return message

def handle_start(chat_id):
    """پاسخ به /start"""
    db_session = SessionLocal()
    try:
        bale_user = db.get_bale_user(db_session, chat_id)

        if bale_user:
            # کاربر قبلاً ثبت شده
            bale_api.send_message(
                chat_id,
                "✅ شما قبلاً احراز هویت شده‌اید.\n\n"
                "برای مشاهده تردد، از دکمه‌های زیر یا کلیدواژه‌های "
                "<code>today</code> و <code>yesterday</code> استفاده کنید.",
                reply_markup=bale_api.MAIN_MENU_KEYBOARD
            )
        else:
            # کاربر جدید → درخواست شماره
            bale_api.send_message(
                chat_id,
                "👋 به ربات تردد خوش آمدید!\n\n"
                "برای شناسایی، لطفاً شماره موبایل خود را از طریق دکمه زیر ارسال کنید.\n\n"
                "⚠️ <b>توجه:</b> برای امنیت، فقط از طریق دکمه اشتراک‌گذاری شماره اقدام کنید.",
                reply_markup=bale_api.CONTACT_KEYBOARD
            )
    finally:
        db_session.close()


def handle_contact(chat_id, contact):
    """پردازش شماره تماس به اشتراک گذاشته شده"""
    db_session = SessionLocal()
    try:
        phone = contact.get('phone_number', '')

        # 🔐 جستجوی کاربر بر اساس شماره
        user_id = db.find_user_by_phone(db_session, phone)

        if not user_id:
            bale_api.send_message(
                chat_id,
                "❌ شماره شما در سیستم یافت نشد.\n\n"
                "لطفاً با مدیر سیستم تماس بگیرید.",
                reply_markup=bale_api.CONTACT_KEYBOARD
            )
            return

        # ✅ ثبت کاربر
        db.register_bale_user(db_session, chat_id, user_id, phone)
        full_name = db.get_employee_name(db_session, user_id)

        bale_api.send_message(
            chat_id,
            f"✅ <b>{full_name}</b> عزیز، ثبت‌نام شما با موفقیت انجام شد!\n\n"
            f"اکنون می‌توانید تردد خود را مشاهده کنید.\n",
            reply_markup=bale_api.MAIN_MENU_KEYBOARD
        )
    finally:
        db_session.close()


def handle_attendance_request(chat_id, target_date: date, day_label: str):
    """نمایش تردد برای تاریخ مشخص"""
    db_session = SessionLocal()
    try:
        bale_user = db.get_bale_user(db_session, chat_id)

        if not bale_user:
            handle_start(chat_id)
            return

        full_name = db.get_employee_name(db_session, bale_user.user_id)
        records = db.get_attendance_records(db_session, bale_user.user_id, target_date)

        message = format_attendance_message(full_name, target_date, records, day_label)

        bale_api.send_message(
            chat_id,
            message,
            reply_markup=bale_api.MAIN_MENU_KEYBOARD
        )
    finally:
        db_session.close()


def handle_specific_day_request(chat_id):
    """🆕 درخواست تردد یک روز خاص - پرسیدن تاریخ"""
    user_states[chat_id] = 'waiting_for_date'
    bale_api.send_message(
        chat_id,
        "🗓️ لطفاً تاریخ مورد نظر را با فرمت زیر ارسال کنید:\n\n"
        "<code>1405/05/19</code>\n\n"
        "برای انصراف، /start را ارسال کنید."
    )


def handle_specific_date(chat_id, date_str: str):
    """🆕 پردازش تاریخ ارسالی برای تردد یک روز خاص"""
    target_date = parse_jalali_date(date_str)

    if not target_date:
        # فرمت نامعتبر - state حفظ می‌شود تا کاربر دوباره تلاش کند
        bale_api.send_message(
            chat_id,
            "❌ فرمت تاریخ نامعتبر است.\n\n"
            "لطفاً تاریخ را با فرمت <code>1405/05/19</code> ارسال کنید.\n\n"
            "برای انصراف، /start را ارسال کنید."
        )
        return

    # تاریخ معتبر - پاک کردن state و نمایش تردد
    user_states.pop(chat_id, None)

    # day_label خالی → فقط تاریخ نمایش داده می‌شود
    handle_attendance_request(chat_id, target_date, "")


def handle_text_message(chat_id, text: str):
    """پردازش پیام‌های متنی"""
    text = text.strip()

    # 🆕 اگر کاربر در حال وارد کردن تاریخ روز خاص است
    if user_states.get(chat_id) == 'waiting_for_date':
        if is_keyword(text, 'start'):
            user_states.pop(chat_id, None)
            handle_start(chat_id)
            return
        handle_specific_date(chat_id, text)
        return

    # /start
    if is_keyword(text, 'start'):
        handle_start(chat_id)
        return

    # today
    if is_keyword(text, 'today'):
        handle_attendance_request(chat_id, date.today(), "امروز")
        return

    # yesterday
    if is_keyword(text, 'yesterday'):
        yesterday = date.today() - timedelta(days=1)
        handle_attendance_request(chat_id, yesterday, "دیروز")
        return

    # specific day
    if is_keyword(text, 'specific'):
        handle_specific_day_request(chat_id)
        return

    # 🆕 balance (مانده مرخصی)
    if is_keyword(text, 'balance'):
        handle_balance_request(chat_id)
        return

    # 🔐 اگر کاربر شماره را تایپ کرد (به جای دکمه)
    if text.replace('+', '').replace(' ', '').replace('-', '').isdigit():
        bale_api.send_message(
            chat_id,
            "⚠️ برای امنیت، لطفاً شماره خود را <b>فقط از طریق دکمه اشتراک‌گذاری</b> ارسال کنید.\n\n"
            "روی دکمه «📱 ارسال شماره تماس» بزنید.",
            reply_markup=bale_api.CONTACT_KEYBOARD
        )
        return

    # پیام ناشناخته
    bale_api.send_message(
        chat_id,
        "❓ متوجه نشدم.\n\n"
        "لطفاً از یکی از گزینه‌های زیر استفاده کنید:\n"
        "• <code>today</code> یا «امروز» → تردد امروز\n"
        "• <code>yesterday</code> یا «دیروز» → تردد دیروز\n"
        "• «روز خاص» → تردد یک روز خاص\n"
        "• «مانده» → مانده مرخصی",
        reply_markup=bale_api.MAIN_MENU_KEYBOARD
    )


def handle_message(message: dict):
    """پردازش کلی پیام"""
    chat_id = message.get('chat', {}).get('id')
    if not chat_id:
        return

    # 📱 دریافت شماره تماس (از دکمه اشتراک‌گذاری)
    if 'contact' in message:
        handle_contact(chat_id, message['contact'])
        return

    # 📝 پیام متنی
    text = message.get('text', '')
    if text:
        handle_text_message(chat_id, text)


# ============================================
# 🆕 مانده مرخصی
# ============================================

def format_balance_message(full_name: str, year_j: int, balances: dict,
                           prev_year_j: int = None, prev_balances: dict = None,
                           is_transferred: bool = False, transferred_amount: int = 0) -> str:
    """ساخت پیام مانده مرخصی (سال جاری + سال قبل + وضعیت انتقال)"""

    leave_types_info = {
        'AL': ('🌴', 'استحقاقی'),
        'SL': ('🏥', 'استعلاجی'),
        'RL': ('🎁', 'تشویقی'),
    }

    # ━━━━━━━━━ سال جاری ━━━━━━━━━
    message = f"👤 <b>{full_name}</b>\n"
    message += f"💰 مانده مرخصی سال <b>{year_j}</b>\n"
    message += f"━━━━━━━━━━━━━━━\n"

    for code, (emoji, name) in leave_types_info.items():
        balance = balances.get(code, 0)
        message += f"{emoji} {name}: <b>{balance}</b> روز\n"

    # 🆕 نمایش ذخیره منتقل شده از سال قبل (CW سال جاری)
    cw_current = balances.get('CW', 0)
    if cw_current > 0:
        message += f"📦 ذخیره از سال قبل: <b>{cw_current}</b> روز\n"

    # جمع کل سال جاری (شامل CW)
    total = sum(balances.get(code, 0) for code in leave_types_info.keys()) + cw_current
    message += f"━━━━━━━━━━━━━━━\n"
    message += f"📊 جمع کل: <b>{total}</b> روز"

    # ━━━━━━━━━ 🆕 وضعیت مانده سال قبل ━━━━━━━━━
    if prev_balances and prev_year_j:
        # محاسبه مانده‌های سال قبل
        prev_leave_total = sum(
            prev_balances.get(code, 0) for code in leave_types_info.keys()
        )
        prev_cw = prev_balances.get('CW', 0)

        # آیا مانده‌ای در سال قبل وجود دارد یا انتقالی انجام شده؟
        has_prev_balance = prev_leave_total > 0 or prev_cw > 0

        if has_prev_balance or is_transferred:
            message += f"\n\n━━━━━━━━━━━━━━━\n"
            message += f"📦 وضعیت مانده سال <b>{prev_year_j}</b>\n"
            message += f"━━━━━━━━━━━━━━━\n"

            # نمایش مانده‌های باقی‌مانده در سال قبل (فقط غیرصفر)
            shown_items = []
            for code, (emoji, name) in leave_types_info.items():
                balance = prev_balances.get(code, 0)
                if balance != 0:
                    shown_items.append(f"{emoji} {name}: <b>{balance}</b> روز")

            # CW سال قبل (اگر از سال قبل‌تر منتقل شده)
            if prev_cw != 0:
                shown_items.append(f"📦 ذخیره از {prev_year_j - 1}: <b>{prev_cw}</b> روز")

            if shown_items:
                message += "\n".join(shown_items) + "\n"
                message += f"━━━━━━━━━━━━━━━\n"

            # 🆕 وضعیت انتقال به سال جدید
            if is_transferred:
                message += f"✅ به سال {year_j} <b>منتقل شده</b>\n"
                message += f"📦 مقدار ذخیره: <b>{transferred_amount}</b> روز"
            elif prev_leave_total > 0:
                message += f"⚠️ به سال {year_j} <b>منتقل نشده</b>\n"
                message += f"💡 برای انتقال با منابع انسانی تماس بگیرید"

    return message


def handle_balance_request(chat_id):
    """نمایش مانده مرخصی کاربر (سال جاری + سال قبل + وضعیت انتقال)"""
    db_session = SessionLocal()
    try:
        bale_user = db.get_bale_user(db_session, chat_id)

        if not bale_user:
            handle_start(chat_id)
            return

        full_name = db.get_employee_name(db_session, bale_user.user_id)

        # سال جاری و سال قبل شمسی
        current_year_j = jdatetime.date.today().year
        previous_year_j = current_year_j - 1

        # دریافت مانده مرخصی سال جاری
        current_balances = db.get_leave_balances(db_session, bale_user.user_id, current_year_j)

        # دریافت مانده مرخصی سال قبل
        previous_balances = db.get_leave_balances(db_session, bale_user.user_id, previous_year_j)

        # 🆕 تشخیص انتقال مانده به سال جدید
        # اگر CW سال جدید مقدار داشته باشد، یعنی انتقال انجام شده
        transferred_amount = current_balances.get('CW', 0)
        is_transferred = transferred_amount > 0

        message = format_balance_message(
            full_name,
            current_year_j,
            current_balances,
            previous_year_j,
            previous_balances,
            is_transferred,  # 🆕
            transferred_amount  # 🆕
        )

        bale_api.send_message(
            chat_id,
            message,
            reply_markup=bale_api.MAIN_MENU_KEYBOARD
        )
    finally:
        db_session.close()