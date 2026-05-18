/*
 * Sistema de modales: window.appModal.{alert, confirm, prompt}.
 * Reemplaza a alert() / confirm() / prompt() nativos.
 *
 * Las funciones retornan Promise.
 */
(function () {
  function ensureHost() {
    var host = document.getElementById('app-modal-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'app-modal-host';
      document.body.appendChild(host);
    }
    return host;
  }

  function buildModal(html) {
    var host = ensureHost();
    var wrap = document.createElement('div');
    wrap.innerHTML = html;
    var modal = wrap.firstElementChild;
    host.appendChild(modal);
    return modal;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function wireUp(modal, resolve, opts) {
    function close(result) {
      document.removeEventListener('keydown', onKey);
      modal.remove();
      resolve(result);
    }
    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(opts.escapeResult);
      } else if (e.key === 'Enter' && opts.allowEnter) {
        var ok = modal.querySelector('[data-modal-ok]');
        if (ok) ok.click();
      }
    }

    modal.querySelectorAll('[data-modal-close]').forEach(function (el) {
      el.addEventListener('click', function () { close(opts.escapeResult); });
    });
    var okBtn = modal.querySelector('[data-modal-ok]');
    if (okBtn) {
      okBtn.addEventListener('click', function () {
        var val = opts.getValue ? opts.getValue(modal) : true;
        close(val);
      });
    }
    var cancelBtn = modal.querySelector('[data-modal-cancel]');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () { close(opts.cancelResult); });
    }

    document.addEventListener('keydown', onKey);

    setTimeout(function () {
      var input = modal.querySelector('[data-modal-input]');
      if (input) { input.focus(); input.select && input.select(); return; }
      if (okBtn) okBtn.focus();
    }, 30);
  }

  function alert(titulo, mensaje, options) {
    options = options || {};
    var html = ''
      + '<div class="app-modal app-modal--' + escapeHtml(options.tipo || 'info') + '" role="alertdialog" aria-modal="true">'
      +   '<div class="app-modal-backdrop" data-modal-close></div>'
      +   '<div class="app-modal-window" tabindex="-1">'
      +     '<header class="app-modal-header"><h2 class="app-modal-title">' + escapeHtml(titulo) + '</h2></header>'
      +     '<div class="app-modal-body">' + escapeHtml(mensaje) + '</div>'
      +     '<footer class="app-modal-footer">'
      +       '<button type="button" class="btn btn--primary" data-modal-ok>' + escapeHtml(options.okText || 'Entendido') + '</button>'
      +     '</footer>'
      +   '</div>'
      + '</div>';
    var modal = buildModal(html);
    return new Promise(function (resolve) {
      wireUp(modal, resolve, { allowEnter: true, escapeResult: undefined });
    });
  }

  function confirmDialog(titulo, mensaje, options) {
    options = options || {};
    var html = ''
      + '<div class="app-modal" role="alertdialog" aria-modal="true">'
      +   '<div class="app-modal-backdrop" data-modal-close></div>'
      +   '<div class="app-modal-window" tabindex="-1">'
      +     '<header class="app-modal-header"><h2 class="app-modal-title">' + escapeHtml(titulo) + '</h2></header>'
      +     '<div class="app-modal-body">' + escapeHtml(mensaje) + '</div>'
      +     '<footer class="app-modal-footer">'
      +       '<button type="button" class="btn btn--ghost" data-modal-cancel>' + escapeHtml(options.cancelText || 'No') + '</button>'
      +       '<button type="button" class="btn ' + (options.danger ? 'btn--danger' : 'btn--primary') + '" data-modal-ok>' + escapeHtml(options.okText || 'Sí') + '</button>'
      +     '</footer>'
      +   '</div>'
      + '</div>';
    var modal = buildModal(html);
    return new Promise(function (resolve) {
      wireUp(modal, resolve, {
        allowEnter: true,
        escapeResult: false,
        cancelResult: false,
        getValue: function () { return true; },
      });
    });
  }

  function prompt(titulo, label, options) {
    options = options || {};
    var html = ''
      + '<div class="app-modal" role="dialog" aria-modal="true">'
      +   '<div class="app-modal-backdrop" data-modal-close></div>'
      +   '<div class="app-modal-window" tabindex="-1">'
      +     '<header class="app-modal-header"><h2 class="app-modal-title">' + escapeHtml(titulo) + '</h2></header>'
      +     '<div class="app-modal-body">'
      +       '<label>' + escapeHtml(label)
      +         + '<input type="text" data-modal-input value="' + escapeHtml(options.defaultValue || '') + '">'
      +       '</label>'
      +     '</div>'
      +     '<footer class="app-modal-footer">'
      +       '<button type="button" class="btn btn--ghost" data-modal-cancel>' + escapeHtml(options.cancelText || 'Cancelar') + '</button>'
      +       '<button type="button" class="btn btn--primary" data-modal-ok>' + escapeHtml(options.okText || 'Aceptar') + '</button>'
      +     '</footer>'
      +   '</div>'
      + '</div>';
    var modal = buildModal(html);
    return new Promise(function (resolve) {
      wireUp(modal, resolve, {
        allowEnter: true,
        escapeResult: null,
        cancelResult: null,
        getValue: function (m) {
          var i = m.querySelector('[data-modal-input]');
          return i ? i.value : null;
        },
      });
    });
  }

  window.appModal = {
    alert: alert,
    confirm: confirmDialog,
    prompt: prompt,
  };
})();
