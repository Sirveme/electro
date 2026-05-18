/*
 * window.geo.captureCurrent()
 * Retorna Promise<{lat, lng, accuracyMeters}>.
 * Lanza error con mensaje legible si falla o el usuario niega permiso.
 */
(function () {
  function captureCurrent() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) {
        reject(new Error('Tu dispositivo no soporta GPS o el navegador lo bloquea.'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracyMeters: Math.round(pos.coords.accuracy || 0),
          });
        },
        function (err) {
          var msg;
          switch (err.code) {
            case err.PERMISSION_DENIED: msg = 'Permiso de ubicación denegado.'; break;
            case err.POSITION_UNAVAILABLE: msg = 'No se pudo determinar la ubicación.'; break;
            case err.TIMEOUT: msg = 'Tiempo agotado esperando GPS.'; break;
            default: msg = err.message || 'Error desconocido capturando GPS.';
          }
          reject(new Error(msg));
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    });
  }

  window.geo = { captureCurrent: captureCurrent };
})();
