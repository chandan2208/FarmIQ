// DOM helpers, formatting, toast, modal, plot picker and small SVG charts.
import { api } from './api.js';
import { store } from './store.js';
import { t } from './i18n.js';

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const fmt = {
  inr: (n) => (n === null || n === undefined) ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n),
  num: (n, d = 0) => (n === null || n === undefined || Number.isNaN(n)) ? '—' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }).format(n),
  pct: (x, d = 0) => (x === null || x === undefined) ? '—' : `${(x * 100).toFixed(d)}%`,
  date: (iso) => iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : '—',
  dateLong: (iso) => iso ? new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—',
  weekday: (iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short' }),
  cap: (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : '',
};

let toastTimer;
export function toast(msg, ms = 2600) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

export function modal(content, { onClose } = {}) {
  const root = document.getElementById('modal-root');
  const back = h('div', { class: 'modal-back', role: 'dialog', 'aria-modal': 'true' });
  const box = h('div', { class: 'modal' }, content);
  back.append(box);
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); onClose?.(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  back.addEventListener('click', (e) => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey);
  root.append(back);
  const first = box.querySelector('input, button');
  first?.focus();
  return close;
}

// Plot picker: search a place (Open-Meteo geocoding) or use device location.
export function openPlotPicker({ required = false } = {}) {
  const input = h('input', { type: 'search', placeholder: 'Village, town or district. e.g. Araria, Bihar', autocomplete: 'off' });
  const results = h('div', { class: 'geo-results' });
  const status = h('div', { class: 'small muted', style: { marginTop: '8px' } });
  const gps = h('button', { class: 'btn ghost sm', type: 'button' }, 'Use my location');
  const wrap = h('div', {},
    h('h2', {}, 'Where is your plot?'),
    h('p', { class: 'muted' }, 'FarmIQ reads the soil under this point from satellite maps and the climate from weather reanalysis. Pick the nearest place, or use GPS while standing in the field.'),
    h('div', { class: 'row' }, h('div', { style: { flex: '1 1 260px' } }, input), gps),
    status, results,
  );
  let close;
  const choose = (p) => {
    store.set({ plot: p, site: null, forecast: null, sim: null, rank: null, compare: [], regionHint: null, scenario: { ...store.get().scenario, sow_date: null } });
    updatePlotChip();
    close?.();
    toast(`${t('setPlot')}: ${p.name}`);
    // Learn the region right away so units and language are right before the slow soil call returns.
    api.crops().then((c) => { const r = c.regions[p.region || 'WORLD']; if (r) store.set({ regionHint: { ...r, id: p.region || 'WORLD' } }); }).catch(() => {});
  };
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { results.innerHTML = ''; return; }
    timer = setTimeout(async () => {
      status.textContent = 'Searching…';
      try {
        const { results: rs } = await api.geocode(q);
        status.textContent = rs.length ? '' : 'No places found. Try the district name.';
        results.replaceChildren(...rs.map((r) => h('button', { type: 'button', onClick: () => choose({ name: r.name, admin1: r.admin1, country: r.country, country_code: r.country_code, region: r.region, lat: r.lat, lon: r.lon }) },
          r.name, h('small', {}, [r.admin2, r.admin1, r.country].filter(Boolean).join(', ')))));
      } catch (err) { status.textContent = err.message; }
    }, 260);
  });
  gps.addEventListener('click', () => {
    if (!navigator.geolocation) { status.textContent = 'This browser has no location access.'; return; }
    status.textContent = 'Reading GPS…';
    navigator.geolocation.getCurrentPosition(
      (pos) => choose({ name: `Field at ${pos.coords.latitude.toFixed(3)}, ${pos.coords.longitude.toFixed(3)}`, admin1: 'GPS', lat: +pos.coords.latitude.toFixed(5), lon: +pos.coords.longitude.toFixed(5) }),
      (err) => { status.textContent = `Location failed: ${err.message}`; },
      { enableHighAccuracy: true, timeout: 12000 },
    );
  });
  close = modal(wrap, { onClose: () => { if (required && !store.get().plot) { /* stay */ } } });
}

export function updatePlotChip() {
  const { plot } = store.get();
  const chip = document.getElementById('plot-chip');
  const name = document.getElementById('plot-chip-name');
  chip.classList.toggle('set', !!plot);
  name.textContent = plot ? plot.name : t('setPlot');
}

export function plotBanner() {
  const { plot, site } = store.get();
  const region = site?.region || store.get().regionHint;
  return h('div', { class: 'row', style: { marginBottom: '18px' } },
    plot
      ? h('span', { class: 'chip ok' }, `${plot.name}${plot.admin1 && plot.admin1 !== 'GPS' ? ', ' + plot.admin1 : ''}${region ? ' · ' + region.name : ''} · ${plot.lat.toFixed(3)}, ${plot.lon.toFixed(3)}`)
      : h('span', { class: 'chip bad' }, t('noPlot')),
    h('button', { class: 'btn ghost sm', type: 'button', onClick: () => openPlotPicker() }, plot ? t('changePlot') : t('setPlot')),
  );
}

export function needPlot(root, title) {
  root.append(h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, title))),
    h('div', { class: 'empty' },
      h('p', {}, t('needPlot')),
      h('button', { class: 'btn primary', type: 'button', onClick: () => openPlotPicker() }, t('setLocation')),
    ),
  ));
}

// Ensures site profile and forecast are loaded for the current plot.
export async function ensureSiteData({ forecast = true } = {}) {
  const s = store.get();
  if (!s.plot) return null;
  const tasks = [];
  if (!s.site) tasks.push(api.profile(s.plot.lat, s.plot.lon, s.plot.country_code).then((site) => store.set({ site, regionHint: site.region })));
  if (forecast && !s.forecast) tasks.push(api.forecast(s.plot.lat, s.plot.lon, s.scenario?.crop).then((f) => store.set({ forecast: f })));
  await Promise.all(tasks);
  return store.get();
}

export async function ensureCrops() {
  if (!store.get().crops) store.set({ crops: await api.crops() });
  return store.get().crops;
}

// ---------- charts (inline SVG, brand colours) ----------
const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };

// Season chart: canopy area, soil water line, rain bars, stress markers.
export function seasonChart(daily, { width = 720, height = 180, onHover } = {}) {
  const pad = { l: 8, r: 8, t: 12, b: 22 };
  const w = width - pad.l - pad.r, hgt = height - pad.t - pad.b;
  const n = daily.length;
  const x = (i) => pad.l + (i / Math.max(n - 1, 1)) * w;
  const y = (v) => pad.t + (1 - v) * hgt;
  const maxRain = Math.max(10, ...daily.map((d) => d.rain));
  const root = svg('svg', { viewBox: `0 0 ${width} ${height}`, width: '100%', height, role: 'img', 'aria-label': 'Season chart' });
  daily.forEach((d, i) => {
    if (d.rain > 0) root.append(svg('rect', { x: x(i) - w / n / 2, y: y(d.rain / maxRain), width: Math.max(1, w / n), height: hgt - (y(d.rain / maxRain) - pad.t), fill: '#6FB3D9', opacity: 0.45 }));
    if (d.irrigation > 0) root.append(svg('rect', { x: x(i) - 1, y: pad.t, width: 2, height: 6, fill: '#6FB3D9' }));
  });
  const area = `M${x(0)},${y(0)} ` + daily.map((d, i) => `L${x(i)},${y(d.canopy)}`).join(' ') + ` L${x(n - 1)},${y(0)} Z`;
  root.append(svg('path', { d: area, fill: '#8CC26B', opacity: 0.35 }));
  root.append(svg('path', { d: 'M' + daily.map((d, i) => `${x(i)},${y(d.canopy)}`).join(' L'), fill: 'none', stroke: '#8CC26B', 'stroke-width': 2 }));
  root.append(svg('path', { d: 'M' + daily.map((d, i) => `${x(i)},${y(d.water)}`).join(' L'), fill: 'none', stroke: '#6FB3D9', 'stroke-width': 1.6, 'stroke-dasharray': '3 3' }));
  daily.forEach((d, i) => { if (d.stress > 0.05) root.append(svg('circle', { cx: x(i), cy: y(1 - d.stress), r: 2.2, fill: '#E8694A' })); });
  const cursor = svg('line', { x1: 0, x2: 0, y1: pad.t, y2: pad.t + hgt, stroke: '#ECE7D8', 'stroke-width': 1, opacity: 0 });
  root.append(cursor);
  // month ticks
  daily.forEach((d, i) => {
    if (d.date.endsWith('-01') || i === 0) {
      const t = svg('text', { x: x(i), y: height - 6, fill: '#ECE7D8', opacity: 0.55, 'font-size': 11, 'text-anchor': i === 0 ? 'start' : 'middle' });
      t.textContent = new Date(d.date + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short' });
      root.append(t);
    }
  });
  if (onHover) {
    root.addEventListener('mousemove', (e) => {
      const r = root.getBoundingClientRect();
      const i = Math.round(((e.clientX - r.left) / r.width * width - pad.l) / w * (n - 1));
      if (i >= 0 && i < n) { cursor.setAttribute('x1', x(i)); cursor.setAttribute('x2', x(i)); cursor.setAttribute('opacity', 0.6); onHover(i); }
    });
    root.addEventListener('mouseleave', () => cursor.setAttribute('opacity', 0));
  }
  root.setCursor = (i) => { cursor.setAttribute('x1', x(i)); cursor.setAttribute('x2', x(i)); cursor.setAttribute('opacity', 0.6); };
  return root;
}

export function bar(value, { cls = '' } = {}) {
  return h('div', { class: `bar ${cls}` }, h('i', { style: { width: `${Math.max(0, Math.min(100, value * 100))}%` } }));
}
