import { api } from '../api.js';
import { store } from '../store.js';
import { h, fmt, toast, needPlot, ensureCrops, plotBanner, bar } from '../ui.js';
import { t } from '../i18n.js';
import { U, fmtNum } from '../units.js';
import { navigate } from '../router.js';

export default {
  async mount(root) {
    const s = store.get();
    if (!s.plot) return needPlot(root, t('cropsRanked'));
    const crops = await ensureCrops();
    const meta = (id) => crops.crops.find((c) => c.id === id);
    const irr = h('select', {}, ...['rainfed', 'limited', 'full'].map((v) => h('option', { value: v, selected: v === s.scenario.irrigation }, `${t(v)} ${t('irrigation').toLowerCase()}`)));
    const area = h('input', { type: 'number', min: '0.05', step: '0.05', value: fmtNum(U.areaOut(s.scenario.area_ha), 2).replace(/,/g, ''), style: { width: '110px' } });
    const cat = h('select', {}, h('option', { value: '' }, t('allCategories')), ...['cereal', 'pulse', 'oilseed', 'vegetable', 'fibre', 'cash', 'forage', 'spice'].map((c) => h('option', { value: c, selected: c === s.category }, fmt.cap(c))));
    const allCrops = h('label', { class: 'row small muted' }, h('input', { type: 'checkbox' }), 'Include crops not usually grown in this region');
    irr.addEventListener('change', load); area.addEventListener('change', load); allCrops.querySelector('input').addEventListener('change', load);
    cat.addEventListener('change', () => { store.set({ category: cat.value }); if (store.get().rank) render(store.get().rank); });
    const out = h('div', { class: 'stack' });
    root.append(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, t('cropsRanked')), h('p', {}, t('cropsLede'))), plotBanner()),
      h('div', { class: 'row', style: { marginBottom: '18px' } }, irr, h('label', { class: 'row small muted' }, `${t('area')} (${U.areaUnit()})`, area), cat, allCrops),
      out,
    ));

    async function load() {
      out.replaceChildren(h('div', { class: 'loading' }, 'Simulating every crop at every plausible sowing date (10-20 s the first time)'));
      try {
        const rank = await api.rank({ lat: s.plot.lat, lon: s.plot.lon, country: s.plot.country_code, irrigation: irr.value, area_ha: +U.areaIn(+area.value || 1), all_crops: allCrops.querySelector('input').checked });
        store.set({ rank, site: store.get().site || null });
        if (!store.get().site && rank.site) store.set({ regionHint: rank.site.region });
        render(rank);
      } catch (err) { out.replaceChildren(h('div', { class: 'error' }, err.message)); }
    }

    function render(rank) {
      const filter = store.get().category;
      const rows = rank.ranking.filter((r) => !filter || r.category === filter);
      const maxNet = Math.max(1, ...rows.map((r) => Math.max(0, r.risk_adjusted_net)));
      const soil = rank.site.soil, clim = rank.site.climate, reg = rank.site.region;
      out.replaceChildren(
        h('div', { class: 'card tight small muted' }, `${reg.name} · soil ${soil.texture_label}, pH ${soil.ph}, organic carbon ${soil.organic_carbon_gkg} g/kg (${soil.source}) · last year ${U.rain(clim.annual_rain_mm, 0)} rain, mean ${U.temp(clim.temp_mean, 1)} · ${rows.length} crops · prices and costs: ${reg.sources[0]}`),
        h('table', {},
          h('thead', {}, h('tr', {}, h('th', {}, t('crop')), h('th', {}, t('bestSowing')), h('th', {}, t('suitability')), h('th', { class: 'r' }, t('yieldCol')), h('th', { class: 'r' }, t('adjusted')), h('th', { class: 'r' }, t('net')), h('th', { class: 'r' }, t('irrigationCol')), h('th', {}, t('watchOut')))),
          h('tbody', {}, ...rows.map((r, i) => h('tr', { class: 'clickable rank-row', onClick: () => { store.set({ scenario: { ...store.get().scenario, crop: r.crop, sow_date: r.sow_date, irrigation: rank.irrigation, area_ha: rank.area_ha }, sim: null }); toast(`${r.label} → ${t('twin')}`); navigate('twin'); } },
            h('td', {}, h('div', { class: 'lbl' }, `${i + 1}. ${r.label}`), h('div', { class: 'cat' }, `${fmt.cap(r.category)} · ${r.water} water · ${r.days} days${r.matured ? '' : ' · does not mature'}`)),
            h('td', {}, h('div', {}, `${fmt.date(r.sow_date)} `, h('span', { class: 'tag' }, r.season)), r.window && r.window.from !== r.window.to ? h('div', { class: 'dim small' }, `${t('window')}: ${fmt.date(r.window.from)} – ${fmt.date(r.window.to)}`) : h('div', { class: 'dim small' }, `${t('window')}: narrow`)),
            h('td', { style: { minWidth: '110px' } }, h('div', { class: 'small' }, r.suitability), bar(r.suitability / 100, { cls: r.suitability < 60 ? 'alert' : r.suitability < 80 ? 'gold' : '' })),
            h('td', { class: 'r' }, h('div', {}, fmtNum(U.yieldOut(r.yield_t_ha, meta(r.crop)), 1)), h('div', { class: 'dim small' }, `${U.yieldUnit(meta(r.crop))} of ${fmtNum(U.yieldOut(r.yield_potential_t_ha, meta(r.crop)), 1)}`)),
            h('td', { class: 'r', style: { minWidth: '140px' } }, h('div', { style: { color: r.risk_adjusted_net >= 0 ? 'var(--paddy)' : 'var(--alert)', fontWeight: 600 } }, U.money(r.risk_adjusted_net)), bar(Math.max(0, r.risk_adjusted_net) / maxNet, { cls: 'gold' })),
            h('td', { class: 'r muted' }, U.money(r.net), r.market_haircut < 1 ? h('div', { class: 'dim small' }, `×${r.market_haircut} price risk`) : null),
            h('td', { class: 'r' }, U.rain(r.irrigation_mm, 0)),
            h('td', { class: 'small muted', style: { maxWidth: '280px' } }, r.top_risk),
          ))),
        ),
        h('p', { class: 'small dim', style: { marginTop: '14px' } }, `Margins use ${reg.name} reference prices and typical costs per crop on ${U.area(rank.area_ha)}. Risk-adjusted margin discounts vegetables and spices for price volatility and perishability. Open a crop in the twin to set your own price and inputs.`),
      );
    }

    if (s.rank && s.rank.site?.region?.id === (s.site?.region?.id || s.regionHint?.id || s.rank.site.region.id)) render(s.rank); else load();
  },
};
