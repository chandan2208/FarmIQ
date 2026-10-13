import { h, openPlotPicker, toast, updatePlotChip } from '../ui.js';
import { store } from '../store.js';
import { navigate } from '../router.js';
import { t } from '../i18n.js';

let scene, timer;

const DEMOS = [
  { name: 'Araria', admin1: 'Bihar', country: 'India', country_code: 'IN', region: 'IN', lat: 26.149, lon: 87.513, label: 'Bihar, India' },
  { name: 'Ames', admin1: 'Iowa', country: 'United States', country_code: 'US', region: 'US', lat: 42.035, lon: -93.62, label: 'Iowa, USA' },
  { name: 'Lincoln', admin1: 'England', country: 'United Kingdom', country_code: 'GB', region: 'UK', lat: 53.227, lon: -0.538, label: 'Lincolnshire, UK' },
  { name: 'Toulouse', admin1: 'Occitanie', country: 'France', country_code: 'FR', region: 'EU', lat: 43.6, lon: 1.44, label: 'Occitanie, France' },
];

export default {
  async mount(root) {
    const stage = h('div', { class: 'scene' });
    const legend = h('div', { class: 'legend' });
    const demo = (d) => h('button', { class: 'btn', type: 'button', onClick: () => {
      const { label, ...plot } = d;
      store.set({ plot, site: null, forecast: null, sim: null, rank: null, compare: [], regionHint: null, scenario: { ...store.get().scenario, sow_date: null } });
      updatePlotChip(); toast(`${t('setPlot')}: ${d.label}`); navigate('twin');
    } }, d.label);
    const hero = h('section', { class: 'hero' },
      stage,
      h('div', { class: 'fade' }),
      h('div', { class: 'copy reveal' },
        h('h1', {}, t('heroTitle')),
        h('p', { class: 'lede' }, t('heroLede')),
        h('div', { class: 'cta' },
          h('button', { class: 'btn primary', type: 'button', onClick: () => { openPlotPicker(); const off = store.subscribe((s, patch) => { if (patch.plot) { off(); navigate('twin'); } }); } }, t('buildTwin')),
        ),
        h('div', { class: 'row', style: { marginTop: '14px' } }, h('span', { class: 'small muted' }, `${t('demoPlot')}:`), ...DEMOS.map(demo)),
      ),
      legend,
    );
    const pillars = h('section', { class: 'pillars' },
      pillar('The twin', 'One field, rendered in 3D and simulated with an FAO-56 water balance, growing-degree-days, frost kill and stage-wise yield response. Scrub through the season and watch the canopy, the soil water and the stress days. The field scales with your acreage.', 'twin', 'Open the twin', 'Engine: FAO-56 and FAO-33 methods, 40 crops, regional calendars'),
      pillar('Every crop, every sowing date', 'The same engine runs each crop grown in your region at every plausible sowing date on your soil and climate, then ranks by risk-adjusted margin in your currency and units, with the reason each one loses yield.', 'intel', 'Rank crops'),
      pillar('A forecast that speaks field', '16 days of weather turned into frost nights, workable days for machinery, spray windows, soil moisture at four depths and disease pressure.', 'weather', 'See the forecast', 'Source: Open-Meteo, worldwide'),
      pillar('Leaf scan', 'Photograph a leaf and get a diagnosis with confidence and a treatment protocol with doses. The model says so when it is not sure.', 'scan', 'Scan a leaf', 'MobileNetV3 fine-tuned on 20,000 leaf images, 15 conditions'),
      pillar('Prices where you sell', 'Live mandi prices across India; curated farm-gate reference prices for the US, UK and EU in dollars, pounds and euros, in bushels, tonnes or quintals as you trade them.', 'market', 'Check prices', 'Agmarknet, USDA NASS, AHDB, Eurostat'),
      pillar('An advisor that knows your field', 'Ask in English, Hindi, Spanish, French, German or Italian. The advisor reads your soil, forecast, simulation, ranking and prices before it answers, and quotes the numbers it used.', 'advisor', 'Ask the advisor'),
    );
    root.append(hero, pillars);

    try {
      const { FieldScene, demoSeason } = await import('../three/scene.js');
      scene = new FieldScene().mount(stage, { autoRotate: true, interactive: false });
      scene.setCrop('wheat', 'cereal');
      scene.setArea(2.2);
      const season = demoSeason(120);
      let i = 0;
      const step = () => {
        const d = season[i % season.length];
        scene.setDay(d, { immediate: i === 0 });
        legend.replaceChildren(h('span', {}, h('b', {}, `${t('day')} ${d.day}`), ' of a demo wheat season'), h('span', {}, `${stageName(d.stage)} · ${t('soilWater').toLowerCase()} ${(d.water * 100).toFixed(0)}%`), d.rain > 1 ? h('span', {}, `${d.rain} mm ${t('rain').toLowerCase()}`) : h('span', {}, t('dry')));
        i += 1;
      };
      step();
      timer = setInterval(step, 260);
    } catch (err) {
      stage.append(h('div', { class: 'scene-fallback' }, h('p', {}, `3D view unavailable here (${err.message}). The rest of FarmIQ works without it.`)));
    }
  },
  unmount() { clearInterval(timer); scene?.dispose(); scene = null; },
};

function pillar(title, body, route, cta, src) {
  return h('div', { class: 'pillar' }, h('h3', {}, title), h('p', {}, body), h('p', { style: { marginTop: '10px' } }, h('a', { href: `#/${route}` }, cta)), src && h('span', { class: 'src' }, src));
}

const stageName = (s) => ({ ini: 'Establishment', dev: 'Vegetative growth', mid: 'Flowering and grain fill', late: 'Ripening' })[s] || s;
