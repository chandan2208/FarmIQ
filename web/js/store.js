// Single reactive store persisted to localStorage. Views subscribe; setters patch.
const KEY = 'farmiq.v2';
const listeners = new Set();

const defaults = {
  plot: null,            // { name, admin1, lat, lon }
  site: null,            // /api/site/profile
  forecast: null,        // /api/weather/forecast
  crops: null,           // /api/twin/crops
  scenario: { crop: 'rice', sow_date: null, area_ha: 1, irrigation: 'limited', n_applied_kg_ha: null },
  sim: null,             // last simulation
  compare: [],           // saved scenarios for side-by-side
  rank: null,
  rankSeason: 'kharif',
  market: { state: '', commodity: '', data: null },
  chat: [],
  lang: null,            // ui language; null = detect from region/browser
  regionHint: null,      // region record from geocode, before the site profile loads
  category: '',          // crop category filter on the ranking page
  lastRoute: 'twin',
};

let state = load();

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      return { ...defaults, ...saved, scenario: { ...defaults.scenario, ...(saved.scenario || {}) } };
    }
  } catch (_) { /* private mode or corrupt */ }
  return { ...defaults };
}

function persist() {
  try {
    // Do not persist bulky, refetchable data.
    const { forecast, rank, crops, ...rest } = state;
    localStorage.setItem(KEY, JSON.stringify(rest));
  } catch (_) { /* ignore quota */ }
}

export const store = {
  get: () => state,
  set(patch) {
    state = { ...state, ...patch };
    persist();
    listeners.forEach((fn) => fn(state, patch));
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  reset() { state = { ...defaults }; persist(); listeners.forEach((fn) => fn(state, {})); },
};

export const hasPlot = () => !!(state.plot && Number.isFinite(state.plot.lat));
