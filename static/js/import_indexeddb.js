// electro - Import de datos pendientes desde un JSON exportado.
// El sync_queue se restaura SIN su id viejo (autoIncrement asigna nuevo id),
// para no chocar con items locales. viviendas y meta se restauran tal cual.

(function () {
  'use strict';

  window.electroImportarPendientes = async function (fileInput) {
    if (!fileInput || !fileInput.files || !fileInput.files[0]) return;
    var file = fileInput.files[0];

    var data;
    try {
      var text = await file.text();
      data = JSON.parse(text);
    } catch (e) {
      await window.appModal.alert('Error', 'Archivo invalido: ' + (e.message || e));
      return;
    }
    if (!data || !data._version || !data.sync_queue) {
      await window.appModal.alert(
        'Error',
        'El archivo no parece ser un export de electro.'
      );
      return;
    }

    var nSync = (data.sync_queue && data.sync_queue.length) || 0;
    var nViv = (data.viviendas && data.viviendas.length) || 0;
    var fechaExp = data._exportado_at || 'fecha desconocida';

    var ok = await window.appModal.confirm(
      'Importar datos pendientes',
      'Se importaran ' + nSync + ' items pendientes y ' + nViv +
      ' viviendas locales del archivo exportado el ' + fechaExp + '.\n\n' +
      'IMPORTANTE: los items se SUMAN a los actuales (no se borra nada). ' +
      '¿Continuar?',
      { okText: 'Si, importar', cancelText: 'Cancelar' }
    );
    if (ok !== true) return;

    await window.ElectroDB.open();
    var db = window.ElectroDB;
    var importados = 0;

    try {
      for (var i = 0; i < (data.sync_queue || []).length; i++) {
        var item = data.sync_queue[i];
        var copia = Object.assign({}, item);
        delete copia.id; // dejar que autoIncrement asigne uno nuevo
        await db.put('sync_queue', copia);
        importados++;
      }
      for (var k = 0; k < (data.viviendas || []).length; k++) {
        await db.put('viviendas', data.viviendas[k]);
        importados++;
      }
      for (var m = 0; m < (data.meta || []).length; m++) {
        await db.put('meta', data.meta[m]);
      }

      await window.appModal.alert(
        'Importacion completada',
        'Se importaron ' + importados + ' registros. Recargando pagina...',
        { okText: 'Recargar' }
      );
      window.location.reload();
    } catch (e) {
      await window.appModal.alert('Error', 'Error al importar: ' + (e.message || e));
    }
  };
})();
