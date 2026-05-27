// electro - Guard de logout
// Si al hacer click en "Salir" hay items pendientes en la cola, pide confirmar:
//   - "Sincronizar ahora" → corre electroSync, despues hace logout si todo OK
//   - "Salir sin sincronizar" → submit del logout sin tocar nada
//   - "Cancelar" (cerrar modal) → no pasa nada
//
// El logout del proyecto es un POST con CSRF (ver menu_lateral.html), no un
// link <a href>. Por eso interceptamos el submit del form.logout-form.

(function () {
  'use strict';

  function submitLogoutForm(form) {
    // Marcamos para que nuestro propio handler NO reintercepte.
    form.dataset.bypassGuard = '1';
    form.submit();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const forms = document.querySelectorAll('form.logout-form, form[action="/logout"]');
    forms.forEach((form) => {
      form.addEventListener('submit', async (e) => {
        if (form.dataset.bypassGuard === '1') return; // dejar pasar
        if (!window.ElectroDB) return;                // sin IDB, comportamiento normal

        let count = 0;
        try {
          count = await window.ElectroDB.syncPendingCount();
        } catch (err) {
          return; // si no podemos leer la cola, no bloqueamos el logout
        }
        if (count === 0) return; // nada pendiente

        e.preventDefault();

        // Paso 1: ¿quieres sincronizar antes de salir?
        const wantsSync = await window.appModal.confirm(
          'Tienes cambios sin sincronizar',
          'Hay ' + count + ' cambio(s) pendiente(s) de enviar al servidor. ' +
          '¿Sincronizar ahora antes de salir?',
          { okText: 'Sincronizar ahora', cancelText: 'No, decidir despues' }
        );

        if (wantsSync === true) {
          try {
            const result = await window.electroSync.sincronizar();
            if (result.failed === 0 && result.conflict === 0) {
              // Todo OK: salir.
              submitLogoutForm(form);
            } else {
              await window.appModal.alert(
                'Hubo problemas',
                'Sincronizados: ' + result.ok + ' · conflictos: ' + result.conflict +
                ' · fallidos: ' + result.failed + '. Revisa /app/sync antes de salir.'
              );
            }
          } catch (err) {
            await window.appModal.alert('Error de sincronizacion', String(err.message || err));
          }
          return;
        }

        if (wantsSync === false) {
          // El usuario eligio "decidir despues" → segundo paso: salir o cancelar.
          const salirIgual = await window.appModal.confirm(
            'Salir sin sincronizar?',
            'Los ' + count + ' cambio(s) quedaran guardados en este dispositivo y se ' +
            'enviaran la proxima vez que entres y sincronices. ¿Salir igualmente?',
            { okText: 'Salir', cancelText: 'Cancelar', danger: true }
          );
          if (salirIgual === true) submitLogoutForm(form);
        }
        // Si wantsSync es undefined (Escape/backdrop) → no hacer nada (cancelar).
      });
    });
  });
})();
