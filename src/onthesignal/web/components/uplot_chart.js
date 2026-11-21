// Generic µPlot renderer of a FigureSpec (web specification §5, rule R11).
// The figure description and the decimated, aligned data come from the server; this
// component only draws them. Events emitted: "zoom" {panel, min, max} (time plots, to
// reload the visible window at full resolution) and "select" {panel, min, max} (Shift+drag).
// Heatmap panels (spectrogram, §5.4) receive a grid of 16-bit levels, colored here and read
// under the cursor. Navigation as in the matplotlib toolbar: full view, previous and next
// view, "zoom" mode (drag a range) and "pan" mode (drag to move); Ctrl + wheel zooms around
// the cursor, Shift + wheel (or a horizontal wheel) and the middle button move. In live mode
// (real-time dashboard), new data re-scale the axes until the user zooms or moves.
// Markers, bands and levels with a "ref" are linked to the rows of the results panel that
// carry data-ots-for="<id of this chart>" and data-ots-ref="<ref>" (§7.5): hovering one
// highlights the other, in the browser only.
import uPlot from "onthesignal-uplot";
import { loadResource } from "../../static/utils/resources.js";

const SIGNIFICANT = 5;
const EMPTY = 65535;
const LEVELS = 65534;

function hexRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// 256-entry lookup table interpolated between the color stops.
function ramp(stops) {
  const rgb = stops.map(hexRgb);
  const lut = [];
  for (let i = 0; i < 256; i++) {
    const pos = (i / 255) * (rgb.length - 1);
    const k = Math.min(Math.floor(pos), rgb.length - 2);
    const w = pos - k;
    lut.push(rgb[k].map((c, j) => Math.round(c + (rgb[k + 1][j] - c) * w)));
  }
  return lut;
}

const TOOLBAR_CSS = `
.ots-toolbar { display: flex; justify-content: flex-end; align-items: center; gap: 2px;
  margin: 0 0 2px 0; }
.ots-toolbar .ots-sep { width: 1px; height: 18px; background: #e1e0d9; margin: 0 4px; }
.ots-tool { border: 0; background: transparent; color: #52514e; border-radius: 4px;
  width: 28px; height: 26px; padding: 0; cursor: pointer; display: inline-flex;
  align-items: center; justify-content: center; }
.ots-tool .material-icons { font-size: 18px; }
.ots-tool:hover:not(:disabled) { background: #f0efec; color: #0b0b0b; }
.ots-tool.active { background: #cde2fb; color: #184f95; }
.ots-tool:disabled { opacity: 0.35; cursor: default; }
body.body--dark .ots-tool { color: #c3c2b7; }
body.body--dark .ots-tool:hover:not(:disabled) { background: #2c2c2a; color: #f0efec; }
body.body--dark .ots-tool.active { background: #1c5cab; color: #f0efec; }
body.body--dark .ots-toolbar .ots-sep { background: #383835; }
.ots-linked { background: rgba(28, 92, 171, 0.14); border-radius: 3px; }
body.body--dark .ots-linked { background: rgba(102, 157, 234, 0.24); }
.ots-ref-label { text-decoration: underline dotted rgba(128, 128, 128, 0.7);
  text-underline-offset: 3px; }
`;

function installToolbarCss() {
  if (document.getElementById("ots-toolbar-css")) return;
  const style = document.createElement("style");
  style.id = "ots-toolbar-css";
  style.textContent = TOOLBAR_CSS;
  document.head.appendChild(style);
}

function decodeLevels(b64) {
  const bin = atob(b64 || "");
  const q = new Uint16Array(bin.length >> 1);
  for (let i = 0; i < q.length; i++) q[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
  return q;
}

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(3);
  return String(Number(v.toPrecision(SIGNIFICANT)));
}

function fmtTick(v) {
  if (v === null || v === undefined) return "";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(1);
  return String(Number(v.toPrecision(4)));
}

// Ticks of a linear axis: as many decimals as their step needs, so that close values
// (7.29999 and 7.30001 Hz) keep distinct labels; whole numbers stay whole up to 1e9 (counts:
// -400000, -402000…), beyond or below 1e-3 the labels are exponential.
function stepDecimals(step) {
  // Decimals needed to write the step exactly (negative for tens, hundreds…).
  let d = -Math.floor(Math.log10(step));
  while (d < 15 && Math.abs(Math.round(step * 10 ** d) - step * 10 ** d) > 1e-6 * step * 10 ** d) d++;
  return d;
}

function linearTicks(vals) {
  const finite = vals.filter((v) => v !== null && Number.isFinite(v));
  if (finite.length < 2) return vals.map(fmtTick);
  const step = Math.abs(finite[1] - finite[0]);
  if (!(step > 0)) return vals.map(fmtTick);
  const big = Math.max(...finite.map((v) => Math.abs(v)));
  const d = stepDecimals(step);
  if (big >= 1e9 || (big < 1e-3 && big > 0) || (big >= 1e5 && step < 1)) {
    const digits = Math.min(Math.max(Math.floor(Math.log10(big)) + d, 1), 14);
    return vals.map((v) => (v === null ? "" : v === 0 ? "0" : v.toExponential(digits)));
  }
  return vals.map((v) => (v === null ? "" : v.toFixed(Math.max(d, 0))));
}

function axisLabel(axis) {
  if (axis.time_origin) return `${axis.label || "Time"} (s from ${axis.time_origin})`;
  return axis.unit ? `${axis.label} (${axis.unit})` : axis.label;
}

function utc(originMs, seconds) {
  const d = new Date(originMs + seconds * 1000);
  return d.toISOString().replace("T", " ").replace("Z", " UTC");
}

const MARKER_COLOR = { fundamental: 1, spur: 2, harmonic: 3, maximum: 2, extreme: 2 };

export default {
  template: `<div class="ots-chart" style="width:100%"></div>`,
  props: {
    figure: Object,
    data: Object,
    palette: Object,
    height: { type: Number, default: 420 },
    zoomable: { type: Boolean, default: false },
    live: { type: Boolean, default: false },
    resourcePath: String,
  },
  mounted() {
    this.syncKey = "ots-" + Math.random().toString(36).slice(2);
    this.plots = [];
    this.mode = "zoom"; // left drag: "zoom" a range, or "pan" to move
    this.history = []; // previous views (Back), then the views undone (Forward)
    this.future = [];
    this.gestureStart = null;
    installToolbarCss();
    // The theme of the page changed (light / dark): redraw with its palette, same views.
    this.themeObserver = new MutationObserver(() => {
      if (document.body.classList.contains("body--dark") !== this.dark) this.retheme();
    });
    this.themeObserver.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    // Rows of the results panel linked to elements of this chart (hover highlight, §7.5).
    this.highlightRef = "";
    this.rowRef = "";
    this.chartRef = "";
    this.onRowOver = (e) => {
      const row = e.target && e.target.closest
        ? e.target.closest(`[data-ots-for="${this.$el.id}"]`) : null;
      const ref = row ? row.getAttribute("data-ots-ref") || "" : "";
      if (ref === this.rowRef) return;
      this.rowRef = ref;
      this.highlight(ref || this.chartRef);
    };
    document.addEventListener("mouseover", this.onRowOver);
    this.$nextTick().then(() => {
      loadResource(window.path_prefix + `${this.resourcePath}/uPlot.min.css`);
      this.build();
    });
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.$el);
  },
  unmounted() {
    if (this.observer) this.observer.disconnect();
    if (this.themeObserver) this.themeObserver.disconnect();
    document.removeEventListener("mouseover", this.onRowOver);
    this.destroy();
  },
  watch: {
    figure() { this.rebuild(); },
    data() { this.rebuild(); },
  },
  methods: {
    color(token, alpha = 1) {
      const p = this.pal || {};
      let hex = token;
      if (!token) hex = p.ink2;
      else if (token.startsWith("series:")) hex = p.series[Number(token.slice(7)) % p.series.length];
      else if (p[token]) hex = p[token];
      if (alpha >= 1 || !hex || !hex.startsWith("#")) return hex;
      const n = parseInt(hex.slice(1), 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
    },
    destroy() {
      for (const p of this.plots || []) p.u.destroy();
      this.plots = [];
      this.history = [];
      this.future = [];
      this.gestureStart = null;
      this.$el.innerHTML = "";
    },
    rebuild() {
      this.destroy();
      this.build();
    },
    retheme() {
      const view = this.captureView();
      const history = this.history;
      const future = this.future;
      const mode = this.mode;
      this.rebuild();
      this.mode = mode;
      this.history = history;
      this.future = future;
      if (view.length === this.plots.length) {
        this.plots.forEach((p, i) => {
          p.yRange = view[i].y ? { ...view[i].y } : null;
          if (view[i].min !== null) p.u.setScale("x", { min: view[i].min, max: view[i].max });
        });
      }
      this.updateToolbar();
    },
    toData(panel, d) {
      d = d || (this.data || {})[panel.id] || { x: [], series: [] };
      const h = d.heatmap;
      if (panel.heatmap && h) {
        // The image is not a series: an invisible one spans it so that both scales exist.
        return [[h.x0, h.x1], [h.y0, h.y1], ...panel.series.map(() => [null, null])];
      }
      const arrays = [d.x || []];
      panel.series.forEach((s, i) => arrays.push((d.series || [])[i] || []));
      panel.series.forEach((s, i) => {
        if (s.fill_negative) {
          const y = (d.series || [])[i] || [];
          arrays.push(y.map((v) => (v === null ? null : Math.min(v, 0))));
        }
      });
      return arrays;
    },
    build() {
      const fig = this.figure;
      this.dark = document.body.classList.contains("body--dark");
      const both = this.palette || {};
      this.pal = both.light ? both[this.dark ? "dark" : "light"] : both;
      if (!fig || !fig.panels || !fig.panels.length || !this.pal) return;
      const weights = fig.panels.reduce((a, p) => a + (p.height || 1), 0);
      const width = Math.max(320, this.$el.clientWidth || 800);
      this.$el.appendChild(this.buildToolbar());
      this.building = true; // scale changes made while building are not user zooms
      for (const panel of fig.panels) {
        const wrap = document.createElement("div");
        wrap.className = "ots-panel";
        if (panel.conditions && panel.conditions.length) {
          const c = document.createElement("div");
          c.className = "ots-conditions";
          c.style.cssText = `white-space:pre-line;font-size:11px;color:${this.pal.ink2};margin:2px 0 2px 64px`;
          c.textContent = panel.conditions.join("\n");
          wrap.appendChild(c);
        }
        const holder = document.createElement("div");
        wrap.appendChild(holder);
        const extra = this.markerLegend(panel);
        if (extra) wrap.appendChild(extra);
        const entry = { panel, u: null, initial: null, zoomed: false };
        const heat = ((this.data || {})[panel.id] || {}).heatmap;
        if (panel.heatmap && heat) {
          entry.heat = heat;
          entry.levels = decodeLevels(heat.values);
          entry.image = this.heatmapImage(heat, entry.levels);
          entry.readout = document.createElement("div");
          entry.readout.className = "ots-readout";
          entry.readout.style.cssText = `font-size:11.5px;color:${this.pal.ink2};margin:2px 0 0 64px;min-height:16px`;
          entry.readout.textContent = "Move the cursor over the map to read the time, the frequency and the level";
          wrap.appendChild(entry.readout);
          wrap.appendChild(this.colorBar(heat));
        }
        this.$el.appendChild(wrap);
        const h = Math.max(150, Math.round((this.height * (panel.height || 1)) / weights));
        const arrays = this.toData(panel);
        const u = new uPlot(this.options(panel, width, h, entry), arrays, holder);
        entry.u = u;
        if (panel.x.min !== null && panel.x.min !== undefined && panel.x.max !== null && panel.x.max !== undefined) {
          entry.initial = { min: panel.x.min, max: panel.x.max };
          this.programmatic = true;
          u.setScale("x", entry.initial);
          this.programmatic = false;
        } else {
          // Full view = extent of the data sent at build time (the scales are not set yet;
          // a zoomed time plot later receives only the visible window).
          entry.initial = this.extent(arrays[0], panel.x.scale === "log");
        }
        this.bindPanel(entry);
        this.plots.push(entry);
      }
      this.building = false;
      this.updateToolbar();
    },
    buildToolbar() {
      const bar = document.createElement("div");
      bar.className = "ots-toolbar";
      const button = (icon, title, action) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "ots-tool";
        b.title = title;
        b.innerHTML = `<i class="material-icons">${icon}</i>`;
        b.addEventListener("click", action);
        bar.appendChild(b);
        return b;
      };
      const separator = () => {
        const s = document.createElement("span");
        s.className = "ots-sep";
        bar.appendChild(s);
      };
      this.tools = {
        home: button("home", "Full view (double-click)", () => this.home()),
        back: button("arrow_back", "Previous view", () => this.stepView(-1)),
        forward: button("arrow_forward", "Next view", () => this.stepView(1)),
      };
      separator();
      this.tools.zoom = button("zoom_in", "Zoom: drag a rectangle to zoom in on it, as in matplotlib " +
        "(a flat drag zooms the abscissa only; Ctrl + wheel zooms too)", () => this.setMode("zoom"));
      this.tools.pan = button("open_with", "Move: drag to move along the axis (also the middle " +
        "button, Shift + wheel)", () => this.setMode("pan"));
      return bar;
    },
    updateToolbar() {
      if (!this.tools) return;
      this.tools.back.disabled = !(this.history || []).length;
      this.tools.forward.disabled = !(this.future || []).length;
      this.tools.zoom.classList.toggle("active", this.mode === "zoom");
      this.tools.pan.classList.toggle("active", this.mode === "pan");
      for (const p of this.plots || []) p.u.over.style.cursor = this.mode === "pan" ? "grab" : "";
    },
    setMode(mode) {
      this.mode = mode;
      this.updateToolbar();
    },
    markerLegend(panel) {
      const items = [];
      const seen = new Set();
      for (const m of panel.markers || []) {
        if (!m.label || seen.has(m.kind) || m.kind === "event") continue;
        seen.add(m.kind);
        const label = m.kind === "harmonic" ? "harmonics"
          : m.kind === "extreme" ? "extremes (peak-to-peak)" : m.label;
        items.push([m.kind === "removed_mains" ? "dash" : "dot", this.markerColor(m), label]);
      }
      for (const h of panel.hlines || []) {
        if (!h.label || seen.has("hline:" + h.label)) continue;
        seen.add("hline:" + h.label);
        items.push(["dash", this.color(h.color || "axis"), h.label]);
      }
      for (const b of panel.bands || []) {
        if (seen.has("band:" + b.kind)) continue;
        seen.add("band:" + b.kind);
        items.push(["box", b.kind === "gap" ? "rgba(137,135,129,0.35)" : this.pal.wash, b.label || b.kind]);
      }
      if (!items.length) return null;
      const row = document.createElement("div");
      row.style.cssText = `font-size:11px;color:${this.pal.ink2};margin:0 0 4px 64px;display:flex;gap:14px;flex-wrap:wrap`;
      for (const [shape, color, label] of items) {
        const sw = document.createElement("span");
        if (shape === "dash") sw.style.cssText = `display:inline-block;width:16px;border-top:2px dashed ${color};vertical-align:middle;margin-right:4px`;
        else if (shape === "dot") sw.style.cssText = `display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:4px`;
        else sw.style.cssText = `display:inline-block;width:14px;height:10px;background:${color};border:1px solid ${this.pal.axis};margin-right:4px`;
        const item = document.createElement("span");
        item.appendChild(sw);
        item.appendChild(document.createTextNode(label));
        row.appendChild(item);
      }
      return row;
    },
    markerColor(m) {
      if (m.color) return this.color(m.color);
      if (m.kind === "removed_mains") return this.pal.removed;
      if (m.kind in MARKER_COLOR) return this.color("series:" + MARKER_COLOR[m.kind]);
      return this.pal.ink2;
    },
    options(panel, width, height, entry) {
      const pal = this.pal;
      const xlog = panel.x.scale === "log";
      const ylog = panel.y.scale === "log";
      const origin = panel.x.time_origin ? Date.parse(panel.x.time_origin) : null;
      const series = [{
        label: panel.x.time_origin ? "UTC" : (panel.x.label || "x"),
        value: (u, v) => (v === null || v === undefined ? "—" : origin !== null ? utc(origin, v) : fmt(v)),
      }];
      if (entry.heat) {
        series.push({ label: "", stroke: "transparent", width: 0, points: { show: false }, value: () => "" });
      }
      for (const s of panel.series) {
        const stroke = this.color(s.color, s.alpha);
        series.push({
          label: s.label,
          stroke,
          width: s.width,
          dash: s.dash || undefined,
          spanGaps: true,
          points: s.points ? { show: true, size: 5, width: 1, stroke, fill: stroke } : { show: false },
          paths: s.points ? () => null : undefined,
          value: (u, v) => fmt(v),
        });
      }
      for (const s of panel.series) {
        if (!s.fill_negative) continue;
        series.push({
          label: s.fill_label || "below 0",
          stroke: "transparent",
          width: 0,
          fill: this.color(s.color, 0.16),
          fillTo: 0,
          spanGaps: true,
          points: { show: false },
          value: () => "",
        });
      }
      const axis = (a, size) => ({
        label: axisLabel(a),
        stroke: pal.ink2,
        grid: { show: !entry.heat, stroke: pal.grid, width: 1 },
        ticks: { stroke: pal.axis, width: 1 },
        font: "11px sans-serif",
        labelFont: "12px sans-serif",
        values: (u, vals) => (a.scale === "log" ? vals.map(fmtTick) : linearTicks(vals)),
        size,
      });
      const yFixed = panel.y.min !== null && panel.y.min !== undefined && panel.y.max !== null && panel.y.max !== undefined;
      return {
        width,
        height,
        series,
        scales: {
          x: {
            time: false,
            distr: xlog ? 3 : 1,
            log: 10,
            range: (u, mn, mx) => {
              if (mn === null || mx === null) return [xlog ? 1 : 0, xlog ? 10 : 1];
              if (mn === mx) return xlog ? [mn / 2, mx * 2] : [mn - 1, mx + 1];
              return xlog ? [Math.max(mn, 1e-15), mx] : [mn, mx];
            },
          },
          y: {
            distr: ylog ? 3 : 1,
            log: 10,
            // A range chosen by the user (rectangle zoom, vertical move) holds until the full
            // view; otherwise the fixed bounds of the layout, or the visible data.
            range: (u, mn, mx) => {
              if (entry.yRange) return [entry.yRange.min, entry.yRange.max];
              if (yFixed) return [panel.y.min, panel.y.max];
              if (mn === null || mx === null || !Number.isFinite(mn) || !Number.isFinite(mx)) {
                return ylog ? [1, 10] : [0, 1];
              }
              for (const h of panel.hlines || []) { // levels that must stay visible
                if (h.extend && Number.isFinite(h.y)) {
                  mn = Math.min(mn, h.y);
                  mx = Math.max(mx, h.y);
                }
              }
              return ylog ? uPlot.rangeLog(Math.max(mn, 1e-300), Math.max(mx, 1e-300), 10, false)
                : uPlot.rangeNum(mn, mx, 0.1, true);
            },
          },
        },
        axes: [axis(panel.x, 44), axis(panel.y, 70)],
        legend: { show: !entry.heat, live: true },
        cursor: {
          sync: panel.sync ? { key: this.syncKey + ":" + panel.sync, setSeries: false } : undefined,
          drag: { x: true, y: true, uni: 30, setScale: true },
          bind: { dblclick: () => null },
        },
        hooks: {
          drawClear: [(u) => { this.drawHeatmap(u, entry); this.drawBands(u, panel); }],
          draw: [(u) => this.drawOverlays(u, panel)],
          setScale: [(u, key) => { if (key === "x") this.onScale(entry, u); }],
          setSelect: [(u) => this.onSelect(entry, u)],
          setCursor: [(u) => { this.readHeatmap(u, entry, origin); this.hoverElement(entry, u); }],
        },
      };
    },
    // ------------------------------------------------------------ linked rows (§7.5)
    highlight(ref) {
      ref = ref || "";
      if (ref === this.highlightRef) return;
      this.highlightRef = ref;
      for (const el of document.querySelectorAll(`[data-ots-for="${this.$el.id}"]`)) {
        el.classList.toggle("ots-linked", ref !== "" && el.getAttribute("data-ots-ref") === ref);
      }
      for (const p of this.plots || []) p.u.redraw(false);
    },
    hoverElement(entry, u) {
      if (this.hoverPanel !== entry) return; // panels following the cursor of another one
      const { left, top } = u.cursor;
      const ref = left === null || left < 0 ? "" : this.elementAt(entry, u, left, top);
      if (ref === this.chartRef) return;
      this.chartRef = ref;
      if (!this.rowRef) this.highlight(ref);
    },
    elementAt(entry, u, cx, cy) {
      // Nearest linked element within a few pixels of the cursor (plotting area pixels).
      let best = "";
      let dist = 9;
      const consider = (ref, d, limit) => {
        if (ref && d < Math.min(dist, limit)) {
          best = ref;
          dist = d;
        }
      };
      for (const m of entry.panel.markers || []) {
        const x = u.valToPos(m.x, "x");
        if (m.y === null || m.y === undefined) consider(m.ref, Math.abs(x - cx), 6);
        else consider(m.ref, Math.hypot(x - cx, u.valToPos(m.y, "y") - cy), 9);
      }
      for (const h of entry.panel.hlines || []) consider(h.ref, Math.abs(u.valToPos(h.y, "y") - cy), 5);
      for (const b of entry.panel.bands || []) {
        for (const v of [b.x0, b.x1]) consider(b.ref, Math.abs(u.valToPos(v, "x") - cx), 5);
      }
      return best;
    },
    drawLabel(ctx, text, x, y, right) {
      const r = uPlot.pxRatio;
      ctx.font = `${11.5 * r}px sans-serif`;
      const w = ctx.measureText(text).width + 8 * r;
      const left = Math.min(Math.max(x + 6 * r, 2 * r), right - w - 2 * r);
      ctx.fillStyle = this.pal.surface;
      ctx.globalAlpha = 0.9;
      ctx.fillRect(left, y - 13 * r, w, 17 * r);
      ctx.globalAlpha = 1;
      ctx.fillStyle = this.pal.ink;
      ctx.fillText(text, left + 4 * r, y);
    },
    heatmapImage(h, levels) {
      // Offscreen image of the grid, row 0 (lowest ordinate) at the bottom.
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, h.cols);
      canvas.height = Math.max(1, h.rows);
      const ctx = canvas.getContext("2d");
      const img = ctx.createImageData(canvas.width, canvas.height);
      const lut = ramp(this.dark ? [...h.colors].reverse() : h.colors);
      const span = h.zmax - h.zmin;
      const range = h.vmax - h.vmin || 1;
      for (let r = 0; r < h.rows; r++) {
        const dst = (h.rows - 1 - r) * h.cols;
        for (let k = 0; k < h.cols; k++) {
          const q = levels[r * h.cols + k];
          const o = (dst + k) * 4;
          if (q === EMPTY) continue; // transparent
          const z = h.zmin + (q / LEVELS) * span;
          const u = Math.min(1, Math.max(0, (z - h.vmin) / range));
          const c = lut[Math.round(u * 255)];
          img.data[o] = c[0];
          img.data[o + 1] = c[1];
          img.data[o + 2] = c[2];
          img.data[o + 3] = 255;
        }
      }
      ctx.putImageData(img, 0, 0);
      return canvas;
    },
    colorBar(h) {
      const row = document.createElement("div");
      row.style.cssText = `display:flex;align-items:center;gap:8px;font-size:11px;color:${this.pal.ink2};margin:4px 0 2px 64px`;
      const bar = document.createElement("span");
      bar.style.cssText = `display:inline-block;width:220px;height:10px;border:1px solid ${this.pal.axis};` +
        `background:linear-gradient(to right, ${(this.dark ? [...h.colors].reverse() : h.colors).join(", ")})`;
      const lo = document.createElement("span");
      lo.textContent = fmt(h.vmin);
      const hi = document.createElement("span");
      hi.textContent = `${fmt(h.vmax)} ${h.label || ""}`;
      row.append(lo, bar, hi);
      return row;
    },
    drawHeatmap(u, entry) {
      const h = entry.heat;
      if (!h || !entry.image) return;
      const ctx = u.ctx;
      const x0 = u.valToPos(h.x0, "x", true);
      const x1 = u.valToPos(h.x1, "x", true);
      const y0 = u.valToPos(h.y0, "y", true);
      const y1 = u.valToPos(h.y1, "y", true);
      if (!Number.isFinite(x0 + x1 + y0 + y1)) return;
      ctx.save();
      ctx.beginPath();
      ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
      ctx.clip();
      // Smooth when the image is reduced (many cells per pixel), crisp cells when enlarged.
      ctx.imageSmoothingEnabled = Math.abs(x1 - x0) < h.cols || Math.abs(y0 - y1) < h.rows;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(entry.image, Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y0 - y1));
      ctx.restore();
    },
    readHeatmap(u, entry, origin) {
      const h = entry.heat;
      if (!h || !entry.readout) return;
      const { left, top } = u.cursor;
      if (left === null || left === undefined || left < 0 || top < 0) return;
      const x = u.posToVal(left, "x");
      const y = u.posToVal(top, "y");
      const col = Math.floor(((x - h.x0) / (h.x1 - h.x0)) * h.cols);
      const pos = h.log ? (Math.log10(y) - Math.log10(h.y0)) / (Math.log10(h.y1) - Math.log10(h.y0))
        : (y - h.y0) / (h.y1 - h.y0);
      const row = Math.floor(pos * h.rows);
      let level = "—";
      if (col >= 0 && col < h.cols && row >= 0 && row < h.rows) {
        const q = entry.levels[row * h.cols + col];
        if (q !== EMPTY) level = `${fmt(h.zmin + (q / LEVELS) * (h.zmax - h.zmin))} ${h.label || ""}`;
      }
      const t = origin !== null ? utc(origin, x) : fmt(x);
      const unit = entry.panel.y.unit ? ` ${entry.panel.y.unit}` : "";
      entry.readout.textContent = `${t} · ${fmt(y)}${unit} · ${level}`;
    },
    group(entry) {
      return this.plots.filter((p) => p === entry || (p.panel.sync && p.panel.sync === entry.panel.sync));
    },
    extent(xs, log) {
      let min = null;
      let max = null;
      for (const v of xs || []) {
        if (v === null || v === undefined || !Number.isFinite(v) || (log && v <= 0)) continue;
        if (min === null || v < min) min = v;
        if (max === null || v > max) max = v;
      }
      return { min, max };
    },
    fullRange(entry) {
      // Range of the complete view: the initial one, or the current data in live mode.
      const log = entry.panel.x.scale === "log";
      const range = this.live || entry.initial.min === null ? this.extent(entry.u.data[0], log)
        : entry.initial;
      return range.min === null || range.max === null || !(range.max > range.min) ? null : range;
    },
    // ------------------------------------------------------------- views and history
    captureView() {
      return this.plots.map((p) => ({
        min: p.u.scales.x.min,
        max: p.u.scales.x.max,
        y: p.yRange ? { ...p.yRange } : null,
      }));
    },
    sameRange(v, w) {
      if (!v || !w) return v === w;
      if (v.min === null || w.min === null) return v.min === w.min && v.max === w.max;
      const tol = 1e-9 * Math.max(Math.abs(v.max - v.min), Math.abs(v.max), 1e-300);
      return Math.abs(v.min - w.min) <= tol && Math.abs(v.max - w.max) <= tol;
    },
    sameView(a, b) {
      if (!a || !b || a.length !== b.length) return false;
      return a.every((v, i) => this.sameRange(v, b[i]) && this.sameRange(v.y || null, b[i].y || null));
    },
    visibleRange(entry) {
      // Extent of the data in the visible abscissa (to give the ordinate back to the data).
      const u = entry.u;
      const x = u.data[0] || [];
      if (!x.length || u.scales.x.min === null) return { min: null, max: null };
      const i0 = Math.max(0, u.valToIdx(u.scales.x.min) - 1);
      const i1 = Math.min(x.length - 1, u.valToIdx(u.scales.x.max) + 1);
      const log = entry.panel.y.scale === "log";
      let min = Infinity;
      let max = -Infinity;
      for (let s = 1; s < u.data.length; s++) {
        const ys = u.data[s] || [];
        for (let i = i0; i <= i1; i++) {
          const v = ys[i];
          if (v === null || v === undefined || !Number.isFinite(v) || (log && v <= 0)) continue;
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
      return min <= max ? { min, max } : { min: null, max: null };
    },
    setYRange(entry, range) {
      // range null: the ordinate follows the visible data (or the bounds of the layout) again.
      entry.yRange = range ? { ...range } : null;
      entry.u.setScale("y", range || this.visibleRange(entry));
    },
    remember(view) {
      // Previous view of a completed gesture: Back returns to it, Forward is cleared.
      if (!view || this.sameView(view, this.captureView())) return;
      this.history.push(view);
      if (this.history.length > 50) this.history.shift();
      this.future = [];
      this.updateToolbar();
    },
    beginGesture() {
      if (!this.gestureStart) this.gestureStart = this.captureView();
    },
    endGesture() {
      // Called after uPlot has applied the scales (its hooks run in a microtask).
      const start = this.gestureStart;
      this.gestureStart = null;
      this.remember(start);
    },
    applyView(view, follow = false) {
      // Programmatic view change; time plots reload the visible window from the server.
      this.plots.forEach((p, i) => {
        const v = view ? view[i] : null;
        p.zoomed = !follow;
        p.yRange = v && v.y ? { ...v.y } : null;
        if (!v || v.min === null || (follow && (this.live || p.initial.min === null))) {
          p.u.setData(p.u.data, true);
        } else {
          const sameX = this.sameRange({ min: p.u.scales.x.min, max: p.u.scales.x.max }, v);
          p.u.setScale("x", { min: v.min, max: v.max });
          // A new abscissa re-ranges the ordinate itself (the range function honours yRange);
          // with the same abscissa, the ordinate is set here.
          if (p.yRange || sameX) this.setYRange(p, p.yRange);
        }
      });
      if (this.zoomable && this.plots.length) {
        const v = view && view[0];
        this.$emit("zoom", { panel: this.plots[0].panel.id, min: follow || !v ? null : v.min,
          max: follow || !v ? null : v.max });
      }
    },
    home() {
      const before = this.captureView();
      const full = this.plots.map((p) => (this.live || p.initial.min === null ? null
        : { min: p.initial.min, max: p.initial.max, y: null }));
      this.applyView(full, true);
      if (!this.sameView(before, full.map((v, i) => v || before[i]))) {
        this.history.push(before);
        this.future = [];
      }
      this.updateToolbar();
    },
    stepView(direction) {
      const from = direction < 0 ? this.history : this.future;
      const to = direction < 0 ? this.future : this.history;
      if (!from.length) return;
      to.push(this.captureView());
      this.applyView(from.pop());
      this.updateToolbar();
    },
    // ------------------------------------------------------------- moving along the axis
    shifted(entry, min, max, pixels) {
      // Range moved by a number of pixels of the plotting area, kept inside the full view.
      const log = entry.panel.x.scale === "log";
      const fwd = log ? (v) => Math.log10(Math.max(v, 1e-300)) : (v) => v;
      const back = log ? (v) => 10 ** v : (v) => v;
      const width = entry.u.over.clientWidth || 1;
      const lo0 = fwd(min);
      const hi0 = fwd(max);
      const delta = (-pixels / width) * (hi0 - lo0);
      let lo = lo0 + delta;
      let hi = hi0 + delta;
      const full = this.fullRange(entry);
      if (full) {
        const f0 = fwd(full.min);
        const f1 = fwd(full.max);
        if (hi - lo < f1 - f0) {
          if (lo < f0) {
            hi += f0 - lo;
            lo = f0;
          } else if (hi > f1) {
            lo -= hi - f1;
            hi = f1;
          }
        }
      }
      return { min: back(lo), max: back(hi) };
    },
    shiftedY(entry, range, pixels) {
      // Ordinate range moved by a number of pixels (upwards positive).
      const log = entry.panel.y.scale === "log";
      const fwd = log ? (v) => Math.log10(Math.max(v, 1e-300)) : (v) => v;
      const back = log ? (v) => 10 ** v : (v) => v;
      const height = entry.u.over.clientHeight || 1;
      const lo = fwd(range.min);
      const hi = fwd(range.max);
      const delta = (pixels / height) * (hi - lo);
      return { min: back(lo + delta), max: back(hi + delta) };
    },
    startPan(entry, e) {
      const u = entry.u;
      const min = u.scales.x.min;
      const max = u.scales.x.max;
      if (min === null || max === null) return;
      const yStart = entry.yRange ? { ...entry.yRange } : null;
      const y0 = e.clientY;
      e.preventDefault(); // no text selection, no autoscroll of the middle button
      for (const p of this.plots) { // no zoom selection of uPlot meanwhile
        p.u.cursor.drag.x = false;
        p.u.cursor.drag.y = false;
      }
      this.beginGesture();
      this.userZoom = true;
      u.over.style.cursor = "grabbing";
      const x0 = e.clientX;
      const move = (ev) => {
        u.setScale("x", this.shifted(entry, min, max, ev.clientX - x0));
        // As in matplotlib, a zoomed ordinate moves with the mouse too.
        if (yStart) this.setYRange(entry, this.shiftedY(entry, yStart, ev.clientY - y0));
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        for (const p of this.plots) {
          p.u.cursor.drag.x = true;
          p.u.cursor.drag.y = true;
        }
        setTimeout(() => {
          this.userZoom = false;
          this.endGesture();
          this.updateToolbar(); // cursor of the mode
        }, 0);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up, { once: true });
    },
    bindPanel(entry) {
      const u = entry.u;
      u.over.addEventListener("mouseenter", () => { this.hoverPanel = entry; });
      u.over.addEventListener("mouseleave", () => {
        if (this.hoverPanel === entry) this.hoverPanel = null;
        this.chartRef = "";
        if (!this.rowRef) this.highlight("");
      });
      u.over.addEventListener("mousedown", (e) => {
        if (e.button === 1 || (e.button === 0 && this.mode === "pan" && !e.shiftKey)) {
          this.selecting = false;
          this.startPan(entry, e);
          return;
        }
        if (e.button !== 0) return;
        this.selecting = e.shiftKey;
        u.cursor.drag.setScale = !e.shiftKey;
        u.cursor.drag.y = !e.shiftKey; // Shift: a time window, never a rectangle
        if (e.shiftKey) {
          window.addEventListener("mouseup", () => { u.cursor.drag.y = true; }, { once: true });
          return; // window selection for an analysis, not a zoom
        }
        // A scale change until the button is released is a zoom made by the user.
        this.userZoom = true;
        this.beginGesture();
        window.addEventListener("mouseup", () => setTimeout(() => {
          this.userZoom = false;
          this.endGesture();
        }, 0), { once: true });
      }, true);
      u.over.addEventListener("dblclick", () => this.home());
      u.over.addEventListener("wheel", (e) => {
        // Ctrl + wheel zooms around the cursor; Shift + wheel or a horizontal wheel moves along
        // the axis; a plain vertical wheel scrolls the page.
        const horizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY);
        if (!e.ctrlKey && !e.shiftKey && !horizontal) return;
        e.preventDefault();
        const min = u.scales.x.min;
        const max = u.scales.x.max;
        if (min === null || max === null) return;
        let range;
        if (e.ctrlKey) {
          const full = this.fullRange(entry);
          if (!full) return;
          const log = entry.panel.x.scale === "log";
          const fwd = log ? (v) => Math.log10(Math.max(v, 1e-300)) : (v) => v;
          const back = log ? (v) => 10 ** v : (v) => v;
          const rect = u.over.getBoundingClientRect();
          const c = fwd(u.posToVal(e.clientX - rect.left, "x"));
          const k = e.deltaY < 0 ? 0.8 : 1.25;
          let lo = c - (c - fwd(min)) * k;
          let hi = c + (fwd(max) - c) * k;
          const f0 = fwd(full.min);
          const f1 = fwd(full.max);
          if (hi - lo >= f1 - f0) {
            lo = f0;
            hi = f1;
          } else if (lo < f0) {
            hi += f0 - lo;
            lo = f0;
          } else if (hi > f1) {
            lo -= hi - f1;
            hi = f1;
          }
          range = { min: back(lo), max: back(hi) };
        } else {
          const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? u.over.clientWidth : 1;
          const delta = (horizontal ? e.deltaX : e.deltaY) * unit;
          range = this.shifted(entry, min, max, -delta);
        }
        this.beginGesture();
        this.userZoom = true;
        u.setScale("x", range);
        // uPlot runs its scale hooks in a microtask: release the flag after them; a burst of
        // wheel events makes one step of the history.
        clearTimeout(this.wheelTimer);
        this.wheelTimer = setTimeout(() => { this.userZoom = false; }, 0);
        clearTimeout(this.wheelEnd);
        this.wheelEnd = setTimeout(() => this.endGesture(), 400);
      }, { passive: false });
    },
    onScale(entry, u) {
      if (this.syncing) return;
      // Only zooms of the user count: uPlot also sets the scales on resize and after building.
      const user = this.userZoom && !this.programmatic && !this.building;
      if (user) for (const p of this.group(entry)) p.zoomed = true;
      const range = { min: u.scales.x.min, max: u.scales.x.max };
      if (entry.panel.sync) {
        this.syncing = true;
        for (const p of this.plots) {
          if (p !== entry && p.panel.sync === entry.panel.sync) p.u.setScale("x", range);
        }
        this.syncing = false;
      }
      if (!user || !this.zoomable) return;
      clearTimeout(this.zoomTimer);
      this.zoomTimer = setTimeout(() => this.$emit("zoom", { panel: entry.panel.id, ...range }), 150);
    },
    onSelect(entry, u) {
      if (!this.selecting) {
        // Zoom: a rectangle that does not span the whole height also sets the ordinate.
        const height = u.over.clientHeight;
        const sel = u.select;
        if (sel.height > 0 && (sel.top > 0.5 || sel.height < height - 1)) {
          const lo = u.posToVal(sel.top + sel.height, "y");
          const hi = u.posToVal(sel.top, "y");
          if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
            entry.yRange = { min: lo, max: hi };
          }
        }
        return;
      }
      if (u.select.width <= 0) return;
      const min = u.posToVal(u.select.left, "x");
      const max = u.posToVal(u.select.left + u.select.width, "x");
      this.$emit("select", { panel: entry.panel.id, min, max });
    },
    clampX(u, px) {
      const left = u.bbox.left;
      return Math.min(Math.max(px, left), left + u.bbox.width);
    },
    drawBands(u, panel) {
      const ctx = u.ctx;
      ctx.save();
      for (const b of panel.bands || []) {
        const x0 = this.clampX(u, u.valToPos(b.x0, "x", true));
        const x1 = this.clampX(u, u.valToPos(b.x1, "x", true));
        if (!(x1 > x0)) continue;
        ctx.fillStyle = b.kind === "gap" ? "rgba(137,135,129,0.22)" : this.pal.wash;
        ctx.fillRect(x0, u.bbox.top, x1 - x0, u.bbox.height);
      }
      ctx.restore();
    },
    drawOverlays(u, panel) {
      const ctx = u.ctx;
      const r = uPlot.pxRatio;
      const top = u.bbox.top;
      const bottom = top + u.bbox.height;
      const left = u.bbox.left;
      const right = left + u.bbox.width;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, u.bbox.width, u.bbox.height);
      ctx.clip();
      const lit = (e) => e.ref && e.ref === this.highlightRef;
      const labels = [];
      for (const b of panel.bands || []) {
        if (!lit(b)) continue;
        ctx.strokeStyle = this.pal.ink2;
        ctx.lineWidth = 1.5 * r;
        ctx.setLineDash([]);
        for (const v of [b.x0, b.x1]) {
          const x = u.valToPos(v, "x", true);
          if (!(x >= left && x <= right)) continue;
          ctx.beginPath();
          ctx.moveTo(x, top);
          ctx.lineTo(x, bottom);
          ctx.stroke();
        }
        const x0 = this.clampX(u, u.valToPos(b.x0, "x", true));
        labels.push([b.label || b.ref, x0, top + 16 * r]);
      }
      for (const h of panel.hlines || []) {
        const y = u.valToPos(h.y, "y", true);
        ctx.strokeStyle = lit(h) ? this.pal.ink : this.color(h.color || "axis");
        ctx.lineWidth = (lit(h) ? 2.5 : 1) * r;
        ctx.setLineDash(lit(h) ? [] : (h.dash || []).map((d) => d * r));
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();
        if (lit(h) && h.label) labels.push([h.label, left + 4 * r, y - 6 * r]);
      }
      for (const m of panel.markers || []) {
        const x = u.valToPos(m.x, "x", true);
        if (!(x >= left && x <= right)) continue;
        const color = this.markerColor(m);
        const on = lit(m);
        if (m.y === null || m.y === undefined) {
          ctx.strokeStyle = color;
          ctx.lineWidth = (on ? 2.5 : 1) * r;
          ctx.setLineDash(on ? [] : [4 * r, 3 * r]);
          ctx.beginPath();
          ctx.moveTo(x, top);
          ctx.lineTo(x, bottom);
          ctx.stroke();
          if (on && m.label) labels.push([m.label, x, top + 16 * r]);
          continue;
        }
        const y = u.valToPos(m.y, "y", true);
        ctx.setLineDash([]);
        if (on) { // halo around the highlighted point
          ctx.fillStyle = this.color(m.color || "ink", 0.18);
          ctx.beginPath();
          ctx.arc(x, y, 11 * r, 0, 2 * Math.PI);
          ctx.fill();
        }
        ctx.fillStyle = color;
        ctx.strokeStyle = on ? this.pal.ink : this.pal.surface;
        ctx.lineWidth = (on ? 2 : 1.5) * r;
        ctx.beginPath();
        ctx.arc(x, y, (on ? 6 : 4) * r, 0, 2 * Math.PI);
        ctx.fill();
        ctx.stroke();
        if (on) labels.push([m.label || m.ref, x + 8 * r, y - 8 * r]);
        else if (m.label && m.kind === "harmonic") {
          ctx.fillStyle = this.pal.ink2;
          ctx.font = `${11 * r}px sans-serif`;
          ctx.fillText(m.label, x + 5 * r, y - 6 * r);
        }
      }
      for (const [text, x, y] of labels) this.drawLabel(ctx, text, x, Math.max(y, top + 14 * r), right);
      ctx.restore();
    },
    resize() {
      const width = Math.max(320, this.$el.clientWidth || 0);
      for (const p of this.plots || []) {
        if (Math.abs(p.u.width - width) > 2) p.u.setSize({ width, height: p.u.height });
      }
    },
    setPanelData(panelId, d) {
      const entry = (this.plots || []).find((p) => p.panel.id === panelId);
      if (!entry) return;
      this.programmatic = true;
      if (this.live && !entry.zoomed) {
        entry.u.setData(this.toData(entry.panel, d), true); // follow the new data
      } else {
        const range = { min: entry.u.scales.x.min, max: entry.u.scales.x.max };
        entry.u.setData(this.toData(entry.panel, d), false);
        entry.u.setScale("x", range);
      }
      this.programmatic = false;
    },
    exportPng(filename) {
      const plots = this.plots || [];
      if (!plots.length) return;
      const r = uPlot.pxRatio;
      const width = Math.max(...plots.map((p) => p.u.ctx.canvas.width));
      const titleH = 28 * r;
      const heights = plots.map((p) => p.u.ctx.canvas.height + (p.panel.conditions || []).length * 14 * r);
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = titleH + heights.reduce((a, b) => a + b, 0);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = this.pal.surface;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = this.pal.ink;
      ctx.font = `${14 * r}px sans-serif`;
      ctx.fillText((this.figure && this.figure.title) || "", 10 * r, 19 * r);
      let y = titleH;
      plots.forEach((p, i) => {
        ctx.fillStyle = this.pal.ink2;
        ctx.font = `${11 * r}px sans-serif`;
        for (const line of p.panel.conditions || []) {
          y += 14 * r;
          ctx.fillText(line, 64 * r, y - 3 * r);
        }
        ctx.drawImage(p.u.ctx.canvas, 0, y);
        y += p.u.ctx.canvas.height;
      });
      const a = document.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = filename || "figure.png";
      a.click();
    },
  },
};
