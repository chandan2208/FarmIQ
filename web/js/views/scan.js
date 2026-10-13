import { api } from '../api.js';
import { h, fmt, bar, toast } from '../ui.js';

export default {
  async mount(root) {
    const input = h('input', { type: 'file', accept: 'image/*', capture: 'environment', style: { display: 'none' } });
    const preview = h('div');
    const drop = h('div', { class: 'drop', tabindex: 0, role: 'button', 'aria-label': 'Choose a leaf photo' },
      preview,
      h('div', { class: 'num', style: { fontSize: '20px' } }, 'Drop a leaf photo here, or tap to take one'),
      h('div', { class: 'small muted' }, 'One leaf filling the frame, in daylight, against a plain background. JPEG, PNG or WebP up to 12 MB.'),
    );
    const result = h('div', { class: 'stack' });
    const coverage = h('div', { class: 'small dim' });
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', (e) => { const f = e.dataTransfer.files?.[0]; if (f) analyse(f); });
    input.addEventListener('change', () => { if (input.files[0]) analyse(input.files[0]); });

    root.append(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, 'Leaf scan'), h('p', {}, 'Photograph a leaf. The scanner names the crop and the condition with a confidence, refuses photos that are not a known crop leaf, and hands you a treatment protocol with doses.'))),
      h('div', { class: 'grid two' }, h('div', { class: 'stack' }, drop, input, coverage), result),
    ));
    api.coverage().then((c) => {
      const crops = Object.entries(c.crops).sort();
      coverage.replaceChildren(h('details', {}, h('summary', { style: { cursor: 'pointer' } }, `${crops.length} crops, ${crops.reduce((a, [, v]) => a + v.length, 0)} conditions covered`),
        h('div', { style: { marginTop: '8px' } }, ...crops.map(([crop, conds]) => h('div', {}, h('b', {}, fmt.cap(crop.replace(/_/g, ' '))), ': ', conds.map((x) => x.replace(/_/g, ' ')).join(', '))))));
    }).catch(() => {});

    async function analyse(file) {
      if (!file.type.startsWith('image/')) { toast('That is not an image'); return; }
      const url = URL.createObjectURL(file);
      preview.replaceChildren(h('img', { src: url, alt: 'Photo' }));
      result.replaceChildren(h('div', { class: 'loading' }, 'Analysing'));
      try { render(await api.scan(file)); } catch (err) { result.replaceChildren(h('div', { class: 'error' }, err.message)); }
    }

    function render(r) {
      const g = r.gates || {};
      const modelLine = h('div', { class: 'small dim', style: { marginTop: '10px' } }, `Model ${r.model.arch}, ${r.model.classes} classes, trained on ${fmt.num(r.model.train_images)} images${r.model.val_acc ? `, ${fmt.pct(r.model.val_acc, 1)} on ${fmt.num(r.model.val_images)} held-out images` : ''}. Gates: not-a-leaf ${fmt.pct(g.p_other, 1)}, embedding distance ${g.distance ?? '—'} (limit ${g.distance_threshold ?? '—'}).`);
      if (r.verdict === 'not_a_leaf') {
        result.replaceChildren(h('div', { class: 'card' },
          h('div', { class: 'verdict' }, h('span', { class: 'big' }, 'Not a crop leaf'), h('span', { class: 'chip warn' }, 'rejected')),
          h('p', { class: 'muted', style: { margin: '10px 0 0' } }, r.advice), modelLine));
        return;
      }
      const top = r.top;
      const sevCls = { none: 'ok', medium: 'warn', high: 'bad', critical: 'bad' }[top.severity] || '';
      const p = r.protocol;
      result.replaceChildren(
        h('div', { class: 'card' },
          h('div', { class: 'verdict' }, h('span', { class: 'big' }, r.verdict === 'uncertain' ? 'Not sure' : `${top.crop}: ${top.name}`), h('span', { class: `chip ${r.verdict === 'uncertain' ? 'warn' : sevCls}` }, r.verdict === 'uncertain' ? `${fmt.pct(top.confidence)} confidence` : `${top.severity === 'none' ? 'healthy' : top.severity + ' severity'} · ${fmt.pct(top.confidence)}${r.verdict === 'likely' ? ' · likely' : ''}`)),
          h('p', { class: 'muted', style: { margin: '10px 0 0' } }, r.advice),
          h('div', { class: 'divider' }),
          h('div', { class: 'cands' }, ...r.candidates.map((c) => h('div', { class: 'c' }, h('div', {}, h('div', {}, `${c.crop}: ${c.name}`), bar(c.confidence, { cls: c === top ? 'gold' : '' })), h('span', { class: 'r small' }, fmt.pct(c.confidence, 1))))),
          modelLine,
        ),
        p && h('div', { class: 'card protocol' },
          h('h4', {}, p.pathogen ? `${p.name}: ${p.pathogen}` : 'Looks healthy'),
          h('p', { class: 'small muted', style: { margin: '6px 0 12px' } }, p.symptoms),
          h('b', {}, 'Do this now'), h('ol', {}, ...p.act_now.map((x) => h('li', {}, x))),
          p.organic && h('p', { style: { margin: '12px 0 0' } }, h('b', {}, 'Organic option. '), p.organic),
          p.chemical && h('p', { style: { margin: '8px 0 0' } }, h('b', {}, 'Chemical option. '), p.chemical),
          p.prevent && h('p', { style: { margin: '8px 0 0' } }, h('b', {}, 'Prevent next time. '), p.prevent),
          p.favoured_by && h('p', { class: 'small dim', style: { margin: '12px 0 0' } }, `Spreads fastest at ${p.favoured_by.temp[0]}–${p.favoured_by.temp[1]} °C${p.favoured_by.humidity_min ? ` with humidity above ${p.favoured_by.humidity_min}%` : ''}${p.favoured_by.rain ? ' and wet leaves' : ' in dry weather'}. Check the forecast page for this week's pressure.`),
        ),
        h('p', { class: 'small dim' }, 'Photos are analysed in memory and not stored.'),
      );
    }
  },
};
