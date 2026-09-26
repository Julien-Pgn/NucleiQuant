// Canvas viewer: multichannel composite, nucleus outlines, pan/zoom, click-to-pick.

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255];
}

export class Viewer {
  constructor(el, handlers = {}) {
    this.el = el;
    this.handlers = handlers;
    this.canvas = document.createElement("canvas");
    this.ctx = this.canvas.getContext("2d");
    el.append(this.canvas);
    this.composite = document.createElement("canvas");
    this.data = null;
    this.channels = [];
    this.style = () => null;
    this.showOutlines = true;
    this.hovered = 0;
    this.view = { zoom: 1, tx: 0, ty: 0 };
    this._dirty = false;
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(el);
    this._bind();
  }

  destroy() {
    this._ro.disconnect();
    this._unbind();
    this.canvas.remove();
  }

  // ---- data ----------------------------------------------------------------------
  setData({ raw, C, H, W, labels, outlines }) {
    this.data = { raw, C, H, W, labels };
    this.composite.width = W;
    this.composite.height = H;
    this._acc = new Float32Array(W * H * 3);
    this._image = new ImageData(W, H);
    // Outline bounding boxes and label -> index lookup
    const { ids, offsets, pts } = outlines;
    const n = ids.length;
    const bb = new Float32Array(4 * n);
    let maxId = 0;
    for (let i = 0; i < n; i++) {
      let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
      for (let k = offsets[i]; k < offsets[i + 1]; k++) {
        const x = pts[2 * k], y = pts[2 * k + 1];
        if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      }
      bb[4 * i] = x0; bb[4 * i + 1] = y0; bb[4 * i + 2] = x1 + 1; bb[4 * i + 3] = y1 + 1;
      if (ids[i] > maxId) maxId = ids[i];
    }
    const index = new Int32Array(maxId + 1).fill(-1);
    for (let i = 0; i < n; i++) index[ids[i]] = i;
    this.outlines = { ids, offsets, pts, bb, index };
    this.histograms = null;
    this.fit();
  }

  // Percentile-based contrast for one channel, from a histogram of the data.
  autoRange(c, low = 0.5, high = 99.8) {
    const { raw, H, W } = this.data;
    const N = H * W;
    if (!this.histograms) this.histograms = [];
    if (!this.histograms[c]) {
      const hist = new Uint32Array(65536);
      const off = c * N;
      for (let i = 0; i < N; i += 2) hist[raw[off + i]]++;
      this.histograms[c] = hist;
    }
    const hist = this.histograms[c];
    let total = 0;
    for (let v = 0; v < 65536; v++) total += hist[v];
    const find = (p) => {
      const target = total * p / 100;
      let acc = 0;
      for (let v = 0; v < 65536; v++) { acc += hist[v]; if (acc >= target) return v; }
      return 65535;
    };
    let lo = find(low), hi = find(high);
    if (hi <= lo) hi = lo + 1;
    let max = 0;
    for (let v = 65535; v >= 0; v--) if (hist[v]) { max = v; break; }
    return { lo, hi, max };
  }

  setChannels(channels) {
    this.channels = channels;
    this._recomposite();
    this.draw();
  }

  _recomposite() {
    if (!this.data) return;
    const { raw, C, H, W } = this.data;
    const N = H * W;
    const acc = this._acc;
    acc.fill(0);
    for (let c = 0; c < C; c++) {
      const ch = this.channels[c];
      if (!ch || !ch.visible) continue;
      const [r, g, b] = hexToRgb(ch.color);
      const lo = ch.lo, inv = 1 / Math.max(ch.hi - ch.lo, 1e-6);
      const off = c * N;
      for (let i = 0, j = 0; i < N; i++, j += 3) {
        let f = (raw[off + i] - lo) * inv;
        if (f <= 0) continue;
        if (f > 1) f = 1;
        acc[j] += f * r; acc[j + 1] += f * g; acc[j + 2] += f * b;
      }
    }
    const px = this._image.data;
    for (let i = 0, j = 0, k = 0; i < N; i++, j += 3, k += 4) {
      px[k] = acc[j] * 255; px[k + 1] = acc[j + 1] * 255; px[k + 2] = acc[j + 2] * 255; px[k + 3] = 255;
    }
    this.composite.getContext("2d").putImageData(this._image, 0, 0);
  }

  // ---- view ------------------------------------------------------------------------
  _resize() {
    const r = this.el.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.cw = r.width;
    this.ch = r.height;
    this.canvas.width = Math.max(1, Math.round(r.width * this.dpr));
    this.canvas.height = Math.max(1, Math.round(r.height * this.dpr));
    if (this.data && !this._fitted) this.fit();
    this.draw();
  }

  fit() {
    if (!this.data || !this.cw) return;
    const { H, W } = this.data;
    const z = Math.min(this.cw / W, this.ch / H) * 0.98;
    this.view = { zoom: z, tx: (this.cw - W * z) / 2, ty: (this.ch - H * z) / 2 };
    this._fitted = true;
    this.minZoom = z * 0.5;
    this.draw();
    this._emitView();
  }

  zoomBy(factor, cx = this.cw / 2, cy = this.ch / 2) {
    const v = this.view;
    const z = Math.min(40, Math.max(this.minZoom || 0.05, v.zoom * factor));
    const ix = (cx - v.tx) / v.zoom, iy = (cy - v.ty) / v.zoom;
    this.view = { zoom: z, tx: cx - ix * z, ty: cy - iy * z };
    this.draw();
    this._emitView();
  }

  setZoom(z) { this.zoomBy(z / this.view.zoom); }

  _emitView() { if (this.handlers.onView) this.handlers.onView(this.view); }

  labelAt(sx, sy) {
    if (!this.data) return 0;
    const ix = Math.floor((sx - this.view.tx) / this.view.zoom);
    const iy = Math.floor((sy - this.view.ty) / this.view.zoom);
    const { H, W, labels } = this.data;
    if (ix < 0 || iy < 0 || ix >= W || iy >= H) return 0;
    return labels[iy * W + ix];
  }

  // ---- drawing -------------------------------------------------------------------------
  draw() {
    if (this._dirty) return;
    this._dirty = true;
    requestAnimationFrame(() => { this._dirty = false; this._draw(); });
  }

  _draw() {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.data) return;
    const { zoom, tx, ty } = this.view;
    const d = this.dpr;
    ctx.setTransform(d * zoom, 0, 0, d * zoom, d * tx, d * ty);
    ctx.imageSmoothingEnabled = zoom < 4;
    ctx.drawImage(this.composite, 0, 0);
    if (!this.showOutlines || !this.outlines) return;

    const x0 = -tx / zoom, y0 = -ty / zoom, x1 = x0 + this.cw / zoom, y1 = y0 + this.ch / zoom;
    const { ids, offsets, pts, bb } = this.outlines;
    const groups = new Map();
    const fills = new Map();
    const haloPath = new Path2D();
    let halos = 0;
    let hoverIdx = -1;
    for (let i = 0; i < ids.length; i++) {
      if (bb[4 * i + 2] < x0 || bb[4 * i] > x1 || bb[4 * i + 3] < y0 || bb[4 * i + 1] > y1) continue;
      const lab = ids[i];
      if (lab === this.hovered) hoverIdx = i;
      const st = this.style(lab);
      if (!st) continue;
      if (st.fill) {
        if (!fills.has(st.fill)) fills.set(st.fill, new Path2D());
        this._trace(fills.get(st.fill), i);
      }
      if (st.stroke) {
        const key = `${st.stroke}|${st.weight || 1}|${st.alpha || 1}`;
        if (!groups.has(key)) groups.set(key, { path: new Path2D(), color: st.stroke, weight: st.weight || 1, alpha: st.alpha || 1 });
        this._trace(groups.get(key).path, i);
        if ((st.weight || 1) >= 2 || st.halo) { this._trace(haloPath, i); halos++; }
      }
    }
    const px = 1 / zoom;
    ctx.lineJoin = "round";
    for (const [color, path] of fills) {
      ctx.globalAlpha = 0.42;
      ctx.fillStyle = color;
      ctx.fill(path);
    }
    ctx.globalAlpha = 1;
    if (halos && zoom > 0.6) {
      ctx.strokeStyle = "rgba(0,0,0,0.75)";
      ctx.lineWidth = 4 * px;
      ctx.stroke(haloPath);
    }
    for (const g of groups.values()) {
      // Faint outlines (alpha < 1) fade out when zoomed out, so the image stays readable
      ctx.globalAlpha = g.alpha < 1 ? g.alpha * Math.min(1, Math.max(0, (zoom - 0.45) / 0.6)) : g.alpha;
      if (ctx.globalAlpha <= 0.01) continue;
      ctx.strokeStyle = g.color;
      ctx.lineWidth = (g.weight >= 2 ? 2 : 1) * px * (zoom < 0.6 ? 0.8 : 1);
      ctx.stroke(g.path);
    }
    ctx.globalAlpha = 1;
    if (hoverIdx >= 0) {
      const p = this._path(hoverIdx);
      ctx.strokeStyle = "rgba(0,0,0,0.8)";
      ctx.lineWidth = 5 * px;
      ctx.stroke(p);
      ctx.strokeStyle = "#FFFFFF";
      ctx.lineWidth = 2.2 * px;
      ctx.stroke(p);
    }
  }

  _path(i) {
    const p = new Path2D();
    this._trace(p, i);
    return p;
  }

  // Append outline i (pixel-centre polygon) to a Path2D
  _trace(p, i) {
    const { offsets, pts } = this.outlines;
    const a = offsets[i], b = offsets[i + 1];
    if (b - a <= 2) {
      let x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1;
      for (let k = a; k < b; k++) {
        x0 = Math.min(x0, pts[2 * k]); x1 = Math.max(x1, pts[2 * k]);
        y0 = Math.min(y0, pts[2 * k + 1]); y1 = Math.max(y1, pts[2 * k + 1]);
      }
      p.rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
      return;
    }
    p.moveTo(pts[2 * a] + 0.5, pts[2 * a + 1] + 0.5);
    for (let k = a + 1; k < b; k++) p.lineTo(pts[2 * k] + 0.5, pts[2 * k + 1] + 0.5);
    p.closePath();
  }

  // ---- interaction ------------------------------------------------------------------------
  _bind() {
    const el = this.el;
    this._down = null;
    this._onDown = (e) => {
      if (e.button !== 0 && e.button !== 1) return;
      this._down = { x: e.clientX, y: e.clientY, tx: this.view.tx, ty: this.view.ty, moved: false, button: e.button };
      el.setPointerCapture(e.pointerId);
    };
    this._onMove = (e) => {
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      if (this._down) {
        const dx = e.clientX - this._down.x, dy = e.clientY - this._down.y;
        if (!this._down.moved && Math.hypot(dx, dy) > 4) { this._down.moved = true; el.classList.add("panning"); }
        if (this._down.moved) {
          this.view.tx = this._down.tx + dx;
          this.view.ty = this._down.ty + dy;
          this.draw();
        }
        return;
      }
      const lab = this.labelAt(sx, sy);
      if (lab !== this.hovered) {
        this.hovered = lab;
        this.draw();
        if (this.handlers.onHover) this.handlers.onHover(lab, e);
      } else if (lab && this.handlers.onHoverMove) this.handlers.onHoverMove(lab, e);
    };
    this._onUp = (e) => {
      if (!this._down) return;
      const d = this._down;
      this._down = null;
      el.classList.remove("panning");
      if (d.moved) { this._emitView(); return; }
      if (d.button !== 0) return;
      const r = el.getBoundingClientRect();
      const lab = this.labelAt(e.clientX - r.left, e.clientY - r.top);
      if (this.handlers.onClick) this.handlers.onClick(lab, e);
    };
    this._onLeave = () => {
      if (this.hovered) { this.hovered = 0; this.draw(); if (this.handlers.onHover) this.handlers.onHover(0); }
    };
    this._onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const f = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018));
      this.zoomBy(f, e.clientX - r.left, e.clientY - r.top);
    };
    this._onContext = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const lab = this.labelAt(e.clientX - r.left, e.clientY - r.top);
      if (this.handlers.onRightClick) this.handlers.onRightClick(lab, e);
    };
    el.addEventListener("pointerdown", this._onDown);
    el.addEventListener("pointermove", this._onMove);
    el.addEventListener("pointerup", this._onUp);
    el.addEventListener("pointerleave", this._onLeave);
    el.addEventListener("wheel", this._onWheel, { passive: false });
    el.addEventListener("contextmenu", this._onContext);
  }

  _unbind() {
    const el = this.el;
    el.removeEventListener("pointerdown", this._onDown);
    el.removeEventListener("pointermove", this._onMove);
    el.removeEventListener("pointerup", this._onUp);
    el.removeEventListener("pointerleave", this._onLeave);
    el.removeEventListener("wheel", this._onWheel);
    el.removeEventListener("contextmenu", this._onContext);
  }
}
