const onlineCatalog = document.querySelector('#online-kiwix-catalog');
let checkingCatalog = false;
async function updateCatalogAvailability() {
  if (!onlineCatalog || checkingCatalog || document.hidden) return;
  checkingCatalog = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('/api/connectivity/kiwix', {
      signal: controller.signal, cache: 'no-store', credentials: 'omit'
    });
    if (!response.ok) throw new Error('Connectivity check unavailable');
    const state = await response.json();
    onlineCatalog.hidden = state.available !== true;
  } catch {
    onlineCatalog.hidden = true;
  } finally {
    clearTimeout(timeout);
    checkingCatalog = false;
  }
}
updateCatalogAvailability();
setInterval(updateCatalogAvailability, 60000);
document.addEventListener('visibilitychange', updateCatalogAvailability);
window.addEventListener('online', updateCatalogAvailability);
window.addEventListener('offline', () => {
  if (onlineCatalog) onlineCatalog.hidden = true;
});
// A page restored from browser history may contain the accent from before an
// administrator changed it; reload the shared preference from the server.
window.addEventListener('pageshow', event => {
  if (event.persisted) window.location.reload();
});
