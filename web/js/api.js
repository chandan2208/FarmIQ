// Thin API client. Every call returns parsed JSON or throws an Error with the server's message.
async function request(path, options = {}) {
  const res = await fetch(path, { headers: { Accept: 'application/json' }, ...options });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* ignore */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return res.json();
}

const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString();

export const api = {
  health: () => request('/api/health'),
  geocode: (q) => request(`/api/site/geocode?${qs({ q })}`),
  profile: (lat, lon, country) => request(`/api/site/profile?${qs({ lat, lon, country })}`),
  reference: (region) => request(`/api/market/reference?${qs({ region })}`),
  forecast: (lat, lon, crop) => request(`/api/weather/forecast?${qs({ lat, lon, crop })}`),
  crops: () => request('/api/twin/crops'),
  simulate: (body) => request('/api/twin/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  compare: (body) => request('/api/twin/compare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  rank: (body) => request('/api/twin/rank', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  prices: (params) => request(`/api/market/prices?${qs(params)}`),
  scan: (file) => { const fd = new FormData(); fd.append('file', file); return request('/api/scan/leaf', { method: 'POST', body: fd }); },
  diseases: () => request('/api/scan/diseases'),
  coverage: () => request('/api/scan/coverage'),
  posts: (params = {}) => request(`/api/community/posts?${qs(params)}`),
  post: (id) => request(`/api/community/posts/${id}`),
  createPost: (fd) => request('/api/community/posts', { method: 'POST', body: fd }),
  comment: (id, body) => request(`/api/community/posts/${id}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  upvote: (id) => request(`/api/community/posts/${id}/upvote`, { method: 'POST' }),
  advisorMode: () => request('/api/advisor/mode'),

  // Server-sent events from the advisor. onChunk receives text pieces; resolves when done.
  async ask(body, onChunk, onMeta) {
    const res = await fetch('/api/advisor/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok || !res.body) throw new Error('Advisor unavailable');
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const ev = /^event: (\w+)/m.exec(frame)?.[1] || 'message';
        const data = /^data: (.*)$/m.exec(frame)?.[1];
        if (data === undefined) continue;
        if (ev === 'meta') onMeta?.(JSON.parse(data));
        else if (ev === 'message') onChunk(JSON.parse(data));
      }
    }
  },
};
