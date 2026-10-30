// Persist the site-wide accent independently of the larger admin interface script.
(() => {
  const t = window.cyberdeckTranslate;
  const input = document.querySelector('#preferences-form [name="accent_color"]');
  const status = document.querySelector('#accent-color-status');
  const csrf = document.querySelector('.admin-head')?.dataset.csrf;
  const themeLink = document.querySelector('#site-accent-theme');
  if (!themeLink) return;

  window.cyberdeckSetAccent = color => {
    themeLink.href = `/accent.css?color=${encodeURIComponent(color)}`;
    const favicon = document.querySelector('#site-favicon');
    if (favicon) favicon.href = `/favicon.svg?color=${encodeURIComponent(color)}`;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', color);
  };
  if (!input || !status || !csrf) return;

  let timer = null;
  let revision = 0;
  let savedColor = input.value.toLowerCase();
  let saveQueue = Promise.resolve();

  function saveAccent(force = false) {
    clearTimeout(timer);
    timer = null;
    const color = input.value.toLowerCase();
    const requestedRevision = revision;
    if (!force && color === savedColor) return saveQueue;

    status.textContent = t('ui.0343');
    const save = async () => {
      const response = await fetch('/api/admin/settings/accent', {
        method: 'PUT',
        cache: 'no-store',
        keepalive: true,
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({accent_color: color})
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(window.cyberdeckApiError(result, response.status));
      if (result.accent_color !== color) throw new Error(t('ui.0345'));
      return result.accent_color;
    };

    const pending = saveQueue.catch(() => {}).then(save);
    saveQueue = pending;
    return pending.then(saved => {
      savedColor = saved;
      if (requestedRevision === revision) {
        window.cyberdeckSetAccent(saved);
        status.textContent = t('ui.0367');
      } else {
        timer = setTimeout(() => saveAccent().catch(() => {}), 0);
      }
    }).catch(error => {
      if (requestedRevision === revision) {
        const message = error instanceof TypeError ? window.cyberdeckNetworkError() : error.message;
        status.textContent = t('ui.0344', {error: message});
      }
      throw error;
    });
  }

  input.addEventListener('input', () => {
    revision++;
    window.cyberdeckSetAccent(input.value);
    status.textContent = t('ui.0343');
    clearTimeout(timer);
    timer = setTimeout(() => saveAccent().catch(() => {}), 350);
  });
  input.addEventListener('change', () => saveAccent().catch(() => {}));
  document.querySelector('#accent-color-reset')?.addEventListener('click', event => {
    input.value = event.currentTarget.dataset.defaultColor;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  });
  window.cyberdeckSaveAccent = () => saveAccent(true);
})();
