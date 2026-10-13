import { api } from '../api.js';
import { store } from '../store.js';
import { h, fmt, ensureCrops } from '../ui.js';
import { t } from '../i18n.js';
import { U, region, fmtNum } from '../units.js';

const STATES = ['Andhra Pradesh', 'Assam', 'Bihar', 'Chattisgarh', 'Goa', 'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya', 'Mizoram', 'Nagaland', 'NCT of Delhi', 'Odisha', 'Pondicherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttrakhand', 'West Bengal'];
const COMMODITIES = ['Tomato', 'Potato', 'Onion', 'Wheat', 'Paddy(Dhan)(Common)', 'Maize', 'Bhindi(Ladies Finger)', 'Brinjal', 'Cabbage', 'Cauliflower', 'Green Chilli', 'Soyabean', 'Cotton', 'Mustard', 'Bengal Gram(Gram)(Whole)', 'Arhar (Tur/Red Gram)(Whole)', 'Groundnut', 'Bajra(Pearl Millet/Cumbu)', 'Jowar(Sorghum)', 'Banana', 'Apple', 'Ginger(Green)', 'Garlic', 'Turmeric'];

export default {
  async mount(root) {
    const s = store.get();
    const reg = region();
    const crops = await ensureCrops();
    const meta = (id) => crops.crops.find((c) => c.id === id);
    const out = h('div', { class: 'stack' });
    const page = h('div', { class: 'page' });
    root.append(page);

    // Everyone gets the regional reference table; India also gets the live Agmarknet feed.
    const refBlock = h('div', { class: 'stack' }, h('div', { class: 'loading' }, 'Loading reference prices'));
    api.reference(reg.id).then((d) => {
      refBlock.replaceChildren(
        h('div', { class: 'card' },
          h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('h4', {}, `${t('referenceTitle')} · ${d.region.name}`), h('span', { class: 'tag' }, d.region.sources[0])),
          h('table', { style: { marginTop: '8px' } },
            h('thead', {}, h('tr', {}, h('th', {}, t('crop')), h('th', { class: 'r' }, `Price / ${U.priceUnit()}`), h('th', { class: 'r' }, `Cost / ${U.areaUnit()}`), h('th', { class: 'r' }, 'Attainable yield'), h('th', { class: 'r' }, `Gross / ${U.areaUnit()}`))),
            h('tbody', {}, ...d.rows.map((r) => {
              const m = meta(r.crop);
              const costArea = r.cost_ha ? r.cost_ha / (U.areaUnit() === 'acre' ? 2.47105 : 1) : null;
              const grossArea = r.yield_potential ? r.yield_potential * r.price_t / (U.areaUnit() === 'acre' ? 2.47105 : 1) : null;
              return h('tr', {}, h('td', {}, r.label, h('span', { class: 'dim small' }, ` · ${r.category}`)),
                h('td', { class: 'r', style: { fontWeight: 600 } }, `${U.money(U.priceOut(r.price_t, m), 2)}/${U.priceUnit(m)}`),
                h('td', { class: 'r muted' }, costArea ? U.money(costArea) : '—'),
                h('td', { class: 'r muted' }, r.yield_potential ? U.yield(r.yield_potential, m) : '—'),
                h('td', { class: 'r' }, grossArea ? U.money(grossArea) : '—'));
            }))),
          h('p', { class: 'small dim', style: { margin: '10px 0 0' } }, `Sources: ${d.region.sources.join('; ')}. These are the prices the simulator uses unless you override them in the twin.`),
        ),
      );
    }).catch((err) => refBlock.replaceChildren(h('div', { class: 'error' }, err.message)));

    if (reg.id !== 'IN') {
      page.append(h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, t('pricesTitle')), h('p', {}, `Farm-gate reference prices for ${reg.name} in ${reg.currency}. Live exchange feeds are not wired for this region yet; India has live mandi data.`))), refBlock);
      return;
    }

    const guessState = s.plot?.admin1 && STATES.find((x) => x.toLowerCase() === s.plot.admin1.toLowerCase());
    const state = h('select', {}, h('option', { value: '' }, 'All states (slow)'), ...STATES.map((x) => h('option', { value: x, selected: x === (s.market.state || guessState) }, x)));
    const commodity = h('input', { type: 'text', list: 'commodities', placeholder: 'Any commodity', value: s.market.commodity || '' });
    const datalist = h('datalist', { id: 'commodities' }, ...COMMODITIES.map((c) => h('option', { value: c })));
    const btn = h('button', { class: 'btn primary', type: 'submit' }, t('loadPrices'));
    const form = h('form', { class: 'market-controls', onSubmit: (e) => { e.preventDefault(); load(); } },
      h('div', { class: 'field' }, h('span', {}, t('state')), state),
      h('div', { class: 'field' }, h('span', {}, t('commodity')), commodity, datalist),
      h('div', {}, btn));
    page.append(
      h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, t('mandiTitle')), h('p', {}, 'Live modal prices reported by APMC markets to Agmarknet, summarised by commodity: the median across markets, the spread, and the market paying most.'))),
      form, h('div', { style: { height: '18px' } }), out, h('div', { style: { height: '18px' } }), refBlock);

    async function load() {
      btn.disabled = true;
      out.replaceChildren(h('div', { class: 'loading' }, 'Fetching from data.gov.in (can take up to 30 s)'));
      try {
        const data = await api.prices({ state: state.value, commodity: commodity.value.trim() });
        store.set({ market: { state: state.value, commodity: commodity.value.trim(), data } });
        render(data);
      } catch (err) { out.replaceChildren(h('div', { class: 'error' }, err.message)); }
      btn.disabled = false;
    }

    function render(d) {
      if (d.error && !d.records.length) {
        out.replaceChildren(h('div', { class: 'error' }, `${d.error}. Agmarknet's API goes down for hours at a time; FarmIQ keeps the last successful answer for each query and serves it when the API is unreachable. The reference table below still drives the simulator.`));
        return;
      }
      const note = d.cache === 'stale' ? h('div', { class: 'chip warn' }, `Cached ${Math.round((d.age_s || 0) / 60)} min ago; Agmarknet unreachable right now`) : h('div', { class: 'chip ok' }, `${d.records.length} records${d.total ? ` of ${d.total}` : ''} · live`);
      out.replaceChildren(
        note,
        h('div', { class: 'card' }, h('h4', {}, 'By commodity'), h('table', { style: { marginTop: '8px' } },
          h('thead', {}, h('tr', {}, h('th', {}, t('commodity')), h('th', { class: 'r' }, 'Markets'), h('th', { class: 'r' }, 'Median ₹/q'), h('th', { class: 'r' }, 'Range'), h('th', {}, 'Best market'), h('th', { class: 'r' }, 'vs reference'))),
          h('tbody', {}, ...d.summary.map((r) => h('tr', {},
            h('td', {}, r.commodity), h('td', { class: 'r' }, r.markets),
            h('td', { class: 'r', style: { fontWeight: 600 } }, fmtNum(r.median_modal)),
            h('td', { class: 'r muted' }, `${fmtNum(r.min)}–${fmtNum(r.max)}`),
            h('td', {}, r.best_market),
            h('td', { class: 'r' }, r.signal ? h('span', { style: { color: r.signal.delta_pct >= 0 ? 'var(--paddy)' : 'var(--alert)' } }, `${r.signal.delta_pct >= 0 ? '+' : ''}${r.signal.delta_pct}%`) : h('span', { class: 'dim' }, '—')),
          ))))),
        h('details', { class: 'card tight' }, h('summary', { style: { cursor: 'pointer', fontWeight: 600 } }, `All ${d.records.length} market reports`),
          h('table', { style: { marginTop: '8px' } }, h('thead', {}, h('tr', {}, h('th', {}, 'Market'), h('th', {}, 'District'), h('th', {}, t('commodity')), h('th', {}, 'Variety'), h('th', { class: 'r' }, 'Min'), h('th', { class: 'r' }, 'Modal'), h('th', { class: 'r' }, 'Max'), h('th', {}, 'Date'))),
            h('tbody', {}, ...d.records.map((r) => h('tr', {}, h('td', {}, r.market), h('td', {}, r.district), h('td', {}, r.commodity), h('td', { class: 'muted' }, r.variety), h('td', { class: 'r' }, fmtNum(r.min)), h('td', { class: 'r', style: { fontWeight: 600 } }, fmtNum(r.modal)), h('td', { class: 'r' }, fmtNum(r.max)), h('td', { class: 'muted' }, r.date)))))),
        h('p', { class: 'small dim' }, 'Prices in rupees per quintal. "vs reference" compares the median with the reference price FarmIQ uses in the simulator for that crop.'),
      );
    }

    if (s.market.data) render(s.market.data); else if (state.value) load();
  },
};

export { fmt };
