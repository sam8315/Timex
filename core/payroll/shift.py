"""فوق‌العاده نوبت‌کاری از سیاست عضویت. درصدها داخل موتور ثابت نیستند."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.payroll.money import D, money_round

PATTERN_MORNING_EVENING = "morning_evening"
PATTERN_MORNING_EVENING_NIGHT = "morning_evening_night"
PATTERN_MORNING_NIGHT = "morning_night"
PATTERN_EVENING_NIGHT = "evening_night"
PATTERN_NIGHT_PAIR = "night_pair"
PATTERN_NONE = "none"

PATTERN_LABELS = {
    PATTERN_MORNING_EVENING: "صبح و عصر",
    PATTERN_MORNING_EVENING_NIGHT: "صبح و عصر و شب",
    PATTERN_MORNING_NIGHT: "صبح و شب",
    PATTERN_EVENING_NIGHT: "عصر و شب",
    PATTERN_NIGHT_PAIR: "صبح و شب یا عصر و شب",
    PATTERN_NONE: "بدون نوبت‌کاری",
}

SHIFT_OPTIONS = (
    (PATTERN_NONE, PATTERN_LABELS[PATTERN_NONE]),
    (PATTERN_MORNING_EVENING, PATTERN_LABELS[PATTERN_MORNING_EVENING]),
    (PATTERN_MORNING_EVENING_NIGHT, PATTERN_LABELS[PATTERN_MORNING_EVENING_NIGHT]),
    (PATTERN_NIGHT_PAIR, PATTERN_LABELS[PATTERN_NIGHT_PAIR]),
)


@dataclass(frozen=True)
class ShiftRule:
    basis_codes: tuple[str, ...]
    pct_morning_evening: Decimal = D("10")
    pct_morning_evening_night: Decimal = D("15")
    pct_morning_night: Decimal = D("22.5")
    pct_evening_night: Decimal = D("22.5")

    def percent_for(self, pattern: str) -> Decimal:
        return {
            PATTERN_MORNING_EVENING: D(self.pct_morning_evening),
            PATTERN_MORNING_EVENING_NIGHT: D(self.pct_morning_evening_night),
            PATTERN_MORNING_NIGHT: D(self.pct_morning_night),
            PATTERN_EVENING_NIGHT: D(self.pct_evening_night),
            PATTERN_NIGHT_PAIR: D(self.pct_morning_night),
        }.get(pattern, D(0))


def parse_shift_basis_codes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen = []
    for part in str(raw).split(","):
        code = part.strip()
        if code and code not in seen and code not in ("SHIFT", "WORK_DEFICIT"):
            seen.append(code)
    return tuple(seen)


def detect_shift_pattern(morning: Decimal, evening: Decimal, night: Decimal) -> str | None:
    """ترکیب نوبت از وجود ساعت در هر باند ماه. یک باند به‌تنهایی نوبت‌کاری نیست."""
    has_morning = D(morning) > 0
    has_evening = D(evening) > 0
    has_night = D(night) > 0
    if has_morning and has_evening and has_night:
        return PATTERN_MORNING_EVENING_NIGHT
    if has_morning and has_evening:
        return PATTERN_MORNING_EVENING
    if has_morning and has_night:
        return PATTERN_MORNING_NIGHT
    if has_evening and has_night:
        return PATTERN_EVENING_NIGHT
    return None


def shift_pay(basis: Decimal, percent: Decimal) -> Decimal:
    if D(basis) <= 0 or D(percent) <= 0:
        return D(0)
    return money_round(D(basis) * D(percent) / D(100))
