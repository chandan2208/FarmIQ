// Region-aware units and money. Internally everything is metric (ha, t/ha, C, mm, currency per tonne).
import { store } from './store.js';

const HA_PER_ACRE = 0.404686;
const ACRE_PER_HA = 2.47105;
const BIGHA_PER_HA = 4; // rough north-Indian bigha; shown as a hint only

export function region() {
  const s = store.get();
  return s.site?.region || s.regionHint || { id: 'WORLD', currency: 'USD', symbol: '$', locale: 'en', units: 'metric', unit_preset: { area: 'ha', yield: 't/ha', temp: 'C', rain: 'mm', price: 't' } };
}

export const U = {
  // Area
  areaUnit() { return region().unit_preset.area; },
  areaOut(ha) { return region().unit_preset.area === 'acre' ? ha * ACRE_PER_HA : ha; },
  areaIn(value) { return region().unit_preset.area === 'acre' ? value * HA_PER_ACRE : value; },
  area(ha, d = 2) { const r = region().unit_preset.area; return `${fmtNum(U.areaOut(ha), d)} ${r}${r === 'acre' && region().id === 'IN' ? ` (~${fmtNum(ha * BIGHA_PER_HA, 1)} bigha)` : ''}`; },

  // Yield
  yieldUnit(crop) {
    const p = region().unit_preset.yield;
    if (p === 'bu/acre') return crop?.bu_kg ? 'bu/acre' : 'ton/acre';
    return p;
  },
  yieldOut(tHa, crop) {
    const p = region().unit_preset.yield;
    if (p === 'q/acre') return tHa * 10 / ACRE_PER_HA;
    if (p === 'bu/acre') return crop?.bu_kg ? (tHa * 1000 / crop.bu_kg) / ACRE_PER_HA : (tHa * 1.10231) / ACRE_PER_HA;
    return tHa;
  },
  yield(tHa, crop, d = 1) { return `${fmtNum(U.yieldOut(tHa, crop), d)} ${U.yieldUnit(crop)}`; },

  // Temperature and rain
  temp(c, d = 0) { return region().unit_preset.temp === 'F' ? `${fmtNum(c * 9 / 5 + 32, d)}°F` : `${fmtNum(c, d)}°C`; },
  tempVal(c) { return region().unit_preset.temp === 'F' ? Math.round(c * 9 / 5 + 32) : Math.round(c); },
  tempUnit() { return region().unit_preset.temp === 'F' ? '°F' : '°C'; },
  rain(mm, d = 1) { return region().unit_preset.rain === 'in' ? `${fmtNum(mm / 25.4, d + 1)} in` : `${fmtNum(mm, d)} mm`; },

  // Money
  money(x, d = 0) {
    if (x === null || x === undefined || Number.isNaN(x)) return '—';
    const r = region();
    try { return new Intl.NumberFormat(r.locale || 'en', { style: 'currency', currency: r.currency || 'USD', maximumFractionDigits: d, minimumFractionDigits: 0 }).format(x); }
    catch (_) { return `${r.symbol || ''}${fmtNum(x, d)}`; }
  },
  priceUnit(crop) {
    const p = region().unit_preset.price;
    if (p === 'bu') return crop?.bu_kg ? 'bu' : 'ton';
    return p === 'quintal' ? 'quintal' : 't';
  },
  priceOut(perTonne, crop) {
    const p = region().unit_preset.price;
    if (p === 'quintal') return perTonne / 10;
    if (p === 'bu') return crop?.bu_kg ? perTonne * crop.bu_kg / 1000 : perTonne * 0.907;
    return perTonne;
  },
  priceIn(local, crop) {
    const p = region().unit_preset.price;
    if (p === 'quintal') return local * 10;
    if (p === 'bu') return crop?.bu_kg ? local * 1000 / crop.bu_kg : local / 0.907;
    return local;
  },
  price(perTonne, crop) { return `${U.money(U.priceOut(perTonne, crop), 2)}/${U.priceUnit(crop)}`; },
};

export function fmtNum(n, d = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat(region().locale || 'en', { maximumFractionDigits: d, minimumFractionDigits: 0 }).format(n);
}
