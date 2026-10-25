// Let explicit Admin fragments win over saved scroll and late focus restoration.
document.documentElement.classList.add('admin-initializing');
if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';

window.addEventListener('pageshow', () => {
  const positionFromLocation = () => {
    const target = window.location.hash
      ? document.getElementById(decodeURIComponent(window.location.hash.slice(1)))
      : null;
    if (target) target.scrollIntoView({block: 'start'});
    else if (!window.location.hash) window.scrollTo(0, 0);
  };
  positionFromLocation();
  requestAnimationFrame(() => requestAnimationFrame(() => {
    positionFromLocation();
    document.documentElement.classList.remove('admin-initializing');
  }));
}, {once: true});
