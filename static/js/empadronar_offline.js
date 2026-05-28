// electro - Empadronamiento offline
// Helpers que usa el wizard paso4 cuando el modo de conexion es offline:
//   - electroBootstrap(): refresca cache local desde /app/api/bootstrap
//   - electroUUID(): genera UUID v4
//   - electroEncolarEmpadronamiento(payload): guarda en sync_queue + cache local
//   - electroFileToBase64(fileOrBlob): util para fotos

(function () {
  'use strict';

  // Espera lazy a IndexedDB (se abre en indexeddb.js, puede tardar 1-2 ticks).
  function ready() {
    return window.ElectroDB
      ? Promise.resolve()
      : new Promise((r) => {
          const i = setInterval(() => {
            if (window.ElectroDB) {
              clearInterval(i);
              r();
            }
          }, 50);
        });
  }

  // === UUID v4 ===
  // Implementacion compatible sin depender de crypto.randomUUID (que no esta en
  // algunos browsers viejos del Android). Usa crypto.getRandomValues para tener
  // entropia real.
  function uuidv4() {
    if (crypto && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'));
    return (
      hex.slice(0, 4).join('') + '-' +
      hex.slice(4, 6).join('') + '-' +
      hex.slice(6, 8).join('') + '-' +
      hex.slice(8, 10).join('') + '-' +
      hex.slice(10, 16).join('')
    );
  }
  window.electroUUID = uuidv4;

  // === File → base64 ===
  // Retorna SOLO el payload base64 (sin el prefijo data:...).
  window.electroFileToBase64 = function (fileOrBlob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const result = e.target.result || '';
        const comma = result.indexOf(',');
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.onerror = (err) => reject(err);
      reader.readAsDataURL(fileOrBlob);
    });
  };

  // === Bootstrap: refresca cache local desde el servidor ===
  async function bootstrap() {
    try {
      const resp = await fetch('/app/api/bootstrap', { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('bootstrap status ' + resp.status);
      const data = await resp.json();
      await ready();
      const db = window.ElectroDB;

      for (const c of data.comunidades || []) await db.put('comunidades', c);
      for (const r of data.referentes || []) await db.put('referentes', r);
      for (const s of data.subsidios || []) await db.put('subsidios', s);
      for (const a of data.catalogo || []) {
        // El store usa keyPath='id'; aseguramos id estable origen:codigo.
        const item = { ...a, id: (a.origen || 'x') + ':' + (a.codigo || a.id) };
        await db.put('catalogo_artefactos', item);
      }
      await db.put('meta', { key: 'last_bootstrap', value: data.sync_at });
      // Config como entrada agregada (compatibilidad) + una entrada por clave
      // para lookups individuales (`config:cargo_fijo_mensual`, etc.).
      if (data.config) {
        await db.put('meta', { key: 'config_municipio', value: data.config });
        for (const [clave, valor] of Object.entries(data.config)) {
          await db.put('meta', { key: 'config:' + clave, value: valor });
        }
      }
      if (data.user) {
        await db.put('meta', { key: 'user_info', value: data.user });
      }
      // Reportar errores parciales del servidor (alguna seccion del bootstrap
      // pudo fallar sin abortar las demas).
      if (data.errors && data.errors.length > 0) {
        console.warn('[OFFLINE] Bootstrap con errores parciales:', data.errors);
      }
      console.log('[OFFLINE] Bootstrap OK',
        (data.comunidades || []).length, 'comunidades,',
        (data.catalogo || []).length, 'artefactos');
      return true;
    } catch (e) {
      console.warn('[OFFLINE] Bootstrap fallo:', e);
      return false;
    }
  }
  window.electroBootstrap = bootstrap;

  // Contador local persistente: V-LOCAL-001, V-LOCAL-002, ...
  // El contador NO se decrementa al sincronizar (evita colisiones si el usuario
  // empadrona V-LOCAL-002 antes de que V-LOCAL-001 termine de sincronizar).
  async function siguienteContadorLocal() {
    var meta = await window.ElectroDB.get('meta', 'local_counter');
    var next = ((meta && meta.value) || 0) + 1;
    await window.ElectroDB.put('meta', { key: 'local_counter', value: next });
    return next;
  }

  // === Encolar empadronamiento offline ===
  async function encolarEmpadronamiento(payload) {
    await ready();
    const db = window.ElectroDB;
    payload.uuid_cliente = payload.uuid_cliente || uuidv4();

    const item = {
      tipo: 'empadronar',
      payload: payload,
      status: 'pending',
      created_at: new Date().toISOString(),
      attempts: 0,
      last_error: null,
    };
    const id = await db.put('sync_queue', item);

    var contador = await siguienteContadorLocal();
    var codigoLocal = 'V-LOCAL-' + String(contador).padStart(3, '0');

    // Espejo en `viviendas` para que el padron muestre la vivienda offline.
    await db.put('viviendas', {
      codigo_interno: codigoLocal,
      uuid_cliente: payload.uuid_cliente,
      comunidad_id: payload.comunidad_id,
      referencia_fisica: payload.referencia_fisica,
      gps_lat: payload.gps_lat,
      gps_lng: payload.gps_lng,
      updated_at: new Date().toISOString(),
      _offline: true,
      _sync_id: id,
    });

    console.log('[OFFLINE] Empadronamiento encolado id=', id,
      'codigo=', codigoLocal, 'uuid=', payload.uuid_cliente);
    return { id: id, uuid_cliente: payload.uuid_cliente, codigo_local: codigoLocal };
  }
  window.electroEncolarEmpadronamiento = encolarEmpadronamiento;

  // === Helper global: cancelar empadronamiento (botones Cancelar del wizard) ===
  window.cancelarEmpadronamiento = async function () {
    var ok = await window.appModal.confirm(
      'Cancelar empadronamiento',
      'Se perderan los datos ingresados. ¿Continuar?',
      { danger: true, okText: 'Si, descartar', cancelText: 'Volver' }
    );
    if (ok === true) window.location.href = '/app/padron/';
  };

  // Bootstrap auto-init — INDEPENDIENTE del DOM.
  // Razon: si hyperscript falla al parsear, DOMContentLoaded puede haberse
  // disparado antes de que este script enganche y nunca se hidrata IndexedDB.
  // Tambien: corremos el bootstrap SIEMPRE que haya red, sin importar el modo
  // del usuario — "Forzar offline" intercepta el SUBMIT, no debe impedir que
  // se descarguen comunidades/referentes/catalogo para usarlos despues.
  (async function autoInit() {
    try {
      await ready();
      if (!navigator.onLine) {
        console.log('[OFFLINE] Sin red, skip bootstrap');
        return;
      }
      // Si ya hubo bootstrap reciente (<30 min), no repetir.
      try {
        const last = await window.ElectroDB.get('meta', 'last_bootstrap');
        if (last && last.value) {
          const ageMs = Date.now() - new Date(last.value).getTime();
          if (ageMs < 30 * 60 * 1000) {
            console.log('[OFFLINE] Bootstrap reciente, skip');
            return;
          }
        }
      } catch (e) { /* primera vez: no hay meta */ }

      console.log('[OFFLINE] Iniciando bootstrap...');
      const ok = await bootstrap();
      console.log('[OFFLINE] Bootstrap', ok ? 'OK' : 'FAILED');
    } catch (e) {
      console.error('[OFFLINE] Bootstrap auto-init error:', e);
    }
  })();
})();
