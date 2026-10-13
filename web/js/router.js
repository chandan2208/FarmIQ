// Hash router with mount/unmount lifecycle so views can release resources (the 3D scene, timers).
const routes = new Map();
let current = null;

export function register(name, view) { routes.set(name, view); }

export function navigate(name) { location.hash = `#/${name}`; }

export function currentRoute() {
  const m = /^#\/([\w-]+)/.exec(location.hash);
  return m ? m[1] : '';
}

export async function render(root) {
  const name = currentRoute() || 'home';
  const view = routes.get(name) || routes.get('home');
  if (current?.unmount) { try { current.unmount(); } catch (_) { /* ignore */ } }
  root.innerHTML = '';
  root.scrollTop = 0;
  window.scrollTo({ top: 0 });
  document.querySelectorAll('.rail a[data-route]').forEach((a) => a.classList.toggle('active', a.dataset.route === name));
  current = view;
  try {
    await view.mount(root);
  } catch (err) {
    root.innerHTML = `<div class="page"><div class="error">This page failed to load: ${err.message}</div></div>`;
    console.error(err);
  }
}

export function start(root) {
  window.addEventListener('hashchange', () => render(root));
  return render(root);
}
