// electro - IndexedDB skeleton
// Solo apertura y schema base. La logica de operaciones va en otros archivos.

(function () {
  'use strict';

  const DB_NAME = 'electro_db';
  const DB_VERSION = 1;

  const ElectroDB = {
    db: null,

    open() {
      return new Promise((resolve, reject) => {
        if (this.db) return resolve(this.db);

        const req = indexedDB.open(DB_NAME, DB_VERSION);

        req.onupgradeneeded = (e) => {
          const db = e.target.result;
          console.log('[DB] Upgrading to version', DB_VERSION);

          // Store: cola de sincronizacion (operaciones pendientes de subir)
          if (!db.objectStoreNames.contains('sync_queue')) {
            const store = db.createObjectStore('sync_queue', {
              keyPath: 'id',
              autoIncrement: true,
            });
            store.createIndex('tipo', 'tipo', { unique: false });
            store.createIndex('created_at', 'created_at', { unique: false });
            store.createIndex('status', 'status', { unique: false });
          }

          // Store: viviendas cacheadas localmente (para ver/editar offline)
          if (!db.objectStoreNames.contains('viviendas')) {
            const store = db.createObjectStore('viviendas', {
              keyPath: 'codigo_interno',
            });
            store.createIndex('comunidad_id', 'comunidad_id', { unique: false });
            store.createIndex('updated_at', 'updated_at', { unique: false });
          }

          // Store: catalogo de artefactos (config-like, sincroniza con servidor)
          if (!db.objectStoreNames.contains('catalogo_artefactos')) {
            db.createObjectStore('catalogo_artefactos', { keyPath: 'id' });
          }

          // Store: comunidades, referentes, subsidios
          if (!db.objectStoreNames.contains('comunidades')) {
            db.createObjectStore('comunidades', { keyPath: 'id' });
          }
          if (!db.objectStoreNames.contains('referentes')) {
            db.createObjectStore('referentes', { keyPath: 'id' });
          }
          if (!db.objectStoreNames.contains('subsidios')) {
            db.createObjectStore('subsidios', { keyPath: 'id' });
          }

          // Store: cuotas pendientes (para cobrar offline)
          if (!db.objectStoreNames.contains('cuotas')) {
            const store = db.createObjectStore('cuotas', { keyPath: 'id' });
            store.createIndex('vivienda_id', 'vivienda_id', { unique: false });
            store.createIndex('estado', 'estado', { unique: false });
          }

          // Store: pagos offline pendientes de sync
          if (!db.objectStoreNames.contains('pagos_offline')) {
            const store = db.createObjectStore('pagos_offline', { keyPath: 'uuid' });
            store.createIndex('synced', 'synced', { unique: false });
          }

          // Store: metadata (last_sync, user_info, etc.)
          if (!db.objectStoreNames.contains('meta')) {
            db.createObjectStore('meta', { keyPath: 'key' });
          }
        };

        req.onsuccess = (e) => {
          this.db = e.target.result;
          console.log('[DB] Opened v' + DB_VERSION);
          resolve(this.db);
        };

        req.onerror = (e) => {
          console.error('[DB] Open error:', e);
          reject(e.target.error);
        };
      });
    },

    async put(storeName, value) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const req = store.put(value);
        req.onsuccess = () => resolve(req.result);
        req.onerror = (e) => reject(e.target.error);
      });
    },

    async get(storeName, key) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const req = store.get(key);
        req.onsuccess = () => resolve(req.result);
        req.onerror = (e) => reject(e.target.error);
      });
    },

    async getAll(storeName) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const req = store.getAll();
        req.onsuccess = () => resolve(req.result);
        req.onerror = (e) => reject(e.target.error);
      });
    },

    async delete(storeName, key) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readwrite');
        const store = tx.objectStore(storeName);
        const req = store.delete(key);
        req.onsuccess = () => resolve();
        req.onerror = (e) => reject(e.target.error);
      });
    },

    async count(storeName) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, 'readonly');
        const store = tx.objectStore(storeName);
        const req = store.count();
        req.onsuccess = () => resolve(req.result);
        req.onerror = (e) => reject(e.target.error);
      });
    },

    async syncPendingCount() {
      return await this.count('sync_queue');
    },

    async lastSyncDate() {
      const meta = await this.get('meta', 'last_sync');
      return meta ? new Date(meta.value) : null;
    },

    async daysSinceLastSync() {
      const last = await this.lastSyncDate();
      if (!last) return null;
      const diff = Date.now() - last.getTime();
      return Math.floor(diff / (1000 * 60 * 60 * 24));
    },
  };

  window.ElectroDB = ElectroDB;

  // Abrir al cargar
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () =>
      ElectroDB.open().catch(console.error)
    );
  } else {
    ElectroDB.open().catch(console.error);
  }
})();
