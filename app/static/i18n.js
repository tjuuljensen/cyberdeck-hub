/* Shared client-side localization for static and dynamically rendered UI text. */
const catalog = JSON.parse(document.documentElement.dataset.translations || '{}');
const translationIdsByValue = new Map();
for (const [messageId, value] of Object.entries(catalog)) {
  if (!/^ui\.\d{4}$/.test(messageId) || typeof value !== 'string') continue;
  const ids = translationIdsByValue.get(value) || [];
  ids.push(messageId);
  translationIdsByValue.set(value, ids);
}
const translationIdModeKey = 'cyberdeck.translation-id-mode';
let translationIdMode = false;
try {
  translationIdMode = localStorage.getItem(translationIdModeKey) === 'true';
} catch (_) {}
const translationMessagePatterns = Object.entries(catalog)
  .filter(([messageId, value]) => /^ui\.\d{4}$/.test(messageId) && typeof value === 'string' && value.includes('{'))
  .map(([messageId, value]) => ({
    messageId,
    pattern: new RegExp(`^${value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\{[^{}]+\\\}/g, '.*?')}$`)
  }));

function translationIdsFor(value) {
  const exact = translationIdsByValue.get(value);
  if (exact) return exact;
  return translationMessagePatterns.filter(({pattern}) => pattern.test(value)).map(({messageId}) => messageId);
}

document.querySelector('.language-picker select')?.addEventListener('change', event => {
  event.currentTarget.form?.requestSubmit();
});

function cyberdeckTranslate(message, values = {}) {
  return Object.entries(values).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, value),
    catalog[message] ?? message
  );
}

function cyberdeckApiError(body, status) {
  if (typeof body.error !== 'string') {
    return cyberdeckTranslate('ui.0523', {status});
  }
  return cyberdeckTranslate(body.error, body.error_params || {});
}

function cyberdeckNetworkError() {
  return cyberdeckTranslate('ui.0346');
}

function localizeUi(root) {
  if (!root) return;
  const translateNode = node => {
    const leading = node.nodeValue.match(/^\s*/)?.[0] || '';
    const trailing = node.nodeValue.match(/\s*$/)?.[0] || '';
    let source = node.nodeValue.slice(leading.length, node.nodeValue.length - trailing.length || undefined);
    if (!source) return;
    const existingId = source.match(/^\[(ui\.\d{4}(?:, ui\.\d{4})*)\]\s+/);
    if (existingId) source = source.slice(existingId[0].length);
    const localized = cyberdeckTranslate(source);
    const localizedIds = translationIdMode ? translationIdsFor(localized) : [];
    const ids = localizedIds.length ? localizedIds : translationIdMode ? translationIdsFor(source) : [];
    const prefix = translationIdMode && ids?.length ? `[${ids.join(', ')}] ` : '';
    const next = `${leading}${prefix}${localized}${trailing}`;
    if (next !== node.nodeValue) node.nodeValue = next;
  };
  const localizeAttribute = (element, attribute) => {
    let source = element.getAttribute(attribute);
    if (!source) return;
    const existingId = source.match(/^\[(ui\.\d{4}(?:, ui\.\d{4})*)\]\s+/);
    if (existingId) source = source.slice(existingId[0].length);
    const localized = cyberdeckTranslate(source);
    const localizedIds = translationIdMode ? translationIdsFor(localized) : [];
    const ids = localizedIds.length ? localizedIds : translationIdMode ? translationIdsFor(source) : [];
    const prefix = translationIdMode && ids?.length ? `[${ids.join(', ')}] ` : '';
    const next = `${prefix}${localized}`;
    if (next !== element.getAttribute(attribute)) element.setAttribute(attribute, next);
  };
  const translateAttributes = element => {
    for (const attribute of ['aria-label', 'placeholder', 'title']) {
      localizeAttribute(element, attribute);
    }
  };
  if (root.nodeType === Node.TEXT_NODE) {
    if (!root.parentElement?.closest('script,style,textarea')) translateNode(root);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement?.closest('script,style,textarea')) translateNode(walker.currentNode);
  }
  if (root.querySelectorAll) root.querySelectorAll('[aria-label],[placeholder],[title]').forEach(translateAttributes);
}

function setTranslationIdMode(enabled) {
  translationIdMode = enabled;
  try {
    localStorage.setItem(translationIdModeKey, String(enabled));
  } catch (_) {}
  document.body.classList.toggle('translation-id-mode', enabled);
  localizeUi(document.body);
}

window.cyberdeckTranslate = cyberdeckTranslate;
window.cyberdeckApiError = cyberdeckApiError;
window.cyberdeckNetworkError = cyberdeckNetworkError;
localizeUi(document.body);
document.body.classList.toggle('translation-id-mode', translationIdMode);
document.querySelector('#translation-id-mode')?.addEventListener('change', event => {
  setTranslationIdMode(event.currentTarget.checked);
});
const translationIdToggle = document.querySelector('#translation-id-mode');
if (translationIdToggle) translationIdToggle.checked = translationIdMode;
const localizedRoot = document.querySelector('main');
if (localizedRoot) {
  new MutationObserver(records => {
    for (const record of records) {
      for (const node of record.addedNodes) localizeUi(node);
      if (record.type === 'characterData') localizeUi(record.target);
      if (record.type === 'attributes') localizeUi(record.target);
    }
  }).observe(document.body, {subtree: true, childList: true, characterData: true,
                             attributes: true, attributeFilter: ['aria-label', 'placeholder', 'title']});
}
