import { register, start, render } from './router.js';
import { openPlotPicker, updatePlotChip } from './ui.js';
import { store } from './store.js';
import { LANGS, t, detectLang } from './i18n.js';
import home from './views/home.js';
import twin from './views/twin.js';
import intel from './views/intel.js';
import weather from './views/weather.js';
import scan from './views/scan.js';
import market from './views/market.js';
import advisor from './views/advisor.js';
import community from './views/community.js';

register('home', home);
register('twin', twin);
register('intel', intel);
register('weather', weather);
register('scan', scan);
register('market', market);
register('advisor', advisor);
register('community', community);

const root = document.getElementById('view');
const langSel = document.getElementById('lang');

function applyChrome() {
  const s = store.get();
  const regionLangs = s.site?.region?.languages || s.regionHint?.languages;
  if (!s.lang) store.set({ lang: detectLang(regionLangs) });
  const lang = store.get().lang;
  document.documentElement.lang = lang;
  langSel.replaceChildren(...Object.entries(LANGS).map(([k, v]) => { const o = document.createElement('option'); o.value = k; o.textContent = v; o.selected = k === lang; return o; }));
  const labels = { twin: t('twin'), intel: t('crops'), weather: t('forecast'), scan: t('scan'), market: t('market'), advisor: t('advisor'), community: t('circle') };
  document.querySelectorAll('.rail a[data-route]').forEach((a) => { const ic = a.querySelector('.ic'); a.replaceChildren(ic, document.createTextNode(labels[a.dataset.route] || a.dataset.route)); });
  updatePlotChip();
}

langSel.addEventListener('change', () => { store.set({ lang: langSel.value }); applyChrome(); render(root); });
document.getElementById('plot-chip').addEventListener('click', () => openPlotPicker());
store.subscribe((s, patch) => { if (patch.plot || patch.site || patch.lang) applyChrome(); });

applyChrome();
start(root);

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  navigator.serviceWorker.register('/sw.js').catch(() => { /* offline shell is a bonus, not a requirement */ });
}
