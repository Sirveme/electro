// electro - PWA Install button
// Captura el evento beforeinstallprompt y lo dispara al click.
// Si el browser no lo soporta, muestra modal de instrucciones por SO.

(function () {
  'use strict';

  let deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
  });

  window.electroInstallPWA = async function () {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      deferredPrompt = null;
      return outcome;
    }
    // Browser no soporta o ya instalada o esta en standalone
    window.electroShowInstallInstructions();
    return 'unavailable';
  };

  window.electroShowInstallInstructions = function () {
    const ua = navigator.userAgent.toLowerCase();
    let instrucciones = '';

    if (/iphone|ipad|ipod/.test(ua)) {
      instrucciones = `
        <p>En iPhone/iPad (Safari):</p>
        <ol>
          <li>Toca el boton compartir (cuadrado con flecha arriba)</li>
          <li>Desplazate y elige "Agregar a pantalla de inicio"</li>
          <li>Toca "Agregar"</li>
        </ol>
      `;
    } else if (/android/.test(ua)) {
      instrucciones = `
        <p>En Android (Chrome):</p>
        <ol>
          <li>Toca el menu (3 puntos arriba a la derecha)</li>
          <li>Elige "Instalar aplicacion" o "Agregar a pantalla principal"</li>
          <li>Confirma</li>
        </ol>
      `;
    } else {
      instrucciones = `
        <p>En computadora (Chrome / Edge):</p>
        <ol>
          <li>Mira en la barra de direcciones, lado derecho</li>
          <li>Busca un icono pequeno de instalar (monitor con flecha)</li>
          <li>Toca y confirma instalacion</li>
        </ol>
      `;
    }

    const html = `
      <div class="modal-overlay modal-install" id="modal-install">
        <div class="modal-card">
          <h2>Instalar electro</h2>
          ${instrucciones}
          <p class="muted small">La app se vera como una aplicacion nativa, con su propio icono en tu pantalla.</p>
          <div class="modal-actions">
            <button class="btn btn--primary" data-action="close" type="button">Entendido</button>
          </div>
        </div>
      </div>
    `;
    const container = document.createElement('div');
    container.innerHTML = html;
    document.body.appendChild(container.firstElementChild);

    const modal = document.getElementById('modal-install');
    modal.addEventListener('click', (e) => {
      if (e.target.dataset.action === 'close' || e.target === modal) {
        modal.remove();
      }
    });
  };
})();
