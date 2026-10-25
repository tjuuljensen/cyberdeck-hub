const t = window.cyberdeckTranslate;
const onlineContent = document.querySelector('#online-crisis-content');
const feedSelect = document.querySelector('#police-rss-feed');
const loadButton = document.querySelector('#police-rss-load');
const feedStatus = document.querySelector('#police-rss-status');
const feedItems = document.querySelector('#police-rss-items');
let internetAvailable = false;
let connectivityCheckRunning = false;
let feedLoadRunning = false;

function clearFeed() {
  feedItems.replaceChildren();
}

async function checkInternet() {
  if (connectivityCheckRunning || document.hidden) return;
  connectivityCheckRunning = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('/api/connectivity/kiwix', {
      signal: controller.signal, cache: 'no-store', credentials: 'omit'
    });
    if (!response.ok) throw new Error('Connectivity check unavailable');
    const state = await response.json();
    internetAvailable = state.available === true && navigator.onLine;
    onlineContent.hidden = !internetAvailable;
    if (!internetAvailable) clearFeed();
  } catch {
    internetAvailable = false;
    onlineContent.hidden = true;
    clearFeed();
  } finally {
    clearTimeout(timeout);
    connectivityCheckRunning = false;
  }
}

function appendFeedItem(item) {
  const article = document.createElement('article');
  article.className = 'rss-entry';
  const heading = document.createElement('h3');
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
    summary.textContent = item.summary;
    article.append(summary);
  }
  if (item.link && /^https:\/\//i.test(item.link)) {
    const link = document.createElement('a');
    link.href = item.link;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = t('ui.0771');
    article.append(link);
  }
  feedItems.append(article);
}

loadButton.addEventListener('click', async () => {
  if (!internetAvailable || feedLoadRunning) return;
  feedLoadRunning = true;
  loadButton.disabled = true;
  feedStatus.textContent = t('ui.0765');
  clearFeed();
  try {
    const url = `/api/online/police-rss?feed=${encodeURIComponent(feedSelect.value)}`;
    const response = await fetch(url, {cache: 'no-store', credentials: 'omit'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'RSS feed unavailable');
    if (!internetAvailable) return;
    if (result.items.length === 0) {
      feedStatus.textContent = t('ui.0768');
      return;
    }
    for (const item of result.items) appendFeedItem(item);
    feedStatus.textContent = `${t('ui.0766')} ${result.fetched_utc}${result.stale ? ` · ${t('ui.0767')}` : ''}`;
  } catch {
    if (internetAvailable) feedStatus.textContent = t('ui.0770');
  } finally {
    feedLoadRunning = false;
    loadButton.disabled = !internetAvailable;
  }
});

window.addEventListener('offline', () => {
  internetAvailable = false;
  onlineContent.hidden = true;
  loadButton.disabled = true;
  clearFeed();
});
window.addEventListener('online', checkInternet);
document.addEventListener('visibilitychange', checkInternet);
checkInternet();
setInterval(checkInternet, 60000);
