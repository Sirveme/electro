// electro - Gestion del modo de conexion
// 3 estados: 'auto' | 'online' | 'offline'
// Default: 'offline'

(function () {
  'use strict';

  const KEY = 'electro_connection_mode';
  const DEFAULT_MODE = 'offline';

  const ConnectionMode = {
    get() {
      return localStorage.getItem(KEY) || DEFAULT_MODE;
    },

    set(mode) {
      if (!['auto', 'online', 'offline'].includes(mode)) {
        console.warn('Invalid connection mode:', mode);
        return;
      }
      localStorage.setItem(KEY, mode);
      this.updateUI();
      window.dispatchEvent(
        new CustomEvent('electro:connection-mode-changed', { detail: { mode } })
      );
    },

    isEffectivelyOnline() {
      const mode = this.get();
      if (mode === 'offline') return false;
      if (mode === 'online') return true;
      // auto
      return navigator.onLine;
    },

    updateUI() {
      const mode = this.get();
      const indicator = document.getElementById('connection-indicator');
      if (!indicator) return;

      const isOnline = this.isEffectivelyOnline();
      indicator.classList.remove('mode-auto', 'mode-online', 'mode-offline');
      indicator.classList.add('mode-' + mode);
      indicator.classList.toggle('is-online', isOnline);
      indicator.classList.toggle('is-offline', !isOnline);

      const labelEl = indicator.querySelector('.connection-label');
      if (labelEl) {
        labelEl.textContent = ({
          'auto': 'Auto',
          'online': 'En linea',
          'offline': 'Sin conexion',
        })[mode] || mode;
      }
    },

    showModal() {
      const current = this.get();
      const html = `
        <div class="modal-overlay modal-mode-conexion" id="modal-modo-conexion">
          <div class="modal-card">
            <h2>Modo de conexion</h2>
            <p>Elige como debe comportarse la app con respecto a Internet.</p>
            <div class="mode-options">
              <button class="mode-option ${current === 'auto' ? 'selected' : ''}"
                      data-mode="auto" type="button">
                <strong>Auto</strong>
                <small>Usa conexion cuando esta disponible</small>
              </button>
              <button class="mode-option ${current === 'online' ? 'selected' : ''}"
                      data-mode="online" type="button">
                <strong>Forzar en linea</strong>
                <small>Siempre intentar conectarse al servidor</small>
              </button>
              <button class="mode-option ${current === 'offline' ? 'selected' : ''}"
                      data-mode="offline" type="button">
                <strong>Forzar sin conexion</strong>
                <small>Trabajar solo localmente, sin red</small>
              </button>
            </div>
            <div class="modal-actions">
              <button class="btn btn--ghost" data-action="close" type="button">Cerrar</button>
            </div>
          </div>
        </div>
      `;
      const container = document.createElement('div');
      container.innerHTML = html;
      document.body.appendChild(container.firstElementChild);

      const modal = document.getElementById('modal-modo-conexion');
      modal.addEventListener('click', (e) => {
        // Buscar el ancestro mode-option mas cercano (puede haberse clickeado un hijo)
        const opt = e.target.closest('.mode-option');
        if (opt && opt.dataset.mode) {
          this.set(opt.dataset.mode);
          modal.remove();
          return;
        }
        if (e.target.dataset.action === 'close' || e.target === modal) {
          modal.remove();
        }
      });
    },

    init() {
      this.updateUI();
      // Auto-update cuando cambia navigator.onLine
      window.addEventListener('online', () => this.updateUI());
      window.addEventListener('offline', () => this.updateUI());
    },
  };

  window.ElectroConnectionMode = ConnectionMode;

  // Init al cargar DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ConnectionMode.init());
  } else {
    ConnectionMode.init();
  }
})();
