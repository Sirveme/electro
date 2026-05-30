/*
 * electro — Persistencia dual del wizard (zClaude-fix-19a).
 * El server ya guarda el estado en request.session y los templates prellenan.
 * Esto es un respaldo en localStorage para recargas duras / PWA reabierta:
 * solo rellena inputs VACÍOS (no pisa lo que el server ya prellenó).
 */
(function () {
  'use strict';

  var KEY = 'electro_wizard_' + location.pathname;
  var PREFIX = 'electro_wizard_';

  window.limpiarLocalStorageWizard = function () {
    try {
      var quitar = [];
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (k && k.indexOf(PREFIX) === 0) quitar.push(k);
      }
      quitar.forEach(function (k) { localStorage.removeItem(k); });
    } catch (e) { /* no crítico */ }
  };

  function _form() {
    return document.querySelector('form[action^="/app/padron/nuevo/paso"]');
  }

  document.addEventListener('DOMContentLoaded', function () {
    var form = _form();
    if (!form) return;

    // Restaurar (solo inputs vacíos).
    try {
      var saved = localStorage.getItem(KEY);
      if (saved) {
        var data = JSON.parse(saved);
        Object.keys(data).forEach(function (name) {
          var el = form.querySelector('[name="' + name + '"]');
          if (el && (el.type === 'checkbox' ? false : !el.value)) {
            el.value = data[name];
          }
        });
      }
    } catch (e) { console.warn('[WIZARD-LS] restore:', e); }

    // Auto-guardar al cambiar.
    form.addEventListener('change', function () {
      try {
        var obj = {};
        var fd = new FormData(form);
        fd.forEach(function (v, k) {
          if (k === '_csrf' || k === 'foto_fachada' || k === 'inventario_json') return;
          obj[k] = v;
        });
        localStorage.setItem(KEY, JSON.stringify(obj));
      } catch (e) { /* localStorage lleno: ignorar */ }
    });
  });
})();
