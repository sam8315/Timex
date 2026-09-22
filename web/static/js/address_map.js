/* انتخاب موقعیت آدرس روی نقشه (Leaflet + OpenStreetMap)
 *
 * استفاده:
 *   TimexAddressMap.bindPicker({
 *     modalId: 'addAddressModal',  // شناسه مودال بوت‌استرپ
 *     mapId:   'userAddMap',        // شناسه div نقشه
 *     latId:   'userAddLat',        // شناسه input عرض جغرافیایی
 *     lngId:   'userAddLng',        // شناسه input طول جغرافیایی
 *     geoId:   'userAddGeo',        // شناسه دکمه موقعیت فعلی (اختیاری)
 *     msgId:   'userAddMsg',        // شناسه پیام خطا (اختیاری)
 *   });
 *
 * - کلیک روی نقشه یا جابه‌جایی نشانگر => به‌روزرسانی inputها
 * - ویرایش دستی inputها => جابه‌جایی نشانگر (فقط اگر معتبر باشند)
 * - مختصات خالی => نمای پیش‌فرض بدون نشانگر (بدون مختصات جعلی)
 * - هیچ درخواست خارجی به‌جز تایل‌های نقشه ارسال نمی‌شود (بدون ژئوکدینگ)
 */
var TimexAddressMap = (function () {
    'use strict';

    // نمای پیش‌فرض (تهران) وقتی مختصاتی ثبت نشده است
    var DEFAULT_LAT = 35.6892;
    var DEFAULT_LNG = 51.3890;
    var DEFAULT_ZOOM = 11;
    var SAVED_ZOOM = 15;

    function fmt(v) {
        // حداکثر ۷ رقم اعشار (سازگار با NUMERIC(10,7)) بدون صفرهای اضافه
        return String(Math.round(v * 1e7) / 1e7);
    }

    // ارقام فارسی/عربی و جداکننده اعشار فارسی (مشابه نرمال‌سازی بک‌اند)
    var FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
    var AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';

    function normalizeNumText(text) {
        var out = '';
        for (var i = 0; i < text.length; i++) {
            var ch = text[i];
            var fi = FA_DIGITS.indexOf(ch);
            if (fi !== -1) { out += fi; continue; }
            var ai = AR_DIGITS.indexOf(ch);
            if (ai !== -1) { out += ai; continue; }
            if (ch === '٫') { out += '.'; continue; }
            out += ch;
        }
        return out;
    }

    function parseNum(text) {
        if (text === null || text === undefined) return null;
        var t = normalizeNumText(String(text).trim()).replace('،', '.').replace(',', '.');
        if (t === '') return null;
        var v = Number(t);
        return isFinite(v) ? v : NaN;
    }

    function validLat(v) {
        return typeof v === 'number' && isFinite(v) && v >= -90 && v <= 90;
    }

    function validLng(v) {
        return typeof v === 'number' && isFinite(v) && v >= -180 && v <= 180;
    }

    function showMsg(el, text) {
        if (el) el.textContent = text || '';
    }

    function bindPicker(opts) {
        var modalEl = document.getElementById(opts.modalId);
        var mapEl = document.getElementById(opts.mapId);
        var latEl = document.getElementById(opts.latId);
        var lngEl = document.getElementById(opts.lngId);
        var geoEl = opts.geoId ? document.getElementById(opts.geoId) : null;
        var msgEl = opts.msgId ? document.getElementById(opts.msgId) : null;
        if (!modalEl || !mapEl || !latEl || !lngEl) return;

        var map = null;
        var marker = null;
        var initialized = false;

        function readInputs() {
            return { lat: parseNum(latEl.value), lng: parseNum(lngEl.value) };
        }

        function setMarker(lat, lng, pan) {
            if (!map) return;
            if (marker) {
                marker.setLatLng([lat, lng]);
            } else {
                marker = L.marker([lat, lng], { draggable: true }).addTo(map);
                marker.on('dragend', function () {
                    var p = marker.getLatLng();
                    latEl.value = fmt(p.lat);
                    lngEl.value = fmt(p.lng);
                    showMsg(msgEl, '');
                });
            }
            if (pan) map.setView([lat, lng], Math.max(map.getZoom(), SAVED_ZOOM));
        }

        function initMap() {
            if (initialized) return;
            if (typeof L === 'undefined') {
                showMsg(msgEl, 'خطا در بارگذاری نقشه. اتصال اینترنت را بررسی کنید.');
                return;
            }
            try {
                var coords = readInputs();
                var hasCoords = validLat(coords.lat) && validLng(coords.lng);
                map = L.map(mapEl, { scrollWheelZoom: false }).setView(
                    hasCoords ? [coords.lat, coords.lng] : [DEFAULT_LAT, DEFAULT_LNG],
                    hasCoords ? SAVED_ZOOM : DEFAULT_ZOOM
                );
                // با Ctrl + اسکرول امکان زوم دقیق وجود دارد
                map.on('focus', function () { map.scrollWheelZoom.enable(); });
                map.on('blur', function () { map.scrollWheelZoom.disable(); });
                L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    maxZoom: 19,
                    attribution: '© OpenStreetMap contributors'
                }).addTo(map);
                if (hasCoords) setMarker(coords.lat, coords.lng, false);
                map.on('click', function (e) {
                    setMarker(e.latlng.lat, e.latlng.lng, false);
                    latEl.value = fmt(e.latlng.lat);
                    lngEl.value = fmt(e.latlng.lng);
                    showMsg(msgEl, '');
                });
                initialized = true;
            } catch (err) {
                showMsg(msgEl, 'خطا در بارگذاری نقشه. لطفاً مختصات را دستی وارد کنید.');
            }
        }

        // مودال بوت‌استرپ در ابتدا مخفی است (ابعاد صفر)؛ پس از نمایش، ابعاد اصلاح می‌شود
        modalEl.addEventListener('shown.bs.modal', function () {
            initMap();
            if (map) {
                setTimeout(function () {
                    try { map.invalidateSize(); } catch (err) { /* نادیده */ }
                }, 100);
            }
        });

        // ویرایش دستی مختصات => جابه‌جایی نشانگر فقط در صورت معتبر بودن
        function onManualEdit() {
            var coords = readInputs();
            var latEmpty = String(latEl.value).trim() === '';
            var lngEmpty = String(lngEl.value) === '';
            if (latEmpty && lngEmpty) {
                if (marker && map) { map.removeLayer(marker); marker = null; }
                showMsg(msgEl, '');
                return;
            }
            if (latEmpty || lngEmpty) {
                showMsg(msgEl, 'برای ثبت موقعیت هر دو مقدار عرض و طول جغرافیایی لازم است.');
                return;
            }
            if (!validLat(coords.lat) || !validLng(coords.lng)) {
                showMsg(msgEl, 'مقدار مختصات نامعتبر است.');
                return;
            }
            showMsg(msgEl, '');
            if (map) setMarker(coords.lat, coords.lng, true);
            // اگر نقشه هنوز ساخته نشده (مودال باز نشده)، در initMap اعمال می‌شود
        }
        latEl.addEventListener('change', onManualEdit);
        lngEl.addEventListener('change', onManualEdit);

        // موقعیت فعلی فقط با کلیک صریح کاربر (Geolocation API مرورگر)
        if (geoEl) {
            geoEl.addEventListener('click', function () {
                if (!navigator.geolocation) {
                    showMsg(msgEl, 'موقعیت‌یابی در این مرورگر پشتیبانی نمی‌شود.');
                    return;
                }
                geoEl.disabled = true;
                navigator.geolocation.getCurrentPosition(
                    function (pos) {
                        geoEl.disabled = false;
                        var lat = pos.coords.latitude;
                        var lng = pos.coords.longitude;
                        latEl.value = fmt(lat);
                        lngEl.value = fmt(lng);
                        showMsg(msgEl, '');
                        if (map) setMarker(lat, lng, true);
                    },
                    function (err) {
                        geoEl.disabled = false;
                        if (err && err.code === 1) {
                            showMsg(msgEl, 'دسترسی به موقعیت مکانی رد شد.');
                        } else {
                            showMsg(msgEl, 'موقعیت مکانی در دسترس نیست. لطفاً دوباره تلاش کنید.');
                        }
                    },
                    { timeout: 10000 }
                );
            });
        }
    }

    return { bindPicker: bindPicker };
})();

/* همگام‌سازی متن شهر/استان با انتخاب شهر مرجع (بدون دست‌کاری مختصات)
 *
 * - انتخاب شهر => نام شهر و استان همگام می‌شوند (اقدام صریح کاربر)
 * - انتخاب گزینه خالی => متن‌های موجود دست نمی‌خورند
 */
function timexSyncCity(sel) {
    if (!sel) return;
    var opt = sel.options[sel.selectedIndex];
    if (!opt || !opt.value) return;
    var cityInput = document.getElementById(sel.getAttribute('data-city-target'));
    var provInput = document.getElementById(sel.getAttribute('data-province-target'));
    var name = opt.getAttribute('data-name');
    var province = opt.getAttribute('data-province');
    if (cityInput && name) cityInput.value = name;
    if (provInput && province) provInput.value = province;
}
