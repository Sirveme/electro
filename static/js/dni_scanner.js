/*
 * window.dniScanner.scan({videoEl, onSuccess, onTimeout, onError, timeoutMs})
 *
 * 1. Abre la cámara trasera en el videoEl que se pasa.
 * 2. Usa @zxing/library (window.ZXing) para detectar PDF417.
 * 3. Si detecta, parsea y llama onSuccess({dni, paterno, materno, nombres, sexo, fecha_nac}).
 * 4. Si timeoutMs pasa sin detectar, llama onTimeout() y detiene la cámara.
 * 5. Si falla al abrir la cámara, llama onError(err).
 *
 * También soporta la firma posicional vieja: scan(onSuccess, onTimeout, timeoutMs)
 * en cuyo caso usa o crea un <video id="dni-video"> oculto.
 *
 * Asume que zxing.min.js fue cargado antes y expone window.ZXing.
 */
(function () {
  var codeReader = null;
  var timer = null;
  var currentVideo = null;

  function ensureDefaultVideo() {
    var v = document.getElementById('dni-video');
    if (!v) {
      v = document.createElement('video');
      v.id = 'dni-video';
      v.autoplay = true;
      v.muted = true;
      v.playsInline = true;
      v.style.display = 'none';
      document.body.appendChild(v);
    }
    return v;
  }

  function parsePdf417Pe(raw) {
    // PDF417 del DNI peruano: campos delimitados.
    // Separadores observados: '@' en azul antiguo, otros en formatos nuevos.
    if (!raw) return null;
    var parts = raw.split('@');
    if (parts.length < 5) parts = raw.split('|');
    if (parts.length < 5) parts = raw.split(/\r?\n/);

    var out = { _raw: raw };
    var dniMatch = raw.match(/\b(\d{8})\b/);
    if (dniMatch) out.dni = dniMatch[1];

    if (parts.length >= 4) {
      var fields = parts.map(function (s) { return s.trim(); });
      if (!out.dni && /^\d{8}$/.test(fields[0])) out.dni = fields[0];
      out.paterno = out.paterno || fields[1] || null;
      out.materno = out.materno || fields[2] || null;
      out.nombres = out.nombres || fields[3] || null;
      var sexoMatch = raw.match(/(?:^|[^A-Z])([MF])(?:[^A-Z]|$)/);
      if (sexoMatch) out.sexo = sexoMatch[1];
      var fechaMatch = raw.match(/(\d{2})\/(\d{2})\/(\d{4})/);
      if (fechaMatch) out.fecha_nac = fechaMatch[3] + '-' + fechaMatch[2] + '-' + fechaMatch[1];
    }

    return out;
  }

  async function scan() {
    // Soporta dos firmas:
    //   scan({videoEl, onSuccess, onTimeout, onError, timeoutMs})    ← preferida
    //   scan(onSuccess, onTimeout, timeoutMs)                         ← legacy
    var opts;
    if (typeof arguments[0] === 'object' && arguments[0] !== null && !Array.isArray(arguments[0])) {
      opts = arguments[0];
    } else {
      opts = {
        onSuccess: arguments[0],
        onTimeout: arguments[1],
        timeoutMs: arguments[2],
      };
    }

    var onSuccess = opts.onSuccess;
    var onTimeout = opts.onTimeout;
    var onError = opts.onError;
    var timeoutMs = opts.timeoutMs || 8000;
    var video = opts.videoEl || ensureDefaultVideo();
    currentVideo = video;

    if (typeof window.ZXing === 'undefined') {
      var msg = 'La librería de escaneo no se cargó. Revisa que static/js/zxing.min.js esté presente.';
      if (typeof onError === 'function') {
        onError(new Error(msg));
      } else if (window.appModal) {
        window.appModal.alert('Error', msg, { tipo: 'error' });
      }
      return;
    }

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
        if (!found) {
          stop();
          if (typeof onTimeout === 'function') onTimeout();
        }
      }, timeoutMs);

      codeReader.decodeFromVideoDevice(preferred.deviceId, video, function (result /*, err */) {
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
      if (typeof onError === 'function') {
        onError(e);
      } else if (window.appModal) {
        window.appModal.alert('No se pudo abrir la cámara', e.message || String(e), { tipo: 'error' });
      }
    }
  }

  function stop() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (codeReader) {
      try { codeReader.reset(); } catch (_) { /* noop */ }
      codeReader = null;
    }
    if (currentVideo) {
      try {
        if (currentVideo.srcObject) {
          currentVideo.srcObject.getTracks().forEach(function (t) {
            try { t.stop(); } catch (_) {}
          });
          currentVideo.srcObject = null;
        }
      } catch (_) { /* noop */ }
      currentVideo = null;
    }
  }

  window.dniScanner = { scan: scan, stop: stop };
})();