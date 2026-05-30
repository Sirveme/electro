/*
 * electro — Topbar Cobrar: buscador rápido de morador (zClaude-fix-19a).
 * iniciarEmpadronar() vive en sesion_empadronamiento.js.
 */
(function () {
  'use strict';

  window.toggleBuscarCobrar = function () {
    var d = document.getElementById('dropdown-cobrar');
    if (!d) return;
    d.classList.toggle('hidden');
    if (!d.classList.contains('hidden')) {
      setTimeout(function () {
        var inp = document.getElementById('buscar-cobrar-input');
        if (inp) inp.focus();
      }, 50);
    }
  };

  var _debounce = null;
  window.buscarMoradorRapido = function (q) {
    clearTimeout(_debounce);
    var cont = document.getElementById('buscar-cobrar-resultados');
    if (!cont) return;
    q = (q || '').trim();
    if (q.length < 3) { cont.innerHTML = ''; return; }
    _debounce = setTimeout(function () {
      fetch('/app/padron/buscar-morador?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var res = (data && data.resultados) || [];
          if (!res.length) {
            cont.innerHTML = '<div class="dropdown-empty">Sin resultados</div>';
            return;
          }
          cont.textContent = '';
          res.forEach(function (r) {
            var a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = '/app/cobranza/?q=' + encodeURIComponent(r.codigo || '');
            var s = document.createElement('strong'); s.textContent = r.codigo || '';
            var n = document.createElement('span'); n.textContent = r.nombre || 'Sin jefe';
            var d = document.createElement('small'); d.textContent = r.dni || '';
            a.appendChild(s); a.appendChild(n); a.appendChild(d);
            cont.appendChild(a);
          });
        })
        .catch(function (e) { console.warn('[BUSCAR] error:', e); });
    }, 300);
  };

  // Cerrar el dropdown al hacer click fuera.
  document.addEventListener('click', function (e) {
    var cont = document.querySelector('.topbar-cobrar');
    var d = document.getElementById('dropdown-cobrar');
    if (cont && d && !cont.contains(e.target)) d.classList.add('hidden');
  });
})();
