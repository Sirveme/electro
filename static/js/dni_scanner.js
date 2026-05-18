/*
 * window.dniScanner.scan(onSuccess, onTimeout, timeoutMs)
 *
 * 1. Abre la cámara trasera del dispositivo.
 * 2. Usa @zxing/library (variable global ZXing) para detectar PDF417.
 * 3. Si detecta, parsea la cadena y llama onSuccess({dni, paterno, materno, nombres, sexo, fecha_nac}).
 * 4. Si pasa timeoutMs sin detectar, llama onTimeout() y deja la cámara abierta
 *    para que el usuario pueda tomar foto del frente y procesar vía Vision.
 *
 * Asume que zxing.min.js fue cargado antes y expone window.ZXing.
 */
(function () {
  var codeReader = null;
  var stream = null;
  var timer = null;

  function getVideo() {
    var v = document.getElementById('dni-video');
    if (!v) {
      v = document.createElement('video');
      v.id = 'dni-video';
      v.autoplay = true;
      v.muted = true;
      v.playsInline = true;
      document.body.appendChild(v);
    }
    return v;
  }

  function parsePdf417Pe(raw) {
    // El PDF417 del DNI peruano electrónico tiene los campos delimitados.
    // Separadores observados: '@' en azul antiguo, otros en formatos nuevos.
    // Estrategia: split por '@', si no rinde, split por '|' o '\n'. Si nada,
    // devolvemos solo el _raw para revisión manual.
    if (!raw) return null;
    var parts = raw.split('@');
    if (parts.length < 5) parts = raw.split('|');
    if (parts.length < 5) parts = raw.split(/\r?\n/);

    var out = { _raw: raw };
    var dniMatch = raw.match(/\b(\d{8})\b/);
    if (dniMatch) out.dni = dniMatch[1];

    if (parts.length >= 4) {
      // Heurística: los primeros campos suelen ser DNI, paterno, materno, nombres
      var fields = parts.map(function (s) { return s.trim(); });
      if (!out.dni && /^\d{8}$/.test(fields[0])) out.dni = fields[0];
      out.paterno = out.paterno || fields[1] || null;
      out.materno = out.materno || fields[2] || null;
      out.nombres = out.nombres || fields[3] || null;
      // Sexo: buscar M o F suelto
      var sexoMatch = raw.match(/(?:^|[^A-Z])([MF])(?:[^A-Z]|$)/);
      if (sexoMatch) out.sexo = sexoMatch[1];
      // Fecha de nacimiento DD/MM/YYYY
      var fechaMatch = raw.match(/(\d{2})\/(\d{2})\/(\d{4})/);
      if (fechaMatch) out.fecha_nac = fechaMatch[3] + '-' + fechaMatch[2] + '-' + fechaMatch[1];
    }

    return out;
  }

  async function scan(onSuccess, onTimeout, timeoutMs) {
    timeoutMs = timeoutMs || 8000;

    if (typeof window.ZXing === 'undefined') {
      window.appModal.alert('Error', 'La librería de escaneo no se cargó. Revisa que static/js/zxing.min.js esté presente.', { tipo: 'error' });
      return;
    }

    var video = getVideo();
    video.style.display = 'block';

    try {
      var ZX = window.ZXing;
      var hints = new Map();
      hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, [ZX.BarcodeFormat.PDF_417]);
      codeReader = new ZX.BrowserMultiFormatReader(hints);

      var devices = await codeReader.listVideoInputDevices();
      var preferred = devices.find(function (d) {
        return /back|rear|environment|trasera/i.test(d.label);
      }) || devices[0];
      if (!preferred) throw new Error('No se encontró cámara');

      var found = false;
      timer = setTimeout(function () {
        if (!found && typeof onTimeout === 'function') onTimeout();
      }, timeoutMs);

      codeReader.decodeFromVideoDevice(preferred.deviceId, video, function (result, err) {
        if (result && !found) {
          found = true;
          clearTimeout(timer);
          var data = parsePdf417Pe(result.getText()) || {};
          stop();
          if (typeof onSuccess === 'function') onSuccess(data);
        }
        // err == NotFoundException en frames sin match — ignorar, sigue buscando
      });
    } catch (e) {
      stop();
      window.appModal.alert('No se pudo abrir la cámara', e.message || String(e), { tipo: 'error' });
    }
  }

  function stop() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (codeReader) {
      try { codeReader.reset(); } catch (_) { /* noop */ }
      codeReader = null;
    }
    if (stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (_) { /* noop */ } });
      stream = null;
    }
    var video = document.getElementById('dni-video');
    if (video) video.style.display = 'none';
  }

  window.dniScanner = { scan: scan, stop: stop };
})();
