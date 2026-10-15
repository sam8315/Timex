(function () {
    const MM = 96 / 25.4;
    // A4 با حاشیهٔ ۸ میلی‌متری = ۲۸۱ میلی‌متر؛ کمی کمتر برای گردکردن مرورگر
    const PRINTABLE_HEIGHT = 276 * MM;

    function targetBox() {
        const boxes = Array.from(document.querySelectorAll('.payslip-box'));
        if (document.body.classList.contains('payslip-printing')) {
            return boxes.find((box) => box.closest('#payslipModal')) || null;
        }
        return boxes.find((box) => !box.closest('.modal')) || null;
    }

    // بعضی مرورگرها ارتفاع عنصر zoom‌شده را بدون اعمال zoom گزارش می‌کنند
    function visualHeight(box, zoom, plainHeight) {
        const measured = box.getBoundingClientRect().height;
        const reportsPlain = Math.abs(measured - plainHeight) < Math.abs(measured - plainHeight * zoom);
        return reportsPlain ? measured * zoom : measured;
    }

    function prepare() {
        const box = targetBox();
        if (!box) return;
        document.body.classList.add('payslip-print-mode');
        box.style.zoom = '';
        const plainHeight = box.getBoundingClientRect().height;
        let zoom = 1;
        let height = plainHeight;
        for (let step = 0; step < 4 && height > PRINTABLE_HEIGHT; step++) {
            zoom = Math.floor(zoom * (PRINTABLE_HEIGHT / height) * 1000) / 1000;
            box.style.zoom = String(zoom);
            height = visualHeight(box, zoom, plainHeight);
        }
    }

    function reset() {
        document.body.classList.remove('payslip-print-mode');
        document.querySelectorAll('.payslip-box').forEach((box) => {
            box.style.zoom = '';
        });
    }

    window.addEventListener('beforeprint', prepare);
    window.addEventListener('afterprint', reset);
})();
