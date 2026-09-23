/**
 * فرمت فیلدهای بانکی Timex (کاربر عادی + ادمین)
 *
 * - شماره کارت: فقط ارقام، نمایش گروه‌بندی 4-4-4-4 با '-'،
 *   هنگام ارسال فرم فقط 16 رقم بدون '-' روی سرور می‌رود.
 * - شماره شبا: پیشوند ثابت و غیرقابل ویرایش IR + حداکثر 24 رقم قابل ویرایش؛
 *   مقدار فیلد مخفی name="sheba" همیشه IR + ارقام است.
 * - شماره حساب: فقط ارقام (حداکثر 50 رقم، مطابق String(50) دیتابیس)؛
 *   حروف/فاصله/نشانه حذف و ارقام فارسی/عربی به ASCII تبدیل می‌شوند.
 * - ارقام فارسی/عربی به ASCII نرمال می‌شوند (همانند سمت سرور).
 *
 * بدون اعتبارسنجی چک‌سام (Luhn / MOD-97) در سمت کلاینت؛
 * اعتبارسنجی سرور کاملاً مرجع است.
 */
(function () {
    'use strict';

    var PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩';
    var MAX_CARD_DIGITS = 16;
    var MAX_SHEBA_DIGITS = 24;
    var MAX_ACCOUNT_DIGITS = 50;

    // فقط ارقام (با نرمال‌سازی فارسی/عربی)؛ کاراکترهای دیگر حذف می‌شوند
    function toAsciiDigits(value) {
        var text = String(value == null ? '' : value);
        var out = '';
        for (var i = 0; i < text.length; i++) {
            var ch = text.charAt(i);
            var faIndex = PERSIAN_DIGITS.indexOf(ch);
            if (faIndex >= 0) {
                out += String(faIndex % 10);
            } else if (ch >= '0' && ch <= '9') {
                out += ch;
            }
        }
        return out;
    }

    function cardDigits(value) {
        return toAsciiDigits(value).slice(0, MAX_CARD_DIGITS);
    }

    // نمایش گروه‌بندی 4 رقمی با '-' (فقط ظاهری)
    function formatCard(value) {
        var digits = cardDigits(value);
        var groups = digits.match(/.{1,4}/g);
        return groups ? groups.join('-') : '';
    }

    function shebaDigits(value) {
        var text = String(value == null ? '' : value).trim();
        if (/^ir/i.test(text)) {
            text = text.substring(2);
        }
        return toAsciiDigits(text).slice(0, MAX_SHEBA_DIGITS);
    }

    function shebaValue(digits) {
        return digits ? 'IR' + digits : '';
    }

    // شماره حساب: رشتهٔ سادهٔ عددی؛ صفرهای ابتدایی حفظ می‌شوند
    function accountNumberValue(value) {
        return toAsciiDigits(value).slice(0, MAX_ACCOUNT_DIGITS);
    }

    function caretAfterDigits(formatted, digitCount) {
        var pos = 0;
        var seen = 0;
        while (pos < formatted.length && seen < digitCount) {
            var ch = formatted.charAt(pos);
            if (ch >= '0' && ch <= '9') {
                seen += 1;
            }
            pos += 1;
        }
        return pos;
    }

    function bindCardInput(input) {
        function reformat() {
            var caret = input.selectionStart;
            var digitsBefore = caret == null
                ? null
                : toAsciiDigits(input.value.slice(0, caret)).length;
            input.value = formatCard(input.value);
            if (digitsBefore != null && typeof input.setSelectionRange === 'function') {
                var pos = caretAfterDigits(input.value, digitsBefore);
                input.setSelectionRange(pos, pos);
            }
        }
        input.addEventListener('input', reformat);
        reformat();
    }

    function bindShebaInput(digitsInput) {
        var form = digitsInput.form;
        var hidden = form ? form.querySelector('[data-sheba-hidden]') : null;

        function sync() {
            digitsInput.value = shebaDigits(digitsInput.value);
            if (hidden) {
                hidden.value = shebaValue(digitsInput.value);
            }
        }
        digitsInput.addEventListener('input', sync);
        sync();
    }

    function bindAccountInput(input) {
        function sync() {
            input.value = accountNumberValue(input.value);
        }
        input.addEventListener('input', sync);
        sync();
    }

    // قبل از ارسال: کارت بدون '-'، شبا به شکل IR + 24 رقم، شماره حساب فقط ارقام
    function prepareSubmit(form) {
        var card = form.querySelector('[data-bank-card]');
        if (card) {
            card.value = cardDigits(card.value);
        }
        var digits = form.querySelector('[data-sheba-digits]');
        var hidden = form.querySelector('[data-sheba-hidden]');
        if (digits && hidden) {
            hidden.value = shebaValue(shebaDigits(digits.value));
        }
        var account = form.querySelector('[data-account-number]');
        if (account) {
            account.value = accountNumberValue(account.value);
        }
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (form && form.tagName === 'FORM') {
            prepareSubmit(form);
        }
    }, true);

    document.addEventListener('DOMContentLoaded', function () {
        var cards = document.querySelectorAll('[data-bank-card]');
        for (var i = 0; i < cards.length; i++) {
            bindCardInput(cards[i]);
        }
        var shebas = document.querySelectorAll('[data-sheba-digits]');
        for (var j = 0; j < shebas.length; j++) {
            bindShebaInput(shebas[j]);
        }
        var accounts = document.querySelectorAll('[data-account-number]');
        for (var k = 0; k < accounts.length; k++) {
            bindAccountInput(accounts[k]);
        }
    });

    window.TimexBank = {
        formatCard: formatCard,
        cardDigits: cardDigits,
        shebaDigits: shebaDigits,
        shebaValue: shebaValue,
        accountNumberValue: accountNumberValue
    };
})();
