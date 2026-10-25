/* Gate online-only source pages and load complete bounded RSS feed results. */
const page = document.querySelector('#resource-page');
if (page) {
  const translate = window.cyberdeckTranslate;
  const feedSelect = page.querySelector('[data-rss-feed]');
  const loadButton = page.querySelector('.rss-load');
  const feedStatus = page.querySelector('.rss-status');
  const feedItems = page.querySelector('.rss-items');
  let internetAvailable = false;
  let checkingInternet = false;
  let loadingFeed = false;

  function formatPublishedTime(value) {
    if (!value) return translate('ui.0817');
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return translate('ui.0817');
    try {
      return new Intl.DateTimeFormat(document.documentElement.lang || 'en', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
        timeZone: page.dataset.timezone,
        timeZoneName: 'short'
      }).format(date);
    } catch {
      return translate('ui.0817');
    }
  }

  function clearFeed() {
    if (feedItems) feedItems.replaceChildren();
    if (feedStatus) feedStatus.textContent = '';
  }

  function appendFeedItem(item) {
    const article = document.createElement('article');
    article.className = 'rss-entry';
    const heading = document.createElement('h3');
    heading.textContent = item.title;
    article.append(heading);
    const date = document.createElement('time');
    date.className = 'rss-date';
    date.textContent = formatPublishedTime(item.published);
    if (item.published) date.dateTime = item.published;
    article.append(date);
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
    feedItems.append(article);
  }

  async function loadFeed() {
    if (!internetAvailable || !feedSelect || loadingFeed) return;
    loadingFeed = true;
    loadButton.disabled = true;
    feedStatus.textContent = translate('ui.0765');
    feedItems.replaceChildren();
    try {
      const query = new URLSearchParams({card: page.dataset.rssCard, feed: feedSelect.value});
      const response = await fetch(`/api/online/rss?${query}`, {cache: 'no-store', credentials: 'omit'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'RSS feed unavailable');
      if (!internetAvailable) return;
      const sorted = result.items.map((entry, index) => ({entry, index, date: Date.parse(entry.published)}));
      if (sorted.some(row => Number.isFinite(row.date))) {
        sorted.sort((a, b) => (Number.isFinite(b.date) ? b.date : -Infinity) -
          (Number.isFinite(a.date) ? a.date : -Infinity) || a.index - b.index);
      }
      if (!sorted.length) {
        feedStatus.textContent = translate('ui.0768');
        return;
      }
      sorted.forEach(row => appendFeedItem(row.entry));
      feedStatus.textContent = `${translate('ui.0766')} ${result.fetched_utc}${result.stale ? ` · ${translate('ui.0767')}` : ''}`;
    } catch {
      if (internetAvailable) feedStatus.textContent = translate('ui.0770');
    } finally {
      loadingFeed = false;
      loadButton.disabled = !internetAvailable;
    }
  }

  async function updateInternet() {
    if (checkingInternet || document.hidden) return;
    checkingInternet = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/connectivity/kiwix', {
        signal: controller.signal, cache: 'no-store', credentials: 'omit'
      });
      if (!response.ok) throw new Error('Connectivity check unavailable');
      const result = await response.json();
      internetAvailable = result.available === true && navigator.onLine;
      page.hidden = !internetAvailable;
      if (loadButton) loadButton.disabled = !internetAvailable;
      if (!internetAvailable) clearFeed();
    } catch {
      internetAvailable = false;
      page.hidden = true;
      if (loadButton) loadButton.disabled = true;
      clearFeed();
    } finally {
      clearTimeout(timeout);
      checkingInternet = false;
    }
  }

  loadButton?.addEventListener('click', loadFeed);
  feedSelect?.addEventListener('change', loadFeed);
  window.addEventListener('offline', () => {
    internetAvailable = false;
    page.hidden = true;
    if (loadButton) loadButton.disabled = true;
    clearFeed();
  });
  window.addEventListener('online', updateInternet);
  document.addEventListener('visibilitychange', updateInternet);
  updateInternet().then(() => {
    if (internetAvailable && feedSelect) loadFeed();
  });
  setInterval(updateInternet, 60000);
}
