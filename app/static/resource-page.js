/* Gate online-only detail pages while keeping the configured offline mode usable. */
const page = document.querySelector('#resource-page');
if (page) {
  const translate = window.cyberdeckTranslate;
  const feedSelect = page.querySelector('[data-rss-feed]');
  const loadButton = page.querySelector('.rss-load');
  const feedStatus = page.querySelector('.rss-status');
  const feedItems = page.querySelector('.rss-items');
  const cachePrefix = 'cyberdeck.rss-cache.';
  let internetAvailable = false;
  let checkingInternet = false;
  let loadingFeed = false;

  function cacheKey(feedId) {
    const url = feedSelect?.selectedOptions[0]?.dataset.feedUrl || '';
    let hash = 2166136261;
    for (let index = 0; index < url.length; index++) hash = Math.imul(hash ^ url.charCodeAt(index), 16777619);
    return `${cachePrefix}${page.dataset.rssCard}.${feedId}.${(hash >>> 0).toString(36)}`;
  }

  function getCachedFeed(feedId) {
    try {
      const cached = JSON.parse(localStorage.getItem(cacheKey(feedId)) || 'null');
      return cached && Array.isArray(cached.items) ? cached : null;
    } catch { return null; }
  }

  function saveCachedFeed(feedId, result) {
    try {
      const cached = {fetched_utc: result.fetched_utc, stale: result.stale === true,
        items: result.items.slice(0, 20)};
      const encoded = JSON.stringify(cached);
      if (encoded.length > 40000) return;
      localStorage.setItem(cacheKey(feedId), encoded);
      const keys = [];
      for (let index = 0; index < localStorage.length; index++) {
        const key = localStorage.key(index);
        if (!key?.startsWith(cachePrefix)) continue;
        try { keys.push([key, JSON.parse(localStorage.getItem(key) || '{}').fetched_utc || '']); }
        catch { localStorage.removeItem(key); }
      }
      keys.sort((first, second) => first[1].localeCompare(second[1]));
      while (keys.length > 24) localStorage.removeItem(keys.shift()[0]);
    } catch { /* Storage can be unavailable or full. */ }
  }

  function formatPublishedTime(value) {
    if (!value) return translate('ui.0817');
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return translate('ui.0817');
    const options = {year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', timeZoneName: 'short'};
    const locale = document.documentElement.lang || 'en';
    try { return new Intl.DateTimeFormat(locale, {...options, timeZone: page.dataset.timezone}).format(date); }
    catch {
      try { return new Intl.DateTimeFormat(locale, {...options, timeZone: 'UTC'}).format(date); }
      catch { return `${date.toISOString()} UTC`; }
    }
  }

  function appendFeedItem(item, allowLinks) {
    const article = document.createElement('article');
    article.className = 'rss-entry';
    const header = document.createElement('div');
    header.className = 'rss-entry-head';
    const heading = document.createElement('h3');
    let articleUrl = '';
    if (allowLinks) {
      try {
        const url = new URL(item.link);
        if (url.protocol === 'https:' && !url.username && !url.password) articleUrl = url.href;
      } catch { /* Malformed publisher links are omitted. */ }
    }
    if (articleUrl) {
      const link = document.createElement('a');
      link.href = articleUrl; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = item.title; heading.append(link);
    } else heading.textContent = item.title;
    header.append(heading);
    const date = document.createElement('time'); date.className = 'rss-date';
    date.textContent = formatPublishedTime(item.published);
    if (item.published) date.dateTime = item.published;
    header.append(date); article.append(header);
    if (item.summary) { const summary = document.createElement('p'); summary.className = 'rss-summary'; summary.textContent = item.summary; article.append(summary); }
    feedItems.append(article);
  }

  function renderCachedFeed() {
    if (!feedSelect || !feedItems || !feedStatus) return;
    feedItems.replaceChildren();
    const cached = getCachedFeed(feedSelect.value);
    if (!cached) { feedStatus.textContent = translate('ui.0820'); return; }
    for (const item of cached.items) appendFeedItem(item, false);
    feedStatus.textContent = `${translate('ui.0821')} ${cached.fetched_utc || ''}`.trim();
  }

  function setOnlineLinksEnabled(enabled) {
    for (const link of page.querySelectorAll('[data-external-source]')) {
      if (enabled) {
        if (link.dataset.sourceHref) link.href = link.dataset.sourceHref;
        link.removeAttribute('aria-disabled'); link.removeAttribute('tabindex');
      } else {
        if (link.href) link.dataset.sourceHref = link.href;
        link.removeAttribute('href'); link.setAttribute('aria-disabled', 'true'); link.tabIndex = -1;
      }
    }
  }

  function applyConnectivity(available) {
    internetAvailable = available;
    const inactive = page.dataset.offlineDisplay === 'inactive';
    page.hidden = !available && !inactive;
    page.classList.toggle('offline-inactive', !available && inactive);
    setOnlineLinksEnabled(available);
    if (feedSelect) feedSelect.disabled = !available && !inactive;
    if (loadButton) loadButton.disabled = !available || !feedSelect?.value;
    if (!available && feedSelect) renderCachedFeed();
  }

  async function loadFeed() {
    if (!internetAvailable || !feedSelect?.value || loadingFeed) return;
    loadingFeed = true; loadButton.disabled = true;
    feedStatus.textContent = translate('ui.0765'); feedItems.replaceChildren();
    try {
      const query = new URLSearchParams({card: page.dataset.rssCard, feed: feedSelect.value});
      const response = await fetch(`/api/online/rss?${query}`, {cache: 'no-store', credentials: 'omit'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'RSS feed unavailable');
      if (!internetAvailable) return;
      const sorted = result.items.map((entry, index) => ({entry, index, date: Date.parse(entry.published)}));
      if (sorted.some(row => Number.isFinite(row.date))) sorted.sort((a, b) =>
        (Number.isFinite(b.date) ? b.date : -Infinity) - (Number.isFinite(a.date) ? a.date : -Infinity) || a.index - b.index);
      const ordered = sorted.map(row => row.entry);
      saveCachedFeed(feedSelect.value, {...result, items: ordered});
      if (!ordered.length) { feedStatus.textContent = translate('ui.0768'); return; }
      ordered.forEach(item => appendFeedItem(item, true));
      feedStatus.textContent = `${translate('ui.0766')} ${result.fetched_utc}${result.stale ? ` · ${translate('ui.0767')}` : ''}`;
    } catch {
      if (internetAvailable) {
        if (getCachedFeed(feedSelect.value)) renderCachedFeed();
        else feedStatus.textContent = translate('ui.0770');
      }
    } finally {
      loadingFeed = false;
      loadButton.disabled = !internetAvailable || !feedSelect?.value;
    }
  }

  async function updateInternet() {
    if (checkingInternet || document.hidden) return;
    checkingInternet = true;
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/connectivity/kiwix', {signal: controller.signal,
        cache: 'no-store', credentials: 'omit'});
      if (!response.ok) throw new Error('Connectivity check unavailable');
      const result = await response.json();
      applyConnectivity(result.available === true && navigator.onLine);
      if (internetAvailable && feedSelect?.value && !feedItems.children.length) await loadFeed();
    } catch { applyConnectivity(false); }
    finally { clearTimeout(timeout); checkingInternet = false; }
  }

  loadButton?.addEventListener('click', loadFeed);
  feedSelect?.addEventListener('change', () => internetAvailable ? loadFeed() : renderCachedFeed());
  window.addEventListener('offline', () => applyConnectivity(false));
  window.addEventListener('online', updateInternet);
  document.addEventListener('visibilitychange', updateInternet);
  if (feedSelect && !feedSelect.value) renderCachedFeed();
  updateInternet(); setInterval(updateInternet, 60000);
}
