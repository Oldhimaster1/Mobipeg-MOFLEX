// Browser-only CIA builder UI. The actual movie and icon data never leave this device.
export const CIA_ID_MIN = 0xc0000;
export const CIA_ID_MAX = 0xeffff;
const MAX_ART_BYTES = 32 * 1024 * 1024;
const MAX_PIXELS = 40 * 1000 * 1000;
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

export function randomCiaId(used = [], random = globalThis.crypto) {
  if (!random || typeof random.getRandomValues !== 'function')
    throw Error('Secure random numbers are unavailable in this browser.');
  const reserved = new Set([...used].map(id => String(id).toUpperCase()));
  const range = CIA_ID_MAX - CIA_ID_MIN + 1;
  const bucket = Math.floor(0x100000000 / range) * range;
  const word = new Uint32Array(1);
  for (let attempt = 0; attempt < 128; attempt++) {
    random.getRandomValues(word);
    if (word[0] >= bucket) continue;
    const code = (CIA_ID_MIN + (word[0] % range)).toString(16).toUpperCase();
    if (!reserved.has(code)) return code;
  }
  throw Error('Could not find an unused title ID. Try again.');
}

export function coverGeometry(sw, sh, tw, th, {
  fit = 'fill', aspect = 'native', zoom = 100, x = 0, y = 0
} = {}) {
  if (![sw, sh, tw, th].every(n => Number.isFinite(n) && n > 0))
    throw Error('Invalid artwork dimensions.');
  if (!['fill', 'fit'].includes(fit)) throw Error('Unknown artwork fit mode.');
  const ratio = ({native:tw / th, square:1, wide:16 / 9, cinema:21 / 9, portrait:3 / 4})[aspect];
  if (!ratio) throw Error('Unknown artwork aspect ratio.');
  // Alternative ratios use letterboxing inside the CIA's required output size.
  const bw = Math.min(tw, th * ratio), bh = Math.min(th, tw / ratio);
  const ox = (tw - bw) / 2, oy = (th - bh) / 2;
  const base = (fit === 'fill' ? Math.max : Math.min)(bw / sw, bh / sh);
  const scale = base * clamp(Number(zoom) || 100, 100, 300) / 100;
  const dw = sw * scale, dh = sh * scale;
  // Pan only when there is cropped content in that direction.
  const dx = ox + (bw - dw) / 2 + Math.max(0, dw - bw) * clamp(Number(x) || 0, -100, 100) / 200;
  const dy = oy + (bh - dh) / 2 + Math.max(0, dh - bh) * clamp(Number(y) || 0, -100, 100) / 200;
  return {dx, dy, dw, dh};
}

export function drawCover(ctx, bitmap, width, height, settings = {}) {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#111d18';
  ctx.fillRect(0, 0, width, height);
  const {dx, dy, dw, dh} = coverGeometry(bitmap.width, bitmap.height, width, height, settings);
  const aspect = ({native:width / height, square:1, wide:16/9, cinema:21/9, portrait:3/4})[settings.aspect || 'native'];
  const bw = Math.min(width, height * aspect), bh = Math.min(height, width / aspect);
  ctx.save();
  ctx.beginPath();
  ctx.rect((width - bw)/2, (height - bh)/2, bw, bh);
  ctx.clip();
  ctx.drawImage(bitmap, dx, dy, dw, dh);
  ctx.restore();
}

const imageFile = file => !!file && /\.(png|bmp|jpe?g)$/i.test(file.name);
const readHistory = () => {
  try {
    const value = JSON.parse(localStorage.getItem('mobipeg-cia-ids') || '[]');
    return Array.isArray(value) ? value.filter(x => /^[CDE][0-9A-F]{4}$/.test(x)).slice(-256) : [];
  } catch { return []; }
};
const remember = id => {
  try {
    const saved = readHistory().filter(x => x !== id);
    saved.push(id);
    localStorage.setItem('mobipeg-cia-ids', JSON.stringify(saved.slice(-256)));
  } catch { /* Storage is optional. */ }
};
export function setupCiaDesign({getEpisodes, notify, setFile}) {
  const $ = id => document.getElementById(id);
  const urls = new Map();
  const current = {bitmap: null, kind: null, apply: null, filename: ''};
  const canvas = $('ciaArtworkCanvas');
  const ctx = canvas.getContext('2d');
  const dialog = $('ciaArtworkDialog');
  const fit = $('ciaArtworkFit'), aspect = $('ciaArtworkAspect'), zoom = $('ciaArtworkZoom'),
    panX = $('ciaArtworkX'), panY = $('ciaArtworkY');
  let active = false;

  function url(file) {
    if (!imageFile(file)) return null;
    if (!urls.has(file)) urls.set(file, URL.createObjectURL(file));
    return urls.get(file);
  }
  function setImage(img, placeholder, file) {
    const src = url(file);
    img.hidden = !src;
    placeholder.hidden = !!src;
    if (src && img.src !== src) img.src = src;
    if (!src) img.removeAttribute('src');
  }
  function refresh() {
    const title = $('ciaTitle').value.trim() || 'Your movie';
    $('ciaLiveTitle').textContent = title;
    $('ciaLivePublisher').textContent = $('ciaPublisher').value.trim() || 'MobiPEG';
    const id = $('ciaId').value.toUpperCase();
    $('ciaLiveId').textContent = /^[CDE][0-9A-F]{4}$/.test(id) ? id : '—';
    setImage($('ciaLiveIcon'), $('ciaIconFallback'), $('ciaIcon').files[0]);
    setImage($('ciaLiveBanner'), $('ciaBannerFallback'), $('ciaBanner').files[0]);
    const list = $('ciaLiveEpisodes');
    list.replaceChildren();
    const episodes = getEpisodes();
    if (!episodes.length) {
      const empty = document.createElement('li');
      empty.className = 'cia-preview-empty';
      empty.textContent = 'Your episodes will appear here.';
      list.append(empty);
    }
    for (const [index, episode] of episodes.entries()) {
      const item = document.createElement('li');
      const thumbnail = document.createElement('span');
      thumbnail.className = 'cia-preview-thumb';
      const src = url(episode.bannerFile);
      if (src) {
        const img = document.createElement('img');
        img.src = src;
        img.alt = '';
        thumbnail.append(img);
      } else thumbnail.textContent = String(index + 1);
      const label = document.createElement('span');
      label.textContent = episode.title || episode.file?.name || 'Episode ' + (index + 1);
      item.append(thumbnail, label);
      list.append(item);
    }
  }

  function generate() {
    const used = readHistory();
    const currentId = $('ciaId').value.toUpperCase();
    if (currentId) used.push(currentId);
    const id = randomCiaId(used);
    $('ciaId').value = id;
    remember(id);
    refresh();
    return id;
  }
  $('ciaNewId').addEventListener('click', () => {
    try { generate(); }
    catch (error) { notify(error.message, true); }
  });
  if (!$('ciaId').value) {
    try { generate(); }
    catch (error) { notify(error.message, true); }
  }
  // A user-edited title ID remains untouched until Generate is explicitly clicked.
  $('ciaId').addEventListener('input', refresh);
  for (const id of ['ciaTitle', 'ciaPublisher', 'ciaLongTitle']) {
    $(id).addEventListener('input', refresh);
  }
  for (const id of ['ciaIcon', 'ciaBanner']) $(id).addEventListener('change', refresh);

  function dimensions(kind) {
    return kind === 'icon' ? [48, 48] : [200, 120];
  }
  function paint() {
    if (!current.bitmap) return;
    const [width, height] = dimensions(current.kind);
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    drawCover(ctx, current.bitmap, width, height, {
      fit: fit.value, aspect: aspect.value, zoom: +zoom.value, x: +panX.value, y: +panY.value
    });
    $('ciaArtworkZoomValue').textContent = zoom.value + '%';
  }
  for (const control of [fit, aspect, zoom, panX, panY]) control.addEventListener('input', paint);

  let drag = null;
  canvas.addEventListener('pointerdown', event => {
    if (!current.bitmap) return;
    drag = {x: event.clientX, y: event.clientY, panX: +panX.value, panY: +panY.value};
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || !current.bitmap) return;
    const box = canvas.getBoundingClientRect();
    panX.value = String(clamp(Math.round(drag.panX + (event.clientX - drag.x) * 120 / Math.max(box.width, 1)), -100, 100));
    panY.value = String(clamp(Math.round(drag.panY + (event.clientY - drag.y) * 120 / Math.max(box.height, 1)), -100, 100));
    paint();
  });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('pointercancel', () => { drag = null; });

  async function openEditor(file, kind, apply, filename) {
    if (!file) {
      notify('Choose an image before opening the editor.', true);
      return;
    }
    if (!imageFile(file)) {
      notify('The editor supports PNG, JPG and BMP artwork. Prepared icon and banner files can still be used without editing.', true);
      return;
    }
    if (file.size > MAX_ART_BYTES) { notify('Artwork must be smaller than 32 MB.', true); return; }
    let bitmap;
    try {
      bitmap = await createImageBitmap(file);
      if (bitmap.width * bitmap.height > MAX_PIXELS) throw Error('Artwork exceeds 40 megapixels.');
    } catch (error) {
      bitmap?.close();
      notify('Could not open this image: ' + error.message, true);
      return;
    }
    if (current.bitmap) current.bitmap.close();
    current.bitmap = bitmap;
    current.kind = kind;
    current.apply = apply;
    current.filename = filename;
    fit.value = 'fill'; aspect.value = 'native'; zoom.value = '100'; panX.value = '0'; panY.value = '0';
    $('ciaArtworkHeading').textContent = kind === 'icon' ? 'Edit HOME Menu icon' :
      kind === 'banner' ? 'Edit HOME Menu banner' : 'Edit episode artwork';
    paint();
    dialog.showModal();
    active = true;
  }

  $('ciaEditIcon').addEventListener('click', () =>
    openEditor($('ciaIcon').files[0], 'icon', file => setFile('ciaIcon', file), 'mobipeg-icon.png'));
  $('ciaEditBanner').addEventListener('click', () =>
    openEditor($('ciaBanner').files[0], 'banner', file => setFile('ciaBanner', file), 'mobipeg-banner.png'));
  $('ciaArtworkCancel').addEventListener('click', () => dialog.close());
  $('ciaArtworkApply').addEventListener('click', async () => {
    if (!current.bitmap || !active) return;
    $('ciaArtworkApply').disabled = true;
    try {
      paint();
      const blob = await new Promise((resolve, reject) =>
        canvas.toBlob(result => result ? resolve(result) : reject(Error('Could not export edited image.')), 'image/png'));
      const file = new File([blob], current.filename, {type: 'image/png'});
      current.apply(file);
      refresh();
      dialog.close();
    } catch (error) { notify(error.message, true); }
    finally { $('ciaArtworkApply').disabled = false; }
  });
  dialog.addEventListener('close', () => {
    drag = null; active = false;
    current.bitmap?.close(); current.bitmap = null;
    current.apply = null;
  });
  window.addEventListener('pagehide', () => {
    for (const src of urls.values()) URL.revokeObjectURL(src);
    urls.clear();
  });
  refresh();
  return {
    refresh,
    remember,
    editEpisode(file, index, onDone) {
      return openEditor(file, 'episode', onDone, 'episode-' + (index + 1) + '-art.png');
    },
  };
}
