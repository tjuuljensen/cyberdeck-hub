/* Exercise offline hiding and safe DOM rendering for the online links/RSS page. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'online-crisis-links.js'), 'utf8');

function makePage({available, feedResult}) {
  const handlers = {};
  const windowEvents = {};
  const requests = [];
  const elements = {
    content: {hidden: true},
    select: {value: 'all', addEventListener(event, handler) { handlers[`select:${event}`] = handler; }},
    button: {disabled: false, addEventListener(event, handler) { handlers[event] = handler; }},
    status: {textContent: ''},
    items: {
      children: [],
      replaceChildren() { this.children = []; },
      append(element) { this.children.push(element); }
    }
  };
  const selectors = new Map([
    ['#online-crisis-content', elements.content],
    ['#police-rss-feed', elements.select],
    ['#police-rss-load', elements.button],
    ['#police-rss-status', elements.status],
    ['#police-rss-items', elements.items]
  ]);
  const context = {
    document: {
      hidden: false,
      querySelector: selector => selectors.get(selector) || null,
      addEventListener: (event, handler) => { handlers[`document:${event}`] = handler; },
      createElement(tag) {
        return {
          tagName: tag,
          children: [],
          append(element) { this.children.push(element); }
        };
      }
    },
    window: {
      cyberdeckTranslate: message => message,
      addEventListener: (event, handler) => { windowEvents[event] = handler; }
    },
    navigator: {onLine: true},
    fetch: async (url, options) => {
      requests.push({url, options});
      if (url === '/api/connectivity/kiwix') {
        return {ok: true, json: async () => ({available})};
      }
      if (url.startsWith('/api/online/police-rss?')) {
        return {ok: true, json: async () => feedResult};
      }
      throw new Error(`Unexpected URL: ${url}`);
    },
    AbortController,
    setTimeout: () => 1,
    clearTimeout() {},
    setInterval() {}
  };
  vm.runInNewContext(source, context, {filename: 'online-crisis-links.js'});
  return {elements, handlers, windowEvents, requests};
}

async function flush() {
  await new Promise(resolve => setImmediate(resolve));
}

async function verifyOfflineHiding() {
  const page = makePage({available: false, feedResult: {items: []}});
  await flush();
  assert.equal(page.elements.content.hidden, true);
  assert.equal(page.requests.filter(request => request.url.startsWith('/api/online/')).length, 0);
  await page.handlers.click();
  assert.equal(page.requests.filter(request => request.url.startsWith('/api/online/')).length, 0);
  page.windowEvents.offline();
  assert.equal(page.elements.content.hidden, true);
  assert.equal(page.elements.button.disabled, true);
  assert.equal(page.elements.items.children.length, 0);
}

async function verifySafeFeedRendering() {
  const title = '<img src=x onerror=alert(1)>Police update';
  const summary = '<script>bad()</script>Road closed';
  const page = makePage({available: true, feedResult: {
    items: [{title, summary, published: '2026-10-25', link: 'https://politi.dk/notice/1'}],
    fetched_utc: '2026-10-25T08:00:00Z', stale: false
  }});
  await flush();
  assert.equal(page.elements.content.hidden, false);
  await page.handlers.click();
  assert.equal(page.elements.items.children.length, 1);
  const entry = page.elements.items.children[0];
  assert.equal(entry.children[0].textContent, title);
  assert.equal(entry.children[1].textContent, '2026-10-25');
  assert.equal(entry.children[2].textContent, summary);
  assert.equal(entry.children[3].href, 'https://politi.dk/notice/1');
  assert.equal(entry.children[0].innerHTML, undefined);
  page.windowEvents.offline();
  assert.equal(page.elements.content.hidden, true);
  assert.equal(page.elements.items.children.length, 0);
}

Promise.all([verifyOfflineHiding(), verifySafeFeedRendering()]).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
