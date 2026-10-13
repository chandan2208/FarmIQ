import { api } from '../api.js';
import { store } from '../store.js';
import { h, fmt, toast, ensureCrops } from '../ui.js';

const TOPICS = { question: 'Question', pest: 'Pest or disease', market: 'Market', success: 'What worked', equipment: 'Equipment', weather: 'Weather' };

export default {
  async mount(root) {
    const crops = await ensureCrops();
    const list = h('div', { class: 'stack' });
    const filter = h('select', {}, h('option', { value: '' }, 'All topics'), ...Object.entries(TOPICS).map(([k, v]) => h('option', { value: k }, v)));
    filter.addEventListener('change', load);
    const plot = store.get().plot;
    const formEl = h('form', { class: 'card stack', enctype: 'multipart/form-data', onSubmit: submit },
      h('h4', {}, 'Post to the circle'),
      h('div', { class: 'grid two', style: { gap: '10px' } },
        h('div', { class: 'field' }, h('span', {}, 'Your name'), h('input', { type: 'text', name: 'author', placeholder: 'Anonymous', maxlength: 60 })),
        h('div', { class: 'field' }, h('span', {}, 'Topic'), h('select', { name: 'topic' }, ...Object.entries(TOPICS).map(([k, v]) => h('option', { value: k }, v))))),
      h('div', { class: 'field' }, h('span', {}, 'Title'), h('input', { type: 'text', name: 'title', required: true, minlength: 3, maxlength: 140, placeholder: 'Yellowing between veins on 40-day maize' })),
      h('div', { class: 'field' }, h('span', {}, 'Details'), h('textarea', { name: 'body', required: true, minlength: 3, placeholder: 'What you see, when it started, what you have tried.' })),
      h('div', { class: 'grid two', style: { gap: '10px' } },
        h('div', { class: 'field' }, h('span', {}, 'Crop'), h('select', { name: 'crop' }, h('option', { value: '' }, 'Not crop-specific'), ...crops.crops.map((c) => h('option', { value: c.id }, c.label)))),
        h('div', { class: 'field' }, h('span', {}, 'Photo (optional)'), h('input', { type: 'file', name: 'image', accept: 'image/*' }))),
      h('input', { type: 'hidden', name: 'region', value: plot ? [plot.name, plot.admin1].filter(Boolean).join(', ') : '' }),
      h('div', {}, h('button', { class: 'btn primary', type: 'submit' }, 'Post')),
    );
    root.append(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('div', {}, h('h2', {}, 'Farmer circle'), h('p', {}, 'Ask other growers what they see in the field. Posts stay on this server; no account needed.')), filter),
      h('div', { class: 'grid two', style: { alignItems: 'start' } }, list, formEl),
    ));
    load();

    async function load() {
      list.replaceChildren(h('div', { class: 'loading' }, 'Loading posts'));
      try {
        const { posts } = await api.posts({ topic: filter.value });
        if (!posts.length) { list.replaceChildren(h('div', { class: 'empty' }, 'No posts yet. Be the first to ask something.')); return; }
        list.replaceChildren(...posts.map(postCard));
      } catch (err) { list.replaceChildren(h('div', { class: 'error' }, err.message)); }
    }

    async function submit(e) {
      e.preventDefault();
      const fd = new FormData(formEl);
      const btn = formEl.querySelector('button[type=submit]');
      btn.disabled = true;
      try { await api.createPost(fd); formEl.reset(); toast('Posted'); load(); } catch (err) { toast(err.message, 5000); }
      btn.disabled = false;
    }

    function postCard(p) {
      const cropLabel = p.crop ? crops.crops.find((c) => c.id === p.crop)?.label : null;
      const comments = h('div', { class: 'comments', style: { display: 'none' } });
      const toggle = h('button', { class: 'btn ghost sm', type: 'button' }, `${p.comment_count} ${p.comment_count === 1 ? 'reply' : 'replies'}`);
      const up = h('button', { class: 'btn ghost sm', type: 'button', onClick: async () => { const r = await api.upvote(p.id); up.textContent = `Helpful · ${r.upvotes}`; } }, `Helpful · ${p.upvotes}`);
      toggle.addEventListener('click', async () => {
        if (comments.style.display !== 'none') { comments.style.display = 'none'; return; }
        comments.style.display = 'grid';
        await renderComments();
      });
      async function renderComments() {
        const full = await api.post(p.id);
        const ci = h('input', { type: 'text', placeholder: 'Reply', required: true, minlength: 2 });
        const cn = h('input', { type: 'text', placeholder: 'Name', style: { maxWidth: '140px' } });
        const cf = h('form', { class: 'row', onSubmit: async (e) => { e.preventDefault(); await api.comment(p.id, { author: cn.value || 'Anonymous', body: ci.value }); toggle.textContent = `${full.comments.length + 1} replies`; await renderComments(); } }, cn, h('div', { style: { flex: '1 1 200px' } }, ci), h('button', { class: 'btn sm', type: 'submit' }, 'Reply'));
        comments.replaceChildren(...full.comments.map((c) => h('div', { class: 'comment' }, h('b', {}, c.author), h('span', { class: 'dim small' }, ` · ${c.ago}`), h('div', {}, c.body))), cf);
      }
      return h('article', { class: 'card post' },
        h('div', { class: 'meta' }, h('span', { class: 'tag' }, TOPICS[p.topic] || p.topic), cropLabel && h('span', {}, cropLabel), p.region && h('span', {}, p.region), h('span', {}, `${p.author} · ${p.ago}`)),
        h('h3', {}, p.title),
        h('p', { style: { whiteSpace: 'pre-wrap', margin: 0 } }, p.body),
        p.image && h('img', { src: p.image, alt: '', loading: 'lazy' }),
        h('div', { class: 'row' }, toggle, up),
        comments,
      );
    }
  },
};

export { fmt };
