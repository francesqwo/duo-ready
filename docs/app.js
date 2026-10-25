/* Duo Ready — static tracker. No build step, no dependencies. */
const state = { apps: [], status: 'all', source: 'all', genre: 'all', sort: 'status', q: '' };

const $ = (sel) => document.querySelector(sel);
const grid = $('#grid');

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function daysAgo(iso) {
  if (!iso) return Infinity;
  const then = new Date(iso + 'T00:00:00Z').getTime();
  return (Date.now() - then) / 86400000;
}

function isNew(app) {
  return app.duo && app.firstSeenDuo && daysAgo(app.firstSeenDuo) <= 7;
}

function matches(app) {
  if (state.status === 'ready' && !app.duo) return false;
  if (state.status === 'pending' && app.duo) return false;
  if (state.source === 'featured' && !app.sources?.includes('featured')) return false;
  if (state.source === 'chart' && !app.sources?.some((s) => s.startsWith('chart'))) return false;
  if (state.genre !== 'all' && (app.genre || 'Uncategorised') !== state.genre) return false;
  if (!state.q) return true;
  const haystack = `${app.name} ${app.seller} ${app.genre}`.toLowerCase();
  return state.q.split(/\s+/).every((word) => haystack.includes(word));
}

function sortApps(list) {
  const copy = [...list];
  if (state.sort === 'name') copy.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  else if (state.sort === 'recent') {
    copy.sort((a, b) => (b.firstSeenDuo || '').localeCompare(a.firstSeenDuo || '') || (a.name || '').localeCompare(b.name || ''));
  } else {
    copy.sort((a, b) => (Number(!!b.duo) - Number(!!a.duo)) || (a.name || '').localeCompare(b.name || ''));
  }
  return copy;
}

function card(app) {
  const tags = [];
  if (app.duo) tags.push('<span class="tag ready">Duo-ready</span>');
  else tags.push('<span class="tag pending">Not yet</span>');
  if (isNew(app)) tags.push('<span class="tag new">New</span>');
  if (app.sources?.includes('featured')) tags.push('<span class="tag">Apple featured</span>');
  if (app.genre) tags.push(`<span class="tag">${esc(app.genre)}</span>`);
  if (app.duo && app.firstSeenDuo) tags.push(`<span class="tag">since ${esc(app.firstSeenDuo)}</span>`);

  const icon = app.icon
    ? `<img src="${esc(app.icon)}" alt="" loading="lazy" width="46" height="46">`
    : '<img alt="" width="46" height="46">';

  return `<article class="card">
    <div class="card-top">
      ${icon}
      <div style="min-width:0">
        <h3>${esc(app.name)}</h3>
        <div class="seller">${esc(app.seller || '')}</div>
      </div>
    </div>
    <div class="meta">${tags.join('')}
      ${app.url ? `<a class="open" href="${esc(app.url)}" target="_blank" rel="noopener">App Store ↗</a>` : ''}
    </div>
  </article>`;
}

function render() {
  const list = sortApps(state.apps.filter(matches));
  grid.innerHTML = list.map(card).join('');
  $('#empty').hidden = list.length > 0;
  const ready = list.filter((a) => a.duo).length;
  $('#resultline').textContent = `${list.length} app${list.length === 1 ? '' : 's'} · ${ready} Duo-ready`;
}

function buildGenres() {
  const genres = [...new Set(state.apps.map((a) => a.genre || 'Uncategorised'))].sort();
  $('#genre').insertAdjacentHTML('beforeend',
    genres.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join(''));
}

function wire() {
  $('#search').addEventListener('input', (e) => { state.q = e.target.value.trim().toLowerCase(); render(); });
  $('#genre').addEventListener('change', (e) => { state.genre = e.target.value; render(); });
  $('#sort').addEventListener('change', (e) => { state.sort = e.target.value; render(); });

  document.querySelectorAll('[data-status]').forEach((button) => {
    button.addEventListener('click', () => {
      state.status = button.dataset.status;
      document.querySelectorAll('[data-status]').forEach((b) => b.classList.toggle('is-active', b === button));
      render();
    });
  });
  document.querySelectorAll('[data-source]').forEach((button) => {
    button.addEventListener('click', () => {
      state.source = button.dataset.source;
      document.querySelectorAll('[data-source]').forEach((b) => b.classList.toggle('is-active', b === button));
      render();
    });
  });
}

function wireTrack() {
  const input = $('#track-input');
  const button = $('#track-btn');
  if (!input || !button) return;

  const submit = () => {
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    const idMatch = value.match(/id(\d{6,})/);
    const title = idMatch ? `Track: ${idMatch[1]}` : `Track: ${value}`;
    const body = [
      idMatch ? `App Store id: ${idMatch[1]}` : `App: ${value}`,
      '',
      'Added from the Duo Ready site.',
    ].join('\n');
    const url = 'https://github.com/francesqwo/duo-ready/issues/new'
      + `?title=${encodeURIComponent(title)}`
      + `&body=${encodeURIComponent(body)}`;
    window.open(url, '_blank', 'noopener');
    $('#track-hint').textContent = 'Issue opened — the Action adds it within a minute and replies there.';
  };

  button.addEventListener('click', submit);
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
}

async function boot() {
  try {
    const response = await fetch('data/apps.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    state.apps = data.apps || [];

    const ready = state.apps.filter((a) => a.duo).length;
    const total = state.apps.length;
    $('#stat-ready').textContent = ready;
    $('#stat-total').textContent = total;
    $('#stat-pct').textContent = total ? `${Math.round((ready / total) * 100)}%` : '—';
    const stamp = (data.generatedAt || '').replace('T', ' ').replace('Z', '');
    $('#stat-updated').textContent = stamp ? stamp.slice(5, 16) : '—';

    buildGenres();
    wire();
    wireTrack();
    render();
  } catch (error) {
    $('#resultline').textContent = `Could not load data (${error.message}). Try reloading.`;
  }
}

boot();
