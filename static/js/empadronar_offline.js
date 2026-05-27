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
      if (data.config) {
        await db.put('meta', { key: 'config_municipio', value: data.config });
      }
      if (data.user) {
        await db.put('meta', { key: 'user_info', value: data.user });
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

    // Espejo en `viviendas` para que el padron muestre la vivienda offline.
    await db.put('viviendas', {
      codigo_interno: 'V-OFFLINE-' + payload.uuid_cliente.slice(0, 8),
      uuid_cliente: payload.uuid_cliente,
      comunidad_id: payload.comunidad_id,
      referencia_fisica: payload.referencia_fisica,
      gps_lat: payload.gps_lat,
      gps_lng: payload.gps_lng,
      updated_at: new Date().toISOString(),
      _offline: true,
      _sync_id: id,
    });

    console.log('[OFFLINE] Empadronamiento encolado id=', id, 'uuid=', payload.uuid_cliente);
    return { id, uuid_cliente: payload.uuid_cliente };
  }
  window.electroEncolarEmpadronamiento = encolarEmpadronamiento;

  // Bootstrap automatico cuando hay conexion (modo no-offline).
  // Solo refresca si pasaron mas de 30 min desde el ultimo.
  document.addEventListener('DOMContentLoaded', async () => {
    await ready();
    const mode = (window.ElectroConnectionMode &&
                  window.ElectroConnectionMode.get &&
                  window.ElectroConnectionMode.get()) || 'offline';
    if (mode === 'offline' || !navigator.onLine) return;

    try {
      const last = await window.ElectroDB.get('meta', 'last_bootstrap');
      if (last && last.value) {
        const ageMs = Date.now() - new Date(last.value).getTime();
        if (ageMs < 30 * 60 * 1000) return; // fresh enough
      }
    } catch (e) { /* ignorar */ }

    bootstrap().catch(() => {});
  });
})();
