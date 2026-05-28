// electro - Intercepta el submit de "Registrar pago" cuando el modo es offline.
// Encola el pago en sync_queue con tipo='pago' y avisa al usuario.
// Patron `onsubmit=` inline + hx-boost=false (mismo enfoque que el wizard).

(function () {
  'use strict';

  function isOfflineSubmit() {
    var cm = window.ElectroConnectionMode;
    if (!cm) return false;
    var mode = cm.get ? cm.get() : 'auto';
    if (mode === 'offline') return true;
    if (mode === 'online') return false;
    return !navigator.onLine;
  }

  function leerCodigoInterno(form) {
    var hidden = form.querySelector('input[name="codigo_interno"]');
    if (hidden && hidden.value) return hidden.value;
    // Fallback: extraer de la URL /app/cobranza/vivienda/V-NNNN o de action
    var fromAction = (form.getAttribute('action') || '').match(/vivienda\/([^/]+)\//);
    if (fromAction) return fromAction[1];
    var fromUrl = window.location.pathname.match(/vivienda\/([^/]+)/);
    return fromUrl ? fromUrl[1] : null;
  }

  window.manejarSubmitPago = function (event, form) {
    var mode = (window.ElectroConnectionMode && window.ElectroConnectionMode.get)
      ? window.ElectroConnectionMode.get() : 'auto';
    var offline = isOfflineSubmit();
    console.log('[PAGO] onsubmit interceptado. mode=', mode, 'offline=', offline);
    if (!offline) {
      console.log('[PAGO] Submit online normal');
      return true;
    }
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') {
      event.stopImmediatePropagation();
    }
    console.log('[PAGO] BLOQUEANDO submit al servidor (modo offline)');
    window.guardarPagoOffline(form).catch(function (err) {
      console.error('[PAGO] Error guardando offline:', err);
      window.appModal.alert(
        'Error',
        'No se pudo guardar el pago localmente: ' + (err.message || err)
      );
    });
    return false;
  };

  window.guardarPagoOffline = async function (form) {
    if (!window.ElectroDB) throw new Error('IndexedDB no disponible');
    if (!window.electroUUID) throw new Error('electroUUID no disponible');

    var fd = new FormData(form);
    var codigo = leerCodigoInterno(form);
    var cuotaId = fd.get('cuota_id');
    var monto = parseFloat((fd.get('monto') || '0').toString().replace(',', '.'));
    var metodo = (fd.get('metodo') || 'efectivo').toString().toLowerCase();

    if (!cuotaId) throw new Error('Falta cuota_id en el formulario');
    if (!monto || monto <= 0) throw new Error('Monto debe ser mayor a 0');

    var payload = {
      uuid_pago: window.electroUUID(),
      codigo_interno: codigo,
      cuota_ids: [parseInt(cuotaId, 10)],
      monto_total: monto,
      metodo_pago: metodo,
      referencia_externa: fd.get('referencia_externa') || null,
      observaciones: fd.get('observaciones') || null,
      capturado_at: new Date().toISOString(),
    };

    var item = {
      tipo: 'pago',
      payload: payload,
      status: 'pending',
      created_at: new Date().toISOString(),
      attempts: 0,
      last_error: null,
    };
    var id = await window.ElectroDB.put('sync_queue', item);
    console.log('[PAGO] Encolado id=', id, 'uuid=', payload.uuid_pago);

    await window.appModal.alert(
      'Pago guardado localmente',
      'El pago de S/. ' + monto.toFixed(2) + ' quedo en cola.\n\n' +
      'Se enviara al servidor cuando vuelvas a tener conexion.\n\n' +
      'IMPORTANTE: al sincronizar, el pago se asignara a la caja que tengas ' +
      'ABIERTA en ese momento, no a la actual.',
      { okText: 'Entendido' }
    );

    setTimeout(function () {
      window.location.href = codigo ? '/app/cobranza/vivienda/' + codigo : '/app/cobranza/buscar';
    }, 600);
  };
})();
