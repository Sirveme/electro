// electro - Toast notifications con presencia.
// API: window.electroToast(message, tipo='info', duracion=3500)
// tipo ∈ {success, error, warning, info}
//
// Diseño: centrados arriba, animados (slide-in + bounce), con icono SVG inline.
// Para confirmaciones (sí/no) seguir usando window.appModal.confirm.

(function () {
  'use strict';

  function ensureContainer() {
    var c = document.getElementById('electro-toasts');
    if (!c) {
      c = document.createElement('div');
      c.id = 'electro-toasts';
      c.className = 'toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Iconos SVG inline — mismos que templates/components/icons.html para
  // mantener consistencia visual entre server-render y client-render.
  var ICONOS = {
    success: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
    error:   '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    warning: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    info:    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16v-4M12 8h.01"/><circle cx="12" cy="12" r="10"/></svg>',
  };

  window.electroToast = function (message, tipo, duracion) {
    tipo = tipo || 'info';
    if (!ICONOS[tipo]) tipo = 'info';
    duracion = duracion || 3500;

    var c = ensureContainer();
    var toast = document.createElement('div');
    toast.className = 'toast toast--' + tipo;
    toast.setAttribute('role', tipo === 'error' ? 'alert' : 'status');
    toast.innerHTML =
      '<span class="toast-icon">' + ICONOS[tipo] + '</span>' +
      '<span class="toast-msg">' + escapeHtml(message) + '</span>';
    c.appendChild(toast);

    // Animar entrada en el siguiente frame para que el transition se vea.
    requestAnimationFrame(function () { toast.classList.add('toast--visible'); });

    // Auto-remover con animacion de salida.
    setTimeout(function () {
      toast.classList.remove('toast--visible');
      setTimeout(function () { toast.remove(); }, 300);
    }, duracion);

    return toast;
  };
})();
