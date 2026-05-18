/*
 * electro — kebab_close.js
 * Cierra cualquier kebab-menu abierto al hacer click fuera de su contenedor.
 */
(function () {
  document.addEventListener("click", function (e) {
    document.querySelectorAll(".kebab-menu.open").forEach((menu) => {
      if (!menu.parentElement.contains(e.target)) {
        menu.classList.remove("open");
      }
    });
  });
})();