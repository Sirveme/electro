/*
 * electro — Sesión de empadronamiento (zClaude-fix-19a)
 * El modal se inyecta bajo demanda desde /app/padron/sesion/modal.
 * Persistencia dual: server (request.session) + localStorage.
 */
(function () {
  'use strict';

  var LS_KEY = 'electro_sesion_empadronamiento';

  function _csrf() {
    // El token vive en la cookie _csrf (doble-submit). El input del modal ya lo
    // trae renderizado por el server, pero para fetch usamos el de cookie.
    var m = document.cookie.match(/(?:^|;\s*)_csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function _ensureModal() {
    if (document.getElementById('modal-sesion-empadronamiento')) return true;
    try {
      var resp = await fetch('/app/padron/sesion/modal', { credentials: 'same-origin' });
      if (!resp.ok) return false;
      var html = await resp.text();
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      document.body.appendChild(tmp.firstElementChild || tmp);
      return true;
    } catch (e) {
      console.warn('[SESION] No se pudo cargar el modal:', e);
      return false;
    }
  }

  window.abrirModalSesion = async function () {
    var ok = await _ensureModal();
    if (!ok) {
      window.appModal.alert('Sin conexión', 'No se pudo abrir el configurador de zona. Usa el padrón.');
      return;
    }
    var modal = document.getElementById('modal-sesion-empadronamiento');
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    setTimeout(function () {
      var c = document.getElementById('ses-comunidad');
      if (c) c.focus();
    }, 50);
  };

  window.cerrarModalSesion = function () {
    var modal = document.getElementById('modal-sesion-empadronamiento');
    if (modal) { modal.classList.add('hidden'); modal.setAttribute('aria-hidden', 'true'); }
  };

  window.actualizarReferenteSesion = function () {
    var sel = document.getElementById('ses-comunidad');
    var opt = sel && sel.options[sel.selectedIndex];
    var refId = opt ? (opt.getAttribute('data-referente-id') || '') : '';
    var refNombre = opt ? (opt.getAttribute('data-referente-nombre') || '') : '';
    document.getElementById('ses-referente-id').value = refId;
    document.getElementById('ses-referente-nombre').value = refNombre || '(Sin referente configurado)';
  };

  window.iniciarSesionEmpadronamiento = function (event) {
    event.preventDefault();
    var form = document.getElementById('form-iniciar-sesion');
    var fd = new FormData(form);
    if (!fd.get('_csrf')) fd.append('_csrf', _csrf());
    if (!fd.get('comunidad_id')) {
      window.appModal.alert('Atención', 'Selecciona una comunidad.');
      return false;
    }
    var sel = document.getElementById('ses-comunidad');
    var comNombre = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text.trim() : '';

    fetch('/app/padron/sesion/iniciar', { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          try {
            localStorage.setItem(LS_KEY, JSON.stringify({
              comunidad_id: fd.get('comunidad_id'),
              comunidad_nombre: comNombre,
              referente_id: fd.get('referente_id') || null,
              referente_nombre: document.getElementById('ses-referente-nombre').value,
              fuente_validacion: fd.get('fuente_validacion'),
              iniciada_at: new Date().toISOString(),
            }));
          } catch (e) { /* localStorage lleno o bloqueado: no crítico */ }
          window.location.href = data.redirect || '/app/padron/nuevo/paso1';
        } else {
          window.appModal.alert('Error', (data && data.message) || 'No se pudo iniciar la sesión.');
        }
      })
      .catch(function () {
        window.appModal.alert('Sin conexión', 'No se pudo iniciar la sesión. Intenta de nuevo.');
      });
    return false;
  };

  window.cambiarZonaEmpadronamiento = async function () {
    var ok = await window.appModal.confirm(
      'Cambiar zona',
      '¿Cambiar la zona de empadronamiento? Configurarás una nueva.',
      { okText: 'Sí, cambiar', cancelText: 'Cancelar' }
    );
    if (ok !== true) return;
    try {
      var fd = new FormData(); fd.append('_csrf', _csrf());
      await fetch('/app/padron/sesion/cambiar', { method: 'POST', body: fd, credentials: 'same-origin' });
    } catch (e) { /* best-effort */ }
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
    window.abrirModalSesion();
  };

  // Entrada desde el topbar "Empadronar": si hay sesión activa → wizard; si no → modal.
  window.iniciarEmpadronar = function () {
    fetch('/app/padron/sesion/info', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (sesion) {
        if (sesion && sesion.comunidad_id) {
          window.location.href = '/app/padron/nuevo';
        } else {
          window.abrirModalSesion();
        }
      })
      .catch(function () { window.abrirModalSesion(); });
  };

  // Restaurar sesión server desde localStorage si la PWA se reabrió y el server la perdió.
  window.addEventListener('DOMContentLoaded', function () {
    var local;
    try { local = localStorage.getItem(LS_KEY); } catch (e) { local = null; }
    if (!local) return;
    fetch('/app/padron/sesion/info', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (server) {
        if (server && server.comunidad_id) return; // server ya la tiene
        var data = JSON.parse(local);
        if (!data || !data.comunidad_id) return;
        var fd = new FormData();
        fd.append('comunidad_id', data.comunidad_id);
        if (data.referente_id) fd.append('referente_id', data.referente_id);
        fd.append('fuente_validacion', data.fuente_validacion || '');
        fd.append('_csrf', _csrf());
        return fetch('/app/padron/sesion/iniciar', { method: 'POST', body: fd, credentials: 'same-origin' });
      })
      .catch(function (e) { console.warn('[SESION] No se pudo restaurar:', e); });
  });
})();
