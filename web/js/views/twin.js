import { api } from '../api.js';
import { store } from '../store.js';
import { h, fmt, toast, needPlot, ensureCrops, ensureSiteData, plotBanner, seasonChart, bar } from '../ui.js';
import { t } from '../i18n.js';
import { U, fmtNum, region } from '../units.js';

let scene, playTimer, els = {};

const STAGE = () => ({ ini: 'Establishment', dev: 'Vegetative growth', mid: 'Flowering and fill', late: 'Ripening' });

// Default sowing date and crop for the plot's region and today's date.
function defaults(regionRec) {
  const now = new Date(), m = now.getMonth() + 1, y = now.getFullYear();
  const id = regionRec?.id || 'WORLD';
  if (id === 'IN') {
    if (m >= 5 && m <= 8) return { crop: 'rice', sow: `${y}-06-20` };
    if (m >= 9 || m <= 1) return { crop: 'wheat', sow: `${m >= 9 ? y : y - 1}-11-05` };
    return { crop: 'maize', sow: `${y}-03-01` };
  }
  if (id === 'US') return m >= 8 || m <= 2 ? { crop: 'wheat', sow: `${m >= 8 ? y : y - 1}-09-25` } : { crop: 'maize', sow: `${y}-05-01` };
  if (id === 'UK') return m >= 7 || m <= 1 ? { crop: 'wheat', sow: `${m >= 7 ? y : y - 1}-10-05` } : { crop: 'barley', sow: `${y}-03-10` };
  if (id === 'EU') return m >= 7 || m <= 1 ? { crop: 'wheat', sow: `${m >= 7 ? y : y - 1}-10-10` } : { crop: 'maize', sow: `${y}-04-20` };
  return m >= 8 || m <= 1 ? { crop: 'wheat', sow: `${m >= 8 ? y : y - 1}-10-15` } : { crop: 'maize', sow: `${y}-04-15` };
}

export default {
  async mount(root) {
    const s = store.get();
    if (!s.plot) return needPlot(root, t('fieldTwin'));
    const crops = await ensureCrops();
    if (!s.scenario.sow_date) {
      const d = defaults(s.site?.region || s.regionHint || { id: s.plot.region || 'WORLD' });
      store.set({ scenario: { ...s.scenario, sow_date: d.sow, crop: d.crop } });
    }
    const stage = h('div', { class: 'scene' });
    const hud = h('div', { class: 'hud' });
    const dock = h('div', { class: 'dock' });
    const side = h('aside', { class: 'side' });
    root.append(h('div', { class: 'twin' }, h('div', { class: 'stage' }, stage, hud, dock), side));
    els = { stage, hud, dock, side, crops };
    renderSide();
    try {
      const { FieldScene } = await import('../three/scene.js');
      scene = new FieldScene().mount(stage);
      scene.setArea(store.get().scenario.area_ha);
    } catch (err) {
      stage.append(h('div', { class: 'scene-fallback' }, h('p', {}, `3D view unavailable (${err.message}). Results and the timeline still work below.`)));
    }
    if (store.get().sim) showSim(store.get().sim); else run();
  },
  unmount() { clearInterval(playTimer); scene?.dispose(); scene = null; els = {}; },
};

function cropMeta(id) { return els.crops.crops.find((c) => c.id === id); }

function renderSide(status) {
  const { scenario, sim, compare, site, regionHint } = store.get();
  const reg = site?.region || regionHint;
  const { crops, textures } = els.crops;
  const regional = new Set(reg?.crops || []);
  const byCat = {};
  crops.forEach((c) => (byCat[regional.size && !regional.has(c.id) ? `${c.category} (other regions)` : c.category] ||= []).push(c));
  const cats = Object.keys(byCat).sort((a, b) => (a.includes('other') ? 1 : 0) - (b.includes('other') ? 1 : 0));
  const cropSel = h('select', { name: 'crop' }, ...cats.map((cat) => h('optgroup', { label: fmt.cap(cat) }, ...byCat[cat].map((c) => h('option', { value: c.id, selected: c.id === scenario.crop }, c.label)))));
  const sow = h('input', { type: 'date', name: 'sow_date', value: scenario.sow_date });
  const area = h('input', { type: 'number', name: 'area', min: '0.05', step: '0.05', value: fmtNum(U.areaOut(scenario.area_ha), 2).replace(/,/g, '') });
  const nApp = h('input', { type: 'number', name: 'n', min: '0', step: '5', placeholder: 'recommended', value: scenario.n_applied_kg_ha ?? '' });
  const irr = h('div', { class: 'seg' }, ...['rainfed', 'limited', 'full'].map((v) => h('button', { type: 'button', class: v === scenario.irrigation ? 'on' : '', onClick: (e) => { irr.querySelectorAll('button').forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); irr.dataset.value = v; } }, t(v))));
  irr.dataset.value = scenario.irrigation;
  const soilTex = h('select', { name: 'texture' }, h('option', { value: '' }, `${t('satellite')}: ${site?.soil?.texture_label || '…'}`), ...Object.entries(textures).map(([k, v]) => h('option', { value: k }, v)));
  const price = h('input', { type: 'number', name: 'price', min: '0', step: '0.01', placeholder: 'regional', value: scenario.price_local ?? '' });
  const meta = cropMeta(scenario.crop);
  const form = h('form', { class: 'stack', onSubmit: (e) => { e.preventDefault(); run(); } },
    h('div', { class: 'field' }, h('span', {}, t('crop')), cropSel),
    h('div', { class: 'grid two', style: { gap: '10px' } },
      h('div', { class: 'field' }, h('span', {}, t('sowingDate')), sow),
      h('div', { class: 'field' }, h('span', {}, `${t('area')} (${U.areaUnit()})`), area)),
    h('div', { class: 'field' }, h('span', {}, t('irrigation')), irr),
    h('div', { class: 'grid two', style: { gap: '10px' } },
      h('div', { class: 'field' }, h('span', {}, `${t('nitrogen')} (kg/ha)`), nApp),
      h('div', { class: 'field' }, h('span', {}, t('soilTexture')), soilTex)),
    h('div', { class: 'field' }, h('span', {}, `Price (${region().symbol}/${U.priceUnit(meta)})`), price),
    h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'submit' }, t('runSeason')), status ? h('span', { class: 'loading' }, status) : null),
  );
  cropSel.addEventListener('change', () => { price.placeholder = 'regional'; price.value = ''; });
  els.form = { cropSel, sow, area, nApp, irr, soilTex, price };
  const results = h('div', { class: 'stack', id: 'twin-results' });
  els.results = results;
  els.side.replaceChildren(h('div', {}, h('h2', {}, t('fieldTwin')), plotBanner()), form, results, compareBlock(compare));
  if (sim) fillResults(sim);
}

function readScenario() {
  const f = els.form;
  const meta = cropMeta(f.cropSel.value);
  const priceLocal = f.price.value === '' ? null : +f.price.value;
  return {
    crop: f.cropSel.value, sow_date: f.sow.value, area_ha: +U.areaIn(+f.area.value || 1), irrigation: f.irr.dataset.value,
    n_applied_kg_ha: f.nApp.value === '' ? null : +f.nApp.value,
    price_t: priceLocal === null ? null : U.priceIn(priceLocal, meta), price_local: priceLocal,
  };
}

async function run() {
  const { plot } = store.get();
  const scenario = readScenario();
  const texture = els.form.soilTex.value || null;
  store.set({ scenario });
  const btn = els.side.querySelector('button[type=submit]');
  btn.disabled = true;
  const status = h('span', { class: 'loading' }, store.get().site ? t('simulating') : t('readingSoil'));
  btn.after(status);
  try {
    await ensureSiteData();
    const { price_local, ...payload } = scenario;
    const sim = await api.simulate({ lat: plot.lat, lon: plot.lon, country: plot.country_code, scenario: payload, soil: texture ? { texture } : null });
    store.set({ sim });
    scene?.setArea(scenario.area_ha);
    showSim(sim);
    renderSide();
  } catch (err) {
    status.remove(); btn.disabled = false;
    toast(err.message, 5000);
  }
}

function showSim(sim) {
  const meta = cropMeta(sim.crop);
  scene?.setCrop(sim.crop, meta?.category || 'cereal');
  fillResults(sim);
  buildDock(sim);
  setDayIndex(sim, Math.min(sim.daily.length - 1, Math.max(0, todayIndex(sim))), true);
}

function todayIndex(sim) {
  const today = new Date().toISOString().slice(0, 10);
  const i = sim.daily.findIndex((d) => d.date >= today);
  return i < 0 ? sim.daily.length - 1 : i;
}

function fillResults(sim) {
  const e = sim.economics, fac = sim.factors, meta = cropMeta(sim.crop);
  const chart = seasonChart(sim.daily, { onHover: (i) => setDayIndex(sim, i) });
  els.chart = chart;
  const factorRows = [[t('water'), fac.water, 'water'], [t('nutrients'), fac.nutrients, ''], [t('soilPh'), fac.ph, ''], [t('temperature'), fac.temperature, ''], [t('heatFlower'), fac.heat, ''], [t('coldNights'), fac.cold, ''], [t('texture'), fac.texture, '']]
    .map(([lbl, v, cls]) => h('div', { class: 'f' }, h('span', {}, lbl), bar(v, { cls: v < 0.8 ? 'alert' : v < 0.95 ? 'gold' : cls }), h('span', { class: 'r' }, fmt.pct(v))));
  const ended = sim.killed_on ? `Killed by frost ${fmt.dateLong(sim.killed_on)}` : sim.matured_on ? `Matures ${fmt.dateLong(sim.matured_on)}` : 'Does not mature in the window';
  els.results.replaceChildren(
    h('div', { class: 'card' },
      h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h3', {}, sim.label), h('span', { class: `chip ${sim.suitability >= 80 ? 'ok' : sim.suitability >= 60 ? 'warn' : 'bad'}` }, `${t('suitability')} ${sim.suitability}`)),
      h('div', { class: 'grid three', style: { marginTop: '12px', gap: '10px' } },
        h('div', { class: 'stat' }, h('span', { class: 'num' }, fmtNum(U.yieldOut(sim.yield_t_ha, meta), 1)), h('span', { class: 'lbl' }, `${U.yieldUnit(meta)} (potential ${fmtNum(U.yieldOut(sim.yield_potential_t_ha, meta), 1)})`)),
        h('div', { class: 'stat' }, h('span', { class: 'num', style: { color: e.net >= 0 ? 'var(--paddy)' : 'var(--alert)' } }, U.money(e.net)), h('span', { class: 'lbl' }, `${t('netOn')} ${U.area(sim.area_ha)}`)),
        h('div', { class: 'stat' }, h('span', { class: 'num' }, e.roi_pct === null ? '—' : `${e.roi_pct}%`), h('span', { class: 'lbl' }, t('returnOnCost'))),
      ),
      h('div', { class: 'divider' }),
      h('div', { class: 'small muted' }, `Revenue ${U.money(e.revenue)} at ${U.price(e.price_t, meta)}. Cost ${U.money(e.cost)} including ${U.money(e.irrigation_cost)} for ${U.rain(sim.water.irrigation_mm, 0)} of irrigation over ${sim.water.irrigation_events} events. Rain in season ${U.rain(sim.water.rain_mm, 0)}. ${ended}. ${sim.season ? `Season: ${fmt.cap(sim.season)}.` : ''}`),
    ),
    h('div', { class: 'card' }, h('h4', {}, t('season')), h('div', { class: 'small muted', style: { margin: '2px 0 8px' } }, 'Green: canopy. Blue dashed: root-zone water. Blue bars: rain. Red dots: stress days. Hover to scrub the twin.'), chart,
      h('div', { class: 'small dim' }, `Weather: ${sim.sources.observed} observed days, ${sim.sources.forecast} forecast, ${sim.sources.climatology} from last year's climatology.`)),
    h('div', { class: 'card' }, h('h4', {}, t('limits')), h('div', { class: 'factors', style: { marginTop: '10px' } }, ...factorRows)),
    h('div', { class: 'card' }, h('h4', {}, t('risks')), h('div', { class: 'risk', style: { marginTop: '10px' } }, ...sim.risks.map((r) => h('div', { class: `item ${r.level}` }, h('i'), h('span', {}, r.text))))),
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onClick: () => addCompare(sim) }, t('addCompare')),
      h('a', { class: 'btn ghost', href: '#/intel' }, t('rankAll')),
      h('a', { class: 'btn ghost', href: '#/advisor' }, t('askAdvisor'))),
    h('details', { class: 'card tight' }, h('summary', { style: { cursor: 'pointer', fontWeight: 600 } }, `Growing ${sim.label}: field notes`),
      h('div', { class: 'stack small', style: { marginTop: '10px' } }, ...Object.entries(sim.tips).map(([k, v]) => h('div', {}, h('b', {}, fmt.cap(k) + '. '), v)))),
  );
}

function buildDock(sim) {
  const n = sim.daily.length;
  const range = h('input', { type: 'range', min: 0, max: n - 1, value: 0, 'aria-label': 'Season day' });
  const play = h('button', { class: 'btn sm', type: 'button' }, t('play'));
  const lbl = h('span', { class: 'lbl' });
  const stages = h('div', { class: 'stages' });
  const counts = { ini: 0, dev: 0, mid: 0, late: 0 };
  sim.daily.forEach((d) => counts[d.stage]++);
  for (const k of ['ini', 'dev', 'mid', 'late']) stages.append(h('i', { class: k, style: { width: `${counts[k] / n * 100}%` }, title: STAGE()[k] }));
  const maxR = Math.max(10, ...sim.daily.map((d) => d.rain));
  const rain = h('div', { class: 'rain' }, ...sim.daily.map((d) => h('i', { class: d.stress > 0.05 ? 'stress' : '', style: { height: `${Math.max(2, (d.stress > 0.05 ? d.stress : d.rain / maxR) * 100)}%` } })));
  range.addEventListener('input', () => setDayIndex(sim, +range.value));
  play.addEventListener('click', () => {
    if (playTimer) { clearInterval(playTimer); playTimer = null; play.textContent = t('play'); return; }
    play.textContent = t('pause');
    if (+range.value >= n - 1) range.value = 0;
    playTimer = setInterval(() => { const v = +range.value + 1; if (v >= n) { clearInterval(playTimer); playTimer = null; play.textContent = t('play'); return; } range.value = v; setDayIndex(sim, v); }, 90);
  });
  els.dock.replaceChildren(h('div', { class: 'top' }, play, lbl, range), stages, rain);
  els.range = range; els.dockLbl = lbl;
}

function setDayIndex(sim, i, immediate = false) {
  const d = sim.daily[i];
  if (!d) return;
  if (els.range && +els.range.value !== i) els.range.value = i;
  els.chart?.setCursor(i);
  els.dockLbl.textContent = `${t('day')} ${d.day} · ${fmt.date(d.date)}`;
  scene?.setDay(d, { immediate });
  const src = { observed: 'observed weather', forecast: 'forecast', climatology: 'climatology' }[d.src];
  els.hud.replaceChildren(h('div', { class: 'card' },
    h('div', { class: 'day-title' }, STAGE()[d.stage]),
    h('div', { class: 'small muted' }, `${fmt.dateLong(d.date)} · ${src}`),
    h('div', { class: 'metrics' },
      h('span', {}, `${t('canopy')} `, h('b', {}, fmt.pct(d.canopy))), h('span', {}, `${t('soilWater')} `, h('b', {}, fmt.pct(d.water))),
      h('span', {}, `${t('rain')} `, h('b', {}, U.rain(d.rain))), h('span', {}, `${t('stress')} `, h('b', { style: { color: d.stress > 0.05 ? 'var(--alert)' : 'inherit' } }, fmt.pct(d.stress))),
      h('span', {}, `${t('temp')} `, h('b', {}, `${U.tempVal(d.tmin)}–${U.tempVal(d.tmax)}${U.tempUnit()}`)), h('span', {}, 'GDD ', h('b', {}, d.gdd)),
      d.irrigation > 0 ? h('span', { style: { color: 'var(--water)' } }, `${t('irrigate')} ${U.rain(d.irrigation)}`) : null,
    )));
}

function addCompare(sim) {
  const { compare } = store.get();
  if (compare.length >= 6) { toast('Comparison holds six scenarios. Remove one first.'); return; }
  const entry = { id: Date.now(), crop: sim.crop, label: sim.label, sow_date: sim.sow_date, irrigation: sim.irrigation, area_ha: sim.area_ha, yield_t_ha: sim.yield_t_ha, net: sim.economics.net, roi: sim.economics.roi_pct, irrigation_mm: sim.water.irrigation_mm, suitability: sim.suitability, matured: !!sim.matured_on };
  store.set({ compare: [...compare, entry] });
  renderSide();
  toast(t('addCompare'));
}

function compareBlock(compare) {
  if (!compare.length) return h('div', { class: 'empty small' }, 'Run a few scenarios and add them here to compare crops, sowing dates and irrigation side by side.');
  const best = Math.max(...compare.map((c) => c.net));
  return h('div', { class: 'card' }, h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h4', {}, 'Comparison'), h('button', { class: 'btn ghost sm', type: 'button', onClick: () => { store.set({ compare: [] }); renderSide(); } }, 'Clear')),
    h('table', { class: 'compare-table', style: { marginTop: '8px' } },
      h('thead', {}, h('tr', {}, h('th', {}, 'Scenario'), h('th', { class: 'r' }, t('yieldCol')), h('th', { class: 'r' }, t('net')), h('th', { class: 'r' }, t('irrigationCol')), h('th'))),
      h('tbody', {}, ...compare.map((c) => h('tr', { class: 'clickable', onClick: () => { store.set({ scenario: { ...store.get().scenario, crop: c.crop, sow_date: c.sow_date, irrigation: c.irrigation, area_ha: c.area_ha } }); renderSide(); run(); } },
        h('td', {}, h('div', {}, c.label), h('div', { class: 'dim small' }, `${fmt.date(c.sow_date)} · ${t(c.irrigation)}${c.matured ? '' : ' · does not mature'}`)),
        h('td', { class: 'r' }, fmtNum(U.yieldOut(c.yield_t_ha, cropMeta(c.crop)), 1)),
        h('td', { class: 'r', style: { color: c.net === best ? 'var(--paddy)' : 'inherit', fontWeight: c.net === best ? 600 : 400 } }, U.money(c.net)),
        h('td', { class: 'r' }, U.rain(c.irrigation_mm, 0)),
        h('td', {}, h('button', { class: 'btn ghost sm', type: 'button', 'aria-label': 'Remove', onClick: (e) => { e.stopPropagation(); store.set({ compare: store.get().compare.filter((x) => x.id !== c.id) }); renderSide(); } }, '×')))))));
}
