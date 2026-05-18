/*
 * electro — theme.js
 * Gestiona tema oscuro / atenuado con cookie de persistencia.
 * Aplica el tema ANTES de pintar para evitar flash.
 */
(function () {
  // Leer cookie _theme
  function getTheme() {
    const match = document.cookie.match(/(?:^|;\s*)_theme=([^;]+)/);
    return match ? match[1] : "oscuro";
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    // Cookie 1 año
    document.cookie = `_theme=${theme}; max-age=31536000; path=/; samesite=lax`;
  }

  // Aplicar inmediatamente (evita flash)
  setTheme(getTheme());

  window.electroTheme = {
    get: getTheme,
    set: setTheme,
    toggle: function () {
      const current = getTheme();
      const next = current === "oscuro" ? "atenuado" : "oscuro";
      setTheme(next);
      return next;
    },
  };
})();
