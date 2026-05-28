// electro - Version check
// Compara la version del cliente (meta name="app-version") con la del servidor
// (/app/api/version-check). Muestra banner sugerido o critico segun severidad.
// Estado expuesto en window._electroVersionEstado para que sync_engine.js
// bloquee la sincronizacion cuando es obligatorio.

(function () {
  'use strict';

  function getClienteVersion() {
    var meta = document.querySelector('meta[name="app-version"]');
    return meta ? meta.getAttribute('content') : '0.0.0';
  }

  // Comparacion semver simple — soporta x.y.z; partes faltantes = 0.
  function compararVersiones(a, b) {
    var pa = String(a).split('.').map(function (n) { return parseInt(n, 10) || 0; });
    var pb = String(b).split('.').map(function (n) { return parseInt(n, 10) || 0; });
    var len = Math.max(pa.length, pb.length);
    for (var i = 0; i < len; i++) {
      var diff = (pa[i] || 0) - (pb[i] || 0);
      if (diff !== 0) return diff;
    }
    return 0;
  }

  async function checkVersion(opts) {
    opts = opts || {};
    if (!navigator.onLine && !opts.force) {
      console.log('[VERSION] Sin red, skip');
      return null;
    }
    try {
      var resp = await fetch('/app/api/version-check', { credentials: 'same-origin' });
      if (!resp.ok) {
        console.warn('[VERSION] check fallo', resp.status);
        return null;
      }
      var data = await resp.json();
      var cliente = getClienteVersion();
      var servidor = data.version_servidor;
      var minima = data.version_minima_compatible;

      var estado = {
        cliente: cliente,
        servidor: servidor,
        minima: minima,
        hayActualizacion: compararVersiones(cliente, servidor) < 0,
        actualizacionObligatoria: compararVersiones(cliente, minima) < 0,
        changelog: data.changelog || [],
      };
      window._electroVersionEstado = estado;
      console.log('[VERSION]', estado);

      if (estado.actualizacionObligatoria) {
        mostrarBannerObligatorio(estado);
      } else if (estado.hayActualizacion) {
        mostrarBannerSugerido(estado);
      } else {
        ocultarBanner();
      }
      return estado;
    } catch (e) {
      console.warn('[VERSION] check error:', e);
      return null;
    }
  }

  function ocultarBanner() {
    var b = document.getElementById('update-banner');
    if (b) b.remove();
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function mostrarBannerSugerido(estado) {
    ocultarBanner();
    var div = document.createElement('div');
    div.id = 'update-banner';
    div.className = 'update-banner update-banner--info';
    div.innerHTML =
      '<span>Hay una nueva version disponible (' + escapeHtml(estado.servidor) + ').</span>' +
      '<button class="btn btn--sm btn--primary" type="button"' +
      ' onclick="window.electroAplicarActualizacion()">Actualizar ahora</button>' +
      '<button class="btn btn--sm btn--ghost" type="button"' +
      ' onclick="document.getElementById(\'update-banner\').remove()">Mas tarde</button>';
    document.body.insertBefore(div, document.body.firstChild);
  }

  function mostrarBannerObligatorio(estado) {
    ocultarBanner();
    var div = document.createElement('div');
    div.id = 'update-banner';
    div.className = 'update-banner update-banner--critical';
    div.innerHTML =
      '<strong>Actualizacion obligatoria.</strong> ' +
      '<span>Tu version (' + escapeHtml(estado.cliente) + ') es muy antigua. ' +
      'Sincronizacion bloqueada hasta actualizar a ' + escapeHtml(estado.servidor) + '.</span>' +
      '<button class="btn btn--sm btn--danger" type="button"' +
      ' onclick="window.electroAplicarActualizacion()">Actualizar ahora</button>';
    document.body.insertBefore(div, document.body.firstChild);
  }

  window.electroAplicarActualizacion = async function () {
    var estado = window._electroVersionEstado;
    if (estado && estado.changelog && estado.changelog.length > 0) {
      var notas = estado.changelog.map(function (v) {
        return 'v' + escapeHtml(v.version) + ' ' + escapeHtml(v.fecha) + '\n' +
          (v.notas || []).join('\n');
      }).join('\n\n');

      var ok = await window.appModal.confirm(
        'Novedades de la version ' + estado.servidor,
        notas,
        { okText: 'Actualizar ahora', cancelText: 'Cancelar' }
      );
      if (ok !== true) return;
    }

    // Forzar update del SW (skipWaiting) + limpiar caches HTTP + reload
    if ('serviceWorker' in navigator) {
      try {
        var regs = await navigator.serviceWorker.getRegistrations();
        for (var i = 0; i < regs.length; i++) {
          var reg = regs[i];
          await reg.update();
          if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
      } catch (e) { console.warn('[VERSION] SW update fallo', e); }
    }
    if ('caches' in window) {
      try {
        var names = await caches.keys();
        for (var k = 0; k < names.length; k++) await caches.delete(names[k]);
      } catch (e) { console.warn('[VERSION] caches.delete fallo', e); }
    }
    window.location.reload();
  };

  window.electroVersionCheck = checkVersion;

  // Auto-check al cargar + cada vez que vuelve online
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { checkVersion(); });
  } else {
    setTimeout(function () { checkVersion(); }, 1000);
  }
  window.addEventListener('online', function () {
    setTimeout(function () { checkVersion(); }, 2000);
  });
})();
