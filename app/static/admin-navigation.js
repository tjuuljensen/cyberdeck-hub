// Prevent a browser's saved scroll position from overriding the Admin start link.
document.documentElement.classList.add('admin-initializing');
if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';

window.addEventListener('pageshow', () => {
  if (!window.location.hash || window.location.hash === '#admin-start') {
    window.scrollTo(0, 0);
  }
  requestAnimationFrame(() => {
    document.documentElement.classList.remove('admin-initializing');
  });
}, {once: true});
