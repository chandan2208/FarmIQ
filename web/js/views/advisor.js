import { api } from '../api.js';
import { store } from '../store.js';
import { h, ensureSiteData, openPlotPicker } from '../ui.js';
import { t, LANGS } from '../i18n.js';
import { region } from '../units.js';

const SUGGEST = {
  en: ['When should I irrigate next?', 'Is there a spray window this week?', 'How much nitrogen does this crop need?', 'What is the biggest risk to my yield?', 'What should I sow next and when?', 'Which market pays best right now?'],
  hi: ['अगली सिंचाई कब करूँ?', 'इस हफ़्ते छिड़काव का समय है?', 'इस फ़सल को कितना यूरिया चाहिए?', 'मेरी उपज को सबसे बड़ा खतरा क्या है?', 'अगली फ़सल कौन सी और कब बोऊँ?', 'अभी कौन सी मंडी सबसे अच्छा भाव दे रही है?'],
  es: ['¿Cuándo debo regar?', '¿Hay ventana para pulverizar esta semana?', '¿Cuánto nitrógeno necesita este cultivo?', '¿Cuál es el mayor riesgo para mi rendimiento?', '¿Qué siembro después y cuándo?', '¿Qué mercado paga mejor ahora?'],
  fr: ['Quand irriguer ?', 'Y a-t-il une fenêtre de traitement cette semaine ?', 'Combien d’azote pour cette culture ?', 'Quel est le plus grand risque pour mon rendement ?', 'Que semer ensuite et quand ?', 'Quel marché paie le mieux ?'],
  de: ['Wann sollte ich bewässern?', 'Gibt es diese Woche ein Spritzfenster?', 'Wie viel Stickstoff braucht diese Kultur?', 'Was ist das größte Risiko für meinen Ertrag?', 'Was säe ich als Nächstes und wann?', 'Welcher Markt zahlt gerade am besten?'],
  it: ['Quando devo irrigare?', 'C’è una finestra per trattare questa settimana?', 'Quanto azoto serve a questa coltura?', 'Qual è il rischio maggiore per la resa?', 'Cosa seminare dopo e quando?', 'Quale mercato paga meglio ora?'],
};

function buildContext() {
  const s = store.get();
  const sim = s.sim, f = s.forecast;
  return {
    plot: s.plot,
    site: s.site ? { region: s.site.region, place: s.site.place, soil: s.site.soil, climate: s.site.climate } : (s.regionHint ? { region: s.regionHint } : null),
    forecast: f ? { summary: f.summary, days: f.days.slice(0, 10).map(({ date, tmax, tmin, rain, rain_prob, rh_mean, wind_max, frost, workable, spray_windows }) => ({ date, tmax, tmin, rain, rain_prob, rh_mean, wind_max, frost, workable, spray_windows })), soil_profile: f.soil_profile, disease_pressure: f.disease_pressure.slice(0, 6) } : null,
    simulation: sim ? { crop: sim.crop, label: sim.label, sow_date: sim.sow_date, season: sim.season, matured_on: sim.matured_on, killed_on: sim.killed_on, area_ha: sim.area_ha, irrigation: sim.irrigation, suitability: sim.suitability, yield_t_ha: sim.yield_t_ha, factors: sim.factors, water: sim.water, economics: sim.economics, risks: sim.risks, daily: sim.daily.filter((d, i) => d.src === 'forecast' || i % 7 === 0).map(({ date, src, stage, water, stress, rain, irrigation }) => ({ date, src, stage, water, stress, rain, irrigation })) } : null,
    ranking: s.rank ? s.rank.ranking.slice(0, 8).map(({ label, sow_date, season, yield_t_ha, net, risk_adjusted_net, top_risk }) => ({ label, sow_date, season, yield_t_ha, net, risk_adjusted_net, top_risk })) : null,
    market: s.market.data ? { state: s.market.state, summary: s.market.data.summary.slice(0, 12) } : null,
    today: new Date().toISOString().slice(0, 10),
  };
}

export default {
  async mount(root) {
    const s = store.get();
    const lang = s.lang || 'en';
    const log = h('div', { class: 'log' });
    const input = h('input', { type: 'text', placeholder: s.plot ? t('askPlaceholder') : t('setPlotFirst'), autocomplete: 'off', disabled: !s.plot });
    const send = h('button', { class: 'btn primary', type: 'submit', disabled: !s.plot }, t('ask'));
    const modeTag = h('span', { class: 'tag' }, '…');
    const ctx = h('div', { class: 'ctx' });
    const form = h('form', { onSubmit: (e) => { e.preventDefault(); ask(input.value.trim()); } }, input, send);
    root.append(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, t('advisorTitle')), h('p', {}, t('advisorLede'))), h('div', { class: 'row' }, modeTag, h('span', { class: 'tag' }, LANGS[lang]), s.plot ? null : h('button', { class: 'btn sm', type: 'button', onClick: () => openPlotPicker() }, t('setPlot')))),
      ctx,
      h('div', { class: 'chat', style: { marginTop: '14px' } }, log, h('div', { class: 'stack' }, h('div', { class: 'suggest' }, ...(SUGGEST[lang] || SUGGEST.en).map((q) => h('button', { class: 'btn ghost sm', type: 'button', disabled: !s.plot, onClick: () => ask(q) }, q))), form)),
    ));
    api.advisorMode().then((m) => { modeTag.textContent = m.mode === 'gemini' ? 'Gemini, grounded' : 'Rules engine, English only (set GEMINI_API_KEY for the language model)'; }).catch(() => { modeTag.textContent = 'offline'; });
    if (s.plot) ensureSiteData().then(refreshCtx).catch(() => refreshCtx());
    refreshCtx();
    (s.chat || []).forEach((m) => log.append(h('div', { class: `msg ${m.role === 'user' ? 'user' : 'bot'}` }, m.text)));
    log.scrollTop = log.scrollHeight;

    function refreshCtx() {
      const c = buildContext();
      const reg = region();
      ctx.replaceChildren(
        h('span', { class: `chip ${c.site?.soil ? 'ok' : ''}` }, c.site?.soil ? `Soil: ${c.site.soil.texture_label}, pH ${c.site.soil.ph}` : 'Soil: not loaded'),
        h('span', { class: `chip ${c.forecast ? 'ok' : ''}` }, c.forecast ? `Forecast: ${c.forecast.days.length} days` : 'Forecast: not loaded'),
        h('span', { class: `chip ${c.simulation ? 'ok' : ''}` }, c.simulation ? `Twin: ${c.simulation.label}` : 'Twin: no simulation yet'),
        h('span', { class: `chip ${c.ranking ? 'ok' : ''}` }, c.ranking ? `Ranking: ${c.ranking.length} crops` : 'Ranking: not run'),
        h('span', { class: 'chip' }, `${reg.name} · ${reg.currency}`),
      );
    }

    async function ask(q) {
      if (!q) return;
      input.value = '';
      const history = store.get().chat || [];
      log.append(h('div', { class: 'msg user' }, q));
      const bot = h('div', { class: 'msg bot' }, h('span', { class: 'loading' }, 'Reading your plot'));
      log.append(bot);
      log.scrollTop = log.scrollHeight;
      send.disabled = true;
      let text = '';
      try {
        await api.ask({ question: q, context: buildContext(), history: history.slice(-8), language: store.get().lang || 'en' }, (chunk) => { text += chunk; bot.textContent = text; log.scrollTop = log.scrollHeight; });
      } catch (err) { text = `The advisor failed: ${err.message}`; bot.textContent = text; }
      send.disabled = false;
      store.set({ chat: [...history, { role: 'user', text: q }, { role: 'bot', text }].slice(-30) });
      input.focus();
    }
  },
};
