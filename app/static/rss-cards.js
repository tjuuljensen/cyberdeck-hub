/* Show online-only cards according to each card's offline display preference. */
const onlineGroup = document.querySelector('#online-crisis-group');
let checkingInternet = false;

function applyInternetAvailability(available) {
  if (!onlineGroup) return;
  const cards = [...onlineGroup.querySelectorAll('.resource-home-card')];
  for (const card of cards) {
    const inactive = !available && card.dataset.offlineDisplay === 'inactive';
    card.hidden = !available && !inactive;
    card.classList.toggle('offline-inactive', inactive);
  }
  onlineGroup.hidden = !cards.some(card => !card.hidden);
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
    if (!response.ok) throw new Error('Connectivity check failed');
    const result = await response.json();
    applyInternetAvailability(result.available === true && navigator.onLine);
  } catch {
    applyInternetAvailability(false);
  } finally {
    clearTimeout(timeout);
    checkingInternet = false;
  }
}

window.addEventListener('offline', () => applyInternetAvailability(false));
window.addEventListener('online', updateInternet);
document.addEventListener('visibilitychange', updateInternet);
updateInternet();
setInterval(updateInternet, 60000);
