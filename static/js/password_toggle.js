/*
 * electro — password_toggle.js
 * Convierte automáticamente cualquier <input type="password"> dentro de
 * un <div class="password-wrap"> en uno con botón ojo para mostrar/ocultar.
 */
(function () {
  const EYE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
  const EYE_OFF = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

  function init() {
    document.querySelectorAll(".password-wrap").forEach((wrap) => {
      if (wrap.dataset.eyeInit) return;
      wrap.dataset.eyeInit = "1";

      const input = wrap.querySelector('input[type="password"]');
      if (!input) return;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "password-toggle";
      btn.setAttribute("aria-label", "Mostrar contraseña");
      btn.innerHTML = EYE;

      btn.addEventListener("click", () => {
        if (input.type === "password") {
          input.type = "text";
          btn.innerHTML = EYE_OFF;
          btn.setAttribute("aria-label", "Ocultar contraseña");
        } else {
          input.type = "password";
          btn.innerHTML = EYE;
          btn.setAttribute("aria-label", "Mostrar contraseña");
        }
      });

      wrap.appendChild(btn);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", init);
})();
