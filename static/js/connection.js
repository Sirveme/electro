/*
 * electro — connection.js
 * Indicador discreto de estado de conexión.
 * Usa navigator.onLine + ping ligero a /healthz cada 30s.
 */
(function () {
  const dot = document.querySelector(".conn-dot");
  const label = document.querySelector(".conn-label");
  if (!dot) return;

  function setState(state, text) {
    dot.classList.remove("lenta", "offline");
    if (state === "lenta") dot.classList.add("lenta");
    if (state === "offline") dot.classList.add("offline");
    if (label) label.textContent = text;
  }

  async function ping() {
    if (!navigator.onLine) {
      setState("offline", "sin conexión");
      return;
    }
    try {
      const t0 = performance.now();
      const r = await fetch("/healthz", {
        method: "GET",
        cache: "no-store",
        signal: AbortSignal.timeout(5000),
      });
      const dt = performance.now() - t0;
      if (!r.ok) {
        setState("lenta", "lenta");
      } else if (dt > 1500) {
        setState("lenta", "lenta");
      } else {
        setState("ok", "");
      }
    } catch (e) {
      setState("offline", "sin conexión");
    }
  }

  window.addEventListener("online", ping);
  window.addEventListener("offline", () => setState("offline", "sin conexión"));

  ping();
  setInterval(ping, 30000);
})();
