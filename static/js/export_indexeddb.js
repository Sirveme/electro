// electro - Export de datos pendientes a JSON descargable.
// Util para respaldo antes de cambiar/perder dispositivo. Incluye:
//   - sync_queue (items pendientes)
//   - viviendas locales (espejos V-LOCAL-*)
//   - meta (last_sync, local_counter, last_bootstrap, etc.)
// No exporta caches del bootstrap (comunidades/referentes/catalogo) — esos
// se rehidratan online apenas hay red.

(function () {
  'use strict';

  window.electroExportarPendientes = async function () {
    if (!window.ElectroDB) {
      await window.appModal.alert('Error', 'Base de datos local no disponible');
      return;
    }
    await window.ElectroDB.open();
    var db = window.ElectroDB;

    var data = {
      _version: '1.0',
      _exportado_at: new Date().toISOString(),
      _user_agent: navigator.userAgent.slice(0, 200),
      sync_queue: await db.getAll('sync_queue'),
      viviendas: await db.getAll('viviendas'),
      meta: await db.getAll('meta'),
    };

    var json = JSON.stringify(data, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var fecha = new Date().toISOString().slice(0, 10);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'electro-pendientes-' + fecha + '.json';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);

    await window.appModal.alert(
      'Datos exportados',
      'Se descargaron ' + data.sync_queue.length + ' items pendientes y ' +
      data.viviendas.length + ' viviendas locales.\n\n' +
      'Guarda el archivo en un lugar seguro. Si pierdes el dispositivo, ' +
      'puedes restaurar estos datos en otro celular.',
      { okText: 'Entendido' }
    );
  };
})();
