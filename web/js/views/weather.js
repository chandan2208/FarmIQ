import { store } from '../store.js';
import { h, fmt, needPlot, ensureSiteData, plotBanner, bar } from '../ui.js';
import { t } from '../i18n.js';
import { U, fmtNum } from '../units.js';

const CODE = { 0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog', 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 80: 'Showers', 81: 'Showers', 82: 'Violent showers', 95: 'Thunderstorm', 96: 'Thunderstorm, hail', 99: 'Thunderstorm, hail' };

export default {
  async mount(root) {
    const s = store.get();
    if (!s.plot) return needPlot(root, t('forecastTitle'));
    const out = h('div', { class: 'stack' }, h('div', { class: 'loading' }, 'Loading 16-day forecast'));
    root.append(h('div', { class: 'page' }, h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, t('forecastTitle')), h('p', {}, t('forecastLede'))), plotBanner()), out));
    try {
      const { forecast: f } = await ensureSiteData();
      render(f);
    } catch (err) { out.replaceChildren(h('div', { class: 'error' }, err.message)); }

    function render(f) {
      const cur = f.current || {}, sp = f.soil_profile, sm = f.summary || {};
      const week = f.days.slice(0, 7);
      const windows = f.days.slice(0, 5).flatMap((d) => d.spray_windows.map((w) => ({ ...w, date: d.date })));
      const tile = (num, lbl, color) => h('div', { class: 'card' }, h('div', { class: 'stat' }, h('span', { class: 'num', style: color ? { color } : null }, num), h('span', { class: 'lbl' }, lbl)));
      out.replaceChildren(
        h('div', { class: 'grid three' },
          tile(U.temp(cur.temperature_2m, 1), `${t('now')} · ${CODE[cur.weather_code] || ''} · RH ${cur.relative_humidity_2m}% · wind ${fmtNum(cur.wind_speed_10m)} km/h`),
          tile(U.rain(sm.rain_7d, 0), `${t('rain7')} · ${week.filter((d) => d.rain >= 1).length} wet days · max ${U.temp(Math.max(...week.map((d) => d.tmax)))}`, 'var(--water)'),
          tile(sm.frost_nights ? `${sm.frost_nights}` : t('none'), `${t('frostNights')} · ${sm.first_frost ? `${t('firstFrost')} ${fmt.date(sm.first_frost)}` : `${sm.heat_days_35} days ≥ ${U.temp(35)}`}`, sm.frost_nights ? 'var(--alert)' : null),
          tile(`${sm.workable_days}/16`, `${t('workable')} · ${sm.next_workable ? `${t('nextWorkable')} ${fmt.date(sm.next_workable)}` : 'soil too wet'}`, 'var(--paddy)'),
          tile(`${sm.gdd10_16d}`, `${t('gdd')} · 16 days`),
          h('div', { class: 'card' }, h('h4', {}, t('soilMoistureNow')), h('div', { class: 'soilbars', style: { marginTop: '8px' } },
            ...[['0–1 cm', sp['0_1cm']], ['3–9 cm', sp['3_9cm']], ['9–27 cm', sp['9_27cm']], ['27–81 cm', sp['27_81cm']]].map(([l, v]) => h('div', { class: 'f' }, h('span', {}, l), bar((v || 0) / 0.5, { cls: 'water' }), h('span', { class: 'r small' }, v === null ? '—' : `${(v * 100).toFixed(0)}% vol`))),
            h('div', { class: 'small dim' }, `Soil temperature at 6 cm: ${U.temp(sp.soil_temp_6cm, 1)}`))),
        ),
        h('div', { class: 'days' }, ...f.days.map((d) => h('div', { class: `day ${d.rain >= 5 ? 'wet' : ''}`, style: d.frost ? { borderColor: 'rgba(232,105,74,.5)' } : null },
          h('span', { class: 'd' }, `${fmt.weekday(d.date)} ${fmt.date(d.date)}`),
          h('span', { class: 't' }, `${U.tempVal(d.tmax)}°`, h('small', {}, ` / ${U.tempVal(d.tmin)}°`)),
          h('span', { class: 'small muted' }, `${CODE[d.code] || ''}${d.frost ? ` · ${t('frost')}` : ''}`),
          h('span', { class: 'r' }, d.rain >= 0.5 ? `${U.rain(d.rain)} · ${d.rain_prob ?? '–'}%` : t('dry')),
          h('span', { class: 'small muted' }, `RH ${d.rh_mean ?? '–'}% · ET₀ ${fmtNum(d.et0, 1)} mm${d.workable ? ' · workable' : ''}`),
          d.spray_windows.length ? h('span', { class: 'w' }, `${t('spray')} ${d.spray_windows[0].start}–${d.spray_windows[0].end}`) : h('span', { class: 'small dim' }, t('noSpray')),
        ))),
        h('div', { class: 'grid two' },
          h('div', { class: 'card' }, h('h4', {}, t('sprayWindows')), h('p', { class: 'small muted', style: { margin: '4px 0 10px' } }, 'Daylight hours with wind under 15 km/h, no rain within six hours and humidity between 40 and 85%, so the spray stays on the leaf.'),
            windows.length ? h('table', {}, h('tbody', {}, ...windows.map((w) => h('tr', {}, h('td', {}, `${fmt.weekday(w.date)} ${fmt.date(w.date)}`), h('td', {}, `${w.start} – ${w.end}`), h('td', { class: 'r' }, `${w.hours} h`))))) : h('div', { class: 'empty small' }, 'No clean window in the next five days. Wait, or spray in the first dry morning and accept some loss.')),
          h('div', { class: 'card' }, h('h4', {}, t('diseasePressure')), h('p', { class: 'small muted', style: { margin: '4px 0 10px' } }, 'How closely the coming week matches each pathogen\'s favourite temperature, humidity and leaf wetness. High pressure means apply a protectant before symptoms, not after.'),
            h('div', { class: 'factors' }, ...f.disease_pressure.filter((p) => p.mine).concat(f.disease_pressure.filter((p) => !p.mine).slice(0, 6)).slice(0, 14).map((p) => h('div', { class: 'f' }, h('span', { title: p.crop, style: p.mine ? { fontWeight: 600 } : null }, `${p.name}`, h('span', { class: 'dim' }, ` · ${p.crop}`)), bar(p.pressure / 100, { cls: p.pressure >= 70 ? 'alert' : p.pressure >= 40 ? 'gold' : '' }), h('span', { class: 'r' }, p.pressure))))),
        ),
        h('p', { class: 'small dim' }, `Fetched ${f.fetched_at}${f.stale ? ' (cached; upstream unavailable)' : ''} · elevation ${f.elevation} m · ${f.timezone} · Workable = 9-27 cm soil below field capacity, dry day, no frost.`),
      );
    }
  },
};
