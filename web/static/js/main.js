// JavaScript اصلی Timex
document.addEventListener('DOMContentLoaded', function() {
    console.log('✅ Timex Web App Loaded');

    // Tooltip‌های Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // فرم‌های تأییدی
    const confirmForms = document.querySelectorAll('.confirm-submit');
    confirmForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!confirm('آیا مطمئن هستید؟')) {
                e.preventDefault();
            }
        });
    });
});