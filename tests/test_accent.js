/* Verify that accent-picker save failures use the selected interface language. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const english = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'app', 'translations', 'en.json'), 'utf8'));
const danish = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'app', 'translations', 'da.json'), 'utf8'));
const messages = {};
for (const [id, entry] of Object.entries(english)) {
  const translated = danish[id] ?? entry.default;
  messages[id] = translated;
  messages[entry.default] = translated;
}
const translate = (message, values = {}) => Object.entries(values).reduce(
  (result, [key, value]) => result.replaceAll(`{${key}}`, value),
  messages[message] ?? message
);
const handlers = {};
const input = {
  value: '#c4f36b',
  addEventListener: (event, handler) => { handlers[event] = handler; }
};
const status = {textContent: ''};
const theme = {href: ''};
const favicon = {href: ''};
const context = {
  document: {
    querySelector(selector) {
      if (selector === '#preferences-form [name="accent_color"]') return input;
      if (selector === '#accent-color-status') return status;
      if (selector === '.admin-head') return {dataset: {csrf: 'test-token'}};
      if (selector === '#site-accent-theme') return theme;
      if (selector === '#site-favicon') return favicon;
      if (selector === 'meta[name="theme-color"]') return {setAttribute() {}};
      return null;
    }
  },
  window: {
    cyberdeckTranslate: translate,
    cyberdeckApiError(body, code) {
      return translate(body.error || 'Request failed ({status})',
                       body.error_params || {status: code});
    }
  },
  fetch: async () => ({
    ok: false,
    status: 503,
    json: async () => ({error: 'Request failed ({status})', error_params: {status: 503}})
  }),
  clearTimeout() {},
  setTimeout() { return 1; },
  TypeError
};

const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'accent.js'), 'utf8');
vm.runInNewContext(source, context, {filename: 'accent.js'});

async function verify() {
  input.value = '#79ace6';
  handlers.input();
  assert.equal(favicon.href, '/favicon.svg?color=%2379ace6');
  assert.equal(status.textContent, 'Gemmer farven…');
  await handlers.change();
  assert.equal(status.textContent, 'Farven blev ikke gemt: Anmodningen mislykkedes (503)');
}

verify().catch(error => {
  process.exitCode = 1;
  console.error(error);
});
