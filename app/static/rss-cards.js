/* Load bounded RSS and Atom previews into online-only home cards. */
const onlineGroup = document.querySelector('#online-crisis-group');
const translate = window.cyberdeckTranslate;
let internetAvailable = false;
let checkingInternet = false;

function clearCard(card) {
  card.querySelector('.rss-items').replaceChildren();
  card.querySelector('.rss-status').textContent = '';
}

function appendEntry(container, item) {
  const article = document.createElement('article');
  article.className = 'rss-entry';
  const heading = document.createElement('h4');
  heading.textContent = item.title;
  article.append(heading);
  if (item.published) {
    const date = document.createElement('p');
    date.className = 'rss-date';
    date.textContent = item.published;
    article.append(date);
  }
  if (item.summary) {
    const summary = document.createElement('p');
    summary.className = 'rss-summary';
    summary.textContent = item.summary;
    article.append(summary);
  }
  try {
    const url = new URL(item.link);
    if (url.protocol === 'https:' && !url.username && !url.password) {
      const link = document.createElement('a');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = translate('ui.0771');
      article.append(link);
    }
  } catch { /* malformed publisher links are omitted */ }
  container.append(article);
}

async function loadCard(card) {
  if (!internetAvailable) return;
  const select = card.querySelector('[data-rss-feed]');
  const button = card.querySelector('.rss-load');
  const status = card.querySelector('.rss-status');
  const items = card.querySelector('.rss-items');
  if (!select || !select.value) return;
  button.disabled = true;
  status.textContent = translate('ui.0765');
  items.replaceChildren();
  try {
    const query = new URLSearchParams({card: card.dataset.rssCard, feed: select.value});
    const response = await fetch(`/api/online/rss?${query}`, {cache: 'no-store', credentials: 'omit'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'RSS feed unavailable');
    if (!internetAvailable) return;
    const sorted = result.items.map((entry, index) => ({entry, index, date: Date.parse(entry.published)}));
    if (sorted.some(row => Number.isFinite(row.date))) {
      sorted.sort((a, b) => (Number.isFinite(b.date) ? b.date : -Infinity) -
        (Number.isFinite(a.date) ? a.date : -Infinity) || a.index - b.index);
    }
    const latest = sorted.slice(0, 5).map(row => row.entry);
    if (!latest.length) {
      status.textContent = translate('ui.0768');
      return;
    }
    latest.forEach(item => appendEntry(items, item));
    status.textContent = `${translate('ui.0766')} ${result.fetched_utc}${result.stale ? ` · ${translate('ui.0767')}` : ''}`;
  } catch {
    if (internetAvailable) status.textContent = translate('ui.0770');
  } finally {
    button.disabled = !internetAvailable;
  }
}

async function updateInternet() {
  if (!onlineGroup || checkingInternet || document.hidden) return;
  checkingInternet = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('/api/connectivity/kiwix', {
      signal: controller.signal, cache: 'no-store', credentials: 'omit'
    });
    if (!response.ok) throw new Error('Internet check failed');
    const result = await response.json();
    internetAvailable = result.available === true && navigator.onLine;
    onlineGroup.hidden = !internetAvailable;
    for (const card of onlineGroup.querySelectorAll('[data-rss-card]')) {
      const button = card.querySelector('.rss-load');
      button.disabled = !internetAvailable;
      if (internetAvailable && !card.dataset.loaded) {
        card.dataset.loaded = 'true';
        loadCard(card);
      } else if (!internetAvailable) {
        delete card.dataset.loaded;
        clearCard(card);
      }
    }
  } catch {
    internetAvailable = false;
    onlineGroup.hidden = true;
    onlineGroup.querySelectorAll('[data-rss-card]').forEach(clearCard);
  } finally {
    clearTimeout(timeout);
    checkingInternet = false;
  }
}

onlineGroup?.querySelectorAll('[data-rss-card]').forEach(card => {
  card.querySelector('.rss-load').addEventListener('click', () => loadCard(card));
  card.querySelector('[data-rss-feed]').addEventListener('change', () => loadCard(card));
});
window.addEventListener('offline', () => {
  internetAvailable = false;
  if (onlineGroup) {
    onlineGroup.hidden = true;
    onlineGroup.querySelectorAll('[data-rss-card]').forEach(card => {
      delete card.dataset.loaded;
      clearCard(card);
    });
  }
});
window.addEventListener('online', updateInternet);
document.addEventListener('visibilitychange', updateInternet);
updateInternet();
setInterval(updateInternet, 60000);
