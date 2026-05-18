/*
 * window.imageCompress.{fromFile, fromBlob}
 * Comprime imágenes a JPEG con maxWidth y quality dados.
 * Retorna Blob.
 */
(function () {
  async function compress(blob, opts) {
    opts = opts || {};
    var maxWidth = opts.maxWidth || 1280;
    var quality = typeof opts.quality === 'number' ? opts.quality : 0.82;

    var bitmap;
    if (typeof createImageBitmap === 'function') {
      try { bitmap = await createImageBitmap(blob); }
      catch (e) { bitmap = await blobToImage(blob); }
    } else {
      bitmap = await blobToImage(blob);
    }

    var w = bitmap.width;
    var h = bitmap.height;
    if (w > maxWidth) {
      h = Math.round(h * (maxWidth / w));
      w = maxWidth;
    }

    var canvas;
    if (typeof OffscreenCanvas !== 'undefined') {
      canvas = new OffscreenCanvas(w, h);
    } else {
      canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
    }
    var ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0, w, h);

    if (canvas.convertToBlob) {
      return await canvas.convertToBlob({ type: 'image/jpeg', quality: quality });
    }
    return await new Promise(function (resolve) {
      canvas.toBlob(resolve, 'image/jpeg', quality);
    });
  }

  function blobToImage(blob) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('Imagen inválida')); };
      img.src = url;
    });
  }

  window.imageCompress = {
    fromFile: function (file, opts) { return compress(file, opts); },
    fromBlob: function (blob, opts) { return compress(blob, opts); },
  };
})();
