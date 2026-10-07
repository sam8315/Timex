/**
 * Progressive disclosure for employee-relative forms.
 * Clears hidden dependent fields so they are not submitted.
 */
(function () {
  function clearInputs(root) {
    root.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.type === 'checkbox' || el.type === 'radio') {
        el.checked = false;
      } else {
        el.value = '';
      }
    });
  }

  function setVisible(nodes, visible) {
    nodes.forEach(function (el) {
      el.classList.toggle('d-none', !visible);
      if (!visible) {
        clearInputs(el);
      }
    });
  }

  window.syncRelativeForm = function (root) {
    if (!root) return;
    var marital = root.querySelector('.relative-marital-status');
    var maritalVal = marital ? marital.value : '';
    setVisible(root.querySelectorAll('.relative-dep-marriage'), maritalVal === 'M' || maritalVal === 'D');
    setVisible(root.querySelectorAll('.relative-dep-divorce'), maritalVal === 'D');

    var deceased = root.querySelector('.relative-deceased-toggle');
    var isDeceased = deceased && deceased.checked;
    setVisible(root.querySelectorAll('.relative-dep-death'), !!isDeceased);

    var studying = root.querySelector('.relative-studying-select');
    var studyingVal = studying ? studying.value : '';
    setVisible(root.querySelectorAll('.relative-dep-study'), studyingVal === 'true');

    var disabled = root.querySelector('.relative-disabled-select');
    var disabledVal = disabled ? disabled.value : '';
    setVisible(root.querySelectorAll('.relative-dep-disability'), disabledVal === 'true');
  };

  function bindRoot(root) {
    if (!root || root.dataset.relativeFormBound === '1') return;
    root.dataset.relativeFormBound = '1';
    root.addEventListener('change', function (e) {
      if (
        e.target.matches(
          '.relative-marital-status, .relative-deceased-toggle, ' +
          '.relative-studying-select, .relative-disabled-select'
        )
      ) {
        window.syncRelativeForm(root);
      }
    });
    window.syncRelativeForm(root);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.relative-form-root').forEach(bindRoot);
  });

  document.addEventListener('show.bs.modal', function (e) {
    var roots = e.target.querySelectorAll('.relative-form-root');
    roots.forEach(function (root) {
      root.dataset.relativeFormBound = '';
      bindRoot(root);
    });
  });
})();
