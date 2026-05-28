// electro - Motor de sincronizacion
// Procesa sync_queue secuencialmente. Reintenta items 'failed', marca
// 'conflict' los 409, y elimina los que el servidor acepta (200).

(function () {
  'use strict';

  const CSRF_COOKIE = '_csrf';
  const ENDPOINTS = {
    empadronar: '/app/api/empadronar-offline',
    // pago: '/app/api/registrar-pago-offline',  // se define en 03c
  };

  function getCSRFToken() {
    const m = document.cookie.match(/(?:^|;\s*)_csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function procesarItem(item) {
    const endpoint = ENDPOINTS[item.tipo];
    if (!endpoint) throw new Error('Tipo desconocido: ' + item.tipo);

    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': getCSRFToken(),
        'Accept': 'application/json',
      },
      credentials: 'same-origin',
      body: JSON.stringify(item.payload),
    });

    if (resp.status === 409) {
      const data = await resp.json().catch(() => ({}));
      return { status: 'conflict', data };
    }
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      return { status: 'ok', data };
    }
    // 4xx no-conflict o 5xx → throw para reintentar despues
    const txt = await resp.text().catch(() => 'unknown');
    throw new Error('HTTP ' + resp.status + ': ' + txt.slice(0, 200));
  }

  async function sincronizarTodo(onProgress) {
    await window.ElectroDB.open();
    const db = window.ElectroDB;
    const items = await db.getAll('sync_queue');
    const pendientes = items.filter(
      (i) => i.status === 'pending' || i.status === 'failed'
    );

    if (pendientes.length === 0) {
      return { total: 0, ok: 0, conflict: 0, failed: 0 };
    }

    let ok = 0, conflict = 0, failed = 0;
    for (let i = 0; i < pendientes.length; i++) {
      const item = pendientes[i];
      if (onProgress) {
        try { onProgress({ current: i + 1, total: pendientes.length, item }); }
        catch (e) { /* no romper la sincronizacion por un callback malo */ }
      }
      try {
        const result = await procesarItem(item);
        if (result.status === 'ok') {
          await db.delete('sync_queue', item.id);
          // Refrescar espejo en `viviendas` para que el padron muestre el codigo real.
          if (item.tipo === 'empadronar' && item.payload && item.payload.uuid_cliente) {
            try {
              const locales = await db.getAll('viviendas');
              for (const v of locales) {
                if (v.uuid_cliente === item.payload.uuid_cliente && v._offline) {
                  await db.delete('viviendas', v.codigo_interno);
                }
              }
            } catch (e) { /* ignorar limpieza de espejo */ }
          }
          ok++;
        } else if (result.status === 'conflict') {
          item.status = 'conflict';
          item.last_error = (result.data && result.data.message) || 'Conflicto';
          item.conflict_detail = (result.data && result.data.detalle) || {};
          await db.put('sync_queue', item);
          conflict++;
        }
      } catch (e) {
        item.status = 'failed';
        item.attempts = (item.attempts || 0) + 1;
        item.last_error = String(e && e.message ? e.message : e);
        await db.put('sync_queue', item);
        failed++;
      }
    }

    await db.put('meta', { key: 'last_sync', value: new Date().toISOString() });

    // Si hubo conflictos o fallos, ensamblar detalle para que el caller
    // pueda mostrarlo. Guardamos en el objeto retornado en `detalles[]` para
    // que tanto el handler de auto-sync como el boton "Sincronizar ahora"
    // puedan presentarlo (autoSync abajo dispara modal directamente).
    var detalles = [];
    if (conflict > 0 || failed > 0) {
      try {
        var current = await db.getAll('sync_queue');
        for (var i = 0; i < current.length; i++) {
          var it = current[i];
          if (it.status === 'conflict' || it.status === 'failed') {
            detalles.push({
              tipo: it.tipo,
              status: it.status,
              uuid: it.payload && it.payload.uuid_cliente
                ? it.payload.uuid_cliente.slice(0, 8) : null,
              error: it.last_error || 'error desconocido',
            });
          }
        }
      } catch (e) { /* sin detalle, no fatal */ }
    }
    return { total: pendientes.length, ok: ok, conflict: conflict, failed: failed, detalles: detalles };
  }

  // Helper: formatea el resumen + detalles como string multilinea para appModal.
  function _resumenTexto(result) {
    var lines = [
      'Procesados: ' + result.total,
      'OK: ' + result.ok,
      'Conflictos: ' + result.conflict,
      'Fallidos: ' + result.failed,
    ];
    if (result.detalles && result.detalles.length > 0) {
      lines.push('');
      lines.push('Detalles:');
      result.detalles.forEach(function (d) {
        var prefix = '• ' + d.tipo + ' [' + d.status + ']';
        if (d.uuid) prefix += ' uuid ' + d.uuid;
        lines.push(prefix + ': ' + d.error);
      });
      lines.push('');
      lines.push('Revisa /app/sync para mas detalle.');
    }
    return lines.join('\n');
  }

  // Re-poner items 'failed' como 'pending' para forzar otro intento.
  async function reintentarFallidos() {
    await window.ElectroDB.open();
    const db = window.ElectroDB;
    const items = await db.getAll('sync_queue');
    for (const it of items) {
      if (it.status === 'failed') {
        it.status = 'pending';
        await db.put('sync_queue', it);
      }
    }
  }

  window.electroSync = {
    sincronizar: sincronizarTodo,
    reintentarFallidos: reintentarFallidos,

    async autoSync() {
      const cm = window.ElectroConnectionMode;
      const mode = (cm && cm.get && cm.get()) || 'offline';
      if (mode === 'offline') return null;
      if (!navigator.onLine) return null;
      if (!window.ElectroDB) return null;

      const count = await window.ElectroDB.syncPendingCount();
      if (count === 0) return null;

      console.log('[SYNC] Auto-sync arrancando,', count, 'items pendientes');
      const result = await sincronizarTodo();
      console.log('[SYNC] Auto-sync resultado:', result);
      // En auto-sync, si hubo problemas, avisar al usuario.
      if ((result.conflict > 0 || result.failed > 0) && window.appModal) {
        window.appModal.alert(
          'Sincronizacion con problemas',
          _resumenTexto(result),
          { okText: 'Entendido' }
        ).catch(function () {});
      }
      return result;
    },
  };

  // Dispara auto-sync cuando vuelve la conexion (un poco demorado para que el
  // navegador termine de re-conectar y vuelva el CSRF cookie a estar fresco).
  window.addEventListener('online', () => {
    setTimeout(() => {
      window.electroSync.autoSync().catch(console.error);
    }, 2000);
  });

  // Tambien cuando el usuario cambia el modo a online/auto manualmente.
  window.addEventListener('electro:connection-mode-changed', (e) => {
    if (e.detail && e.detail.mode !== 'offline') {
      setTimeout(() => {
        window.electroSync.autoSync().catch(console.error);
      }, 1000);
    }
  });
})();
