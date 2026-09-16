(function () {
    'use strict';

    var isFormatting = false;
    var messages = {
        hour: 'ساعت باید بین 00 و 23 باشد',
        minute: 'دقیقه باید بین 00 و 59 باشد'
    };

    function sanitize(value) {
        return (value || '').replace(/[^0-9:]/g, '');
    }

    function isValidTimeValue(value) {
        return typeof value === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);
    }

    function setValidity(input, message) {
        if (typeof input.setCustomValidity === 'function') {
            input.setCustomValidity(message || '');
        }
        if (input.classList) {
            input.classList.toggle('is-invalid', Boolean(message));
        }
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
    }

    function shouldInsertColon(digits, hour) {
        return digits.length === 2 && hour <= 23;
    }

    function getCaretPosition(input, rawValue, formattedValue, event) {
        var wasSelection = typeof input.selectionStart === 'number'
            && input.selectionStart !== input.selectionEnd;

        if (!event || event.inputType === 'insertFromPaste'
                || event.inputType === 'insertReplacementText' || wasSelection) {
            return formattedValue.length;
        }

        var position = input.selectionStart;
        if (typeof position !== 'number') {
            return formattedValue.length;
        }

        var digitsBeforeCaret = rawValue.slice(0, position).replace(/\D/g, '');
        if (digitsBeforeCaret.length >= 4) {
            return formattedValue.length;
        }
        if (digitsBeforeCaret.length === 3) {
            return 4;
        }
        if (digitsBeforeCaret.length === 2) {
            return shouldInsertColon(digitsBeforeCaret, parseInt(digitsBeforeCaret, 10)) ? 3 : 2;
        }
        return digitsBeforeCaret.length;
    }

    function formatForSingleDigit(hourDigit, event) {
        // Smart input: first digit is 3-9 -> treat as leading-zero hour and jump to minute
        if (hourDigit >= 3 && hourDigit <= 9) {
            return ('0' + hourDigit) + ':';
        }
        return null;
    }

    function formatMinuteFirstDigit(minDigit) {
        if (minDigit >= 6 && minDigit <= 9) {
            return '0' + minDigit;
        }
        return null;
    }

    function normalizeTimeInput(input, event) {
        if (isFormatting || !input) {
            return;
        }

        isFormatting = true;
        try {
            var rawValue = sanitize(input.value);

            // If the user just deleted or backspaced and the result is empty or shorter,
            // allow clean partial state without forcing immediate full reformat.
            var isBackspaceOrDelete = event && (event.inputType === 'deleteContentBackward' || event.inputType === 'deleteContentForward');

            // If deleting and we have exactly the colon or empty after colon, keep clean
            // We'll just sanitize and format naturally; don't force restore.

            if (rawValue !== input.value) {
                input.value = rawValue;
            }

            if (isBackspaceOrDelete) {
                // During deletion: sanitize only, do not restore/rebuild value
                // Preserve natural partial states (07:3, 07:, 07, 0, '')
                // Do NOT apply smart-input logic; just clean non-digit/non-colon chars
                if (rawValue !== input.value) {
                    input.value = rawValue;
                }
                // Clear validity on partial/empty; set only if clearly invalid
                var msg = '';
                if (rawValue.length >= 2) {
                    var h = parseInt(rawValue.slice(0, 2), 10);
                    if (!isNaN(h) && h > 23) msg = messages.hour;
                }
                if (rawValue.length === 4) {
                    var m = parseInt(rawValue.slice(3, 5), 10);
                    if (!isNaN(m) && m > 59) msg = messages.minute;
                }
                setValidity(input, msg);
                // Preserve cursor naturally based on event; do not force to end
                if (event && typeof event.selectionStart === 'number') {
                    // Browser has already updated selection; don't override
                } else if (typeof input.setSelectionRange === 'function') {
                    // Fallback: put caret at end of current clean value only if no selection info
                    var len = input.value.length;
                    input.setSelectionRange(len, len);
                }
                return;
            }

            // Process smart single-digit input when typing (not paste, not selection replace)
            var isInsert = event && (event.inputType === 'insertText' || event.inputType === 'insertCompositionText');
            var digitsOnly = rawValue.replace(/:/g, '');

            // Smart hour first digit
            if (isInsert && digitsOnly.length === 1 && !isBackspaceOrDelete) {
                var firstDigit = parseInt(digitsOnly, 10);
                if (firstDigit >= 3 && firstDigit <= 9) {
                    var smartValue = ('0' + digitsOnly) + ':';
                    if (smartValue !== input.value) {
                        input.value = smartValue;
                    }
                    setValidity(input, '');
                    var caretPos = smartValue.length;
                    if (typeof input.setSelectionRange === 'function') {
                        input.setSelectionRange(caretPos, caretPos);
                    }
                    // Notify duration after smart normalization completes
                    if (typeof Event === 'function') {
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    } else {
                        var ev2 = document.createEvent('Event');
                        ev2.initEvent('input', true, true);
                        input.dispatchEvent(ev2);
                    }
                    return;
                }
            }

            // Smart minute first digit: after colon with exactly 1 digit 6-9
            var colonIndex = input.value.indexOf(':');
            if (isInsert && colonIndex !== -1 && digitsOnly.length === 3 && !isBackspaceOrDelete) {
                var minFirst = parseInt(digitsOnly.slice(2, 3), 10);
                if (minFirst >= 6 && minFirst <= 9) {
                    var formattedMinute = '0' + minFirst;
                    var smartMinuteValue = digitsOnly.slice(0, 2) + ':' + formattedMinute;
                    if (smartMinuteValue !== input.value) {
                        input.value = smartMinuteValue;
                    }
                    setValidity(input, '');
                    var caretPos2 = smartMinuteValue.length;
                    if (typeof input.setSelectionRange === 'function') {
                        input.setSelectionRange(caretPos2, caretPos2);
                    }
                    // Notify duration after smart minute normalization
                    if (typeof Event === 'function') {
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    } else {
                        var ev3 = document.createEvent('Event');
                        ev3.initEvent('input', true, true);
                        input.dispatchEvent(ev3);
                    }
                    return;
                }
            }

            var digits = rawValue.replace(/:/g, '').slice(0, 4);
            var hourText = digits.slice(0, 2);
            var minuteText = digits.slice(2, 4);
            var hour = hourText ? parseInt(hourText, 10) : 0;
            var minute = minuteText ? parseInt(minuteText, 10) : 0;
            var insertColon = shouldInsertColon(digits, hour);
            var formattedValue;

            if (digits.length === 0) {
                formattedValue = '';
            } else if (digits.length === 1) {
                formattedValue = digits;
            } else if (digits.length === 2) {
                // If colon already present (from previous smart formatting or paste), preserve it
                if (rawValue.indexOf(':') === 2 && digits.length === 2) {
                    formattedValue = digits + ':';
                } else {
                    formattedValue = insertColon ? hourText + ':' : hourText;
                }
            } else if (digits.length === 3) {
                // Partial minute: only 1 minute digit entered after colon
                formattedValue = hourText + ':' + minuteText;
            } else {
                formattedValue = hourText + ':' + minuteText;
            }

            if (formattedValue !== input.value) {
                input.value = formattedValue;
            }

            var message = '';
            if (digits.length >= 2 && hour > 23) {
                message = messages.hour;
            } else if (digits.length === 4 && minute > 59) {
                message = messages.minute;
            }
            setValidity(input, message);

            var caretPosition = getCaretPosition(input, rawValue, formattedValue, event);
            if (typeof input.setSelectionRange === 'function') {
                input.setSelectionRange(caretPosition, caretPosition);
            }

            // After normalization to a valid full time, notify duration listeners
            if (isValidTimeValue(input.value)) {
                if (typeof Event === 'function') {
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                } else {
                    var ev = document.createEvent('Event');
                    ev.initEvent('input', true, true);
                    input.dispatchEvent(ev);
                }
            }
        } finally {
            isFormatting = false;
        }
    }

    function formatTimeInput(input) {
        if (!input || input.getAttribute('data-time-input') !== 'true'
                || input.getAttribute('data-time-input-listener') === 'true') {
            return;
        }

        input.setAttribute('data-time-input-listener', 'true');
        input.addEventListener('input', function (event) {
            normalizeTimeInput(input, event);
        });
    }

    function initTimeInputs() {
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-time-input="true"]'),
            formatTimeInput
        );
    }

    window.formatTimeInput = formatTimeInput;
    window.isValidTimeValue = isValidTimeValue;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTimeInputs);
    } else {
        initTimeInputs();
    }
}());
