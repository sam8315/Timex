"""
واژه‌نامه مفاهیم مرخصی و محل ذخیره در مدل Timex.

منبع حقیقت دامنه برای شارژ استحقاق، ذخیره، بازخرید و سوخت.
"""
from typing import Dict

# انواع مانده قابل‌مصرف در درخواست مرخصی
LEAVE_TYPE_AL = 'AL'   # استحقاق سال جاری
LEAVE_TYPE_SL = 'SL'   # استعلاجی
LEAVE_TYPE_RL = 'RL'   # تشویقی
LEAVE_TYPE_UL = 'UL'   # بدون حقوق
LEAVE_TYPE_CW = 'CW'   # ذخیره / انتقالی از سال قبل
LEAVE_TYPE_HL = 'HL'   # ساعتی (درخواست؛ مانده جدا ندارد)

# نوع ماندهٔ فرآیندی (قابل درخواست مرخصی نیست)
LEAVE_TYPE_BB = 'BB'   # سهمیه/ماندهٔ قابل‌بازخرید (فرآیندی)

# انواع تراکنش دفترکل
TX_CHARGE = 'CHARGE'
TX_DEDUCT = 'DEDUCT'
TX_REVERSE = 'REVERSE'
TX_USE = 'USE'
TX_ADJUST = 'ADJUST'
TX_IMPORT = 'IMPORT'
TX_BURN = 'BURN'       # سوخت‌شده — فقط تاریخچه
TX_CASH_OUT = 'CASH_OUT'
TX_CF_OUT = 'CF_OUT'
TX_CF_IN = 'CF_IN'

# Seed/legacy identity map فقط — runtime behavior از membership_types.behavior_profile
# و web.services.membership_semantics می‌آید. این ثابت‌ها را در مسیر entitlement/travel
# جدید استفاده نکنید (A/B seed compatibility).
MEMBERSHIP_PRORATE_BY_CONTRACT = frozenset({'3', '4', '6', '7'})
MEMBERSHIP_PERMANENT = '1'
MEMBERSHIP_CONSCRIPT = '2'
MEMBERSHIP_PHYSICIAN = '5'

# کدهای عضویت با کلید مستقل در Leave Policy (بدون remap 6/7→4) — seed/policy keys
POLICY_MEMBERSHIP_CODES = frozenset({'1', '2', '3', '4', '5', '6', '7'})

LEAVE_TYPE_NAMES: Dict[str, str] = {
    LEAVE_TYPE_AL: 'استحقاقی',
    LEAVE_TYPE_SL: 'استعلاجی',
    LEAVE_TYPE_RL: 'تشویقی',
    LEAVE_TYPE_UL: 'بدون حقوق',
    LEAVE_TYPE_CW: 'ذخیره سال قبل',
    LEAVE_TYPE_HL: 'ساعتی',
    LEAVE_TYPE_BB: 'قابل بازخرید',
}

TX_TYPE_NAMES: Dict[str, str] = {
    TX_CHARGE: 'شارژ',
    TX_DEDUCT: 'کسر',
    TX_REVERSE: 'بازگشت',
    TX_USE: 'مصرف',
    TX_ADJUST: 'تعدیل دستی',
    TX_IMPORT: 'ورود از منابع انسانی',
    TX_BURN: 'سوخت‌شده',
    TX_CASH_OUT: 'بازخرید نقدی',
    TX_CF_OUT: 'خروج انتقال',
    TX_CF_IN: 'ورود انتقال',
}

# انواع قابل انتخاب در فرم درخواست مرخصی کاربر
REQUESTABLE_LEAVE_TYPES = frozenset({
    LEAVE_TYPE_AL, LEAVE_TYPE_SL, LEAVE_TYPE_RL, LEAVE_TYPE_UL, LEAVE_TYPE_CW, LEAVE_TYPE_HL,
})

GLOSSARY_FA = {
    LEAVE_TYPE_AL: (
        'روزهای اعطایی همان سال شمسی بر اساس عضویت مؤثر و سیاست مرخصی.'
    ),
    LEAVE_TYPE_CW: (
        'مانده استفاده‌نشدهٔ سال(های) قبل که طبق قانون عضویت اجازهٔ انتقال گرفته است.'
    ),
    TX_USE: 'کسر بابت درخواست تأییدشده.',
    LEAVE_TYPE_BB: (
        'سقف سیاست برای تقسیم منطقی ذخیره (CW) به بخش قابل‌بازخرید و غیرقابل‌بازخرید؛ '
        'در تأیید مرخصی روزمره از leave_buyback_quotas کم نمی‌شود — '
        'اولویت کسر: CW غیرقابل‌بازخرید → AL → CW قابل‌بازخرید.'
    ),
    TX_BURN: (
        'مانده‌ای که نه ذخیره شد نه بازخرید؛ فقط در دفترکل برای تاریخچه ثبت می‌شود.'
    ),
}
