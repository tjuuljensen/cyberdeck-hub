/* Dependency-free tests for client-side language discovery and API error formatting. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const english = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'app', 'translations', 'en.json'), 'utf8'));
const danish = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'app', 'translations', 'da.json'), 'utf8'));
const catalog = {};
const idByDefault = new Map();
for (const [id, entry] of Object.entries(english)) {
  const translated = danish[id] ?? entry.default;
  catalog[id] = translated;
  catalog[entry.default] = translated;
  idByDefault.set(entry.default, id);
}
const makeTextNode = (value) => ({
  nodeType: 3,
  nodeValue: value,
  parentElement: {closest: () => null}
});
const makeElement = (attributes = {}) => ({
  nodeType: 1,
  attributes: {...attributes},
  getAttribute(name) { return this.attributes[name] ?? null; },
  setAttribute(name, value) { this.attributes[name] = value; },
  querySelectorAll() { return []; }
});
const staticText = makeTextNode('Edit document');
const accessibilityLabel = makeElement({title: 'Show saved password'});
const main = makeElement();
main.querySelectorAll = () => [accessibilityLabel];
const body = makeElement();
body.classList = {toggle() {}};
body.querySelectorAll = () => [accessibilityLabel];
const mutationCallbacks = [];
class TestMutationObserver {
  constructor(callback) { mutationCallbacks.push(callback); }
  observe() {}
}
const context = {
  document: {
    body,
    documentElement: {dataset: {translations: JSON.stringify(catalog)}},
    querySelector: selector => selector === 'main' ? main : null,
    createTreeWalker: root => {
      const nodes = root === body || root === main ? [staticText] : [];
      let index = -1;
      return {
        currentNode: null,
        nextNode() {
          index += 1;
          if (index >= nodes.length) return false;
          this.currentNode = nodes[index];
          return true;
        }
      };
    }
  },
  Node: {TEXT_NODE: 3, ELEMENT_NODE: 1, DOCUMENT_FRAGMENT_NODE: 11},
  NodeFilter: {SHOW_TEXT: 4},
  MutationObserver: TestMutationObserver,
  window: {}
};
const source = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'i18n.js'), 'utf8');
vm.runInNewContext(source, context, {filename: 'i18n.js'});

assert.equal(staticText.nodeValue, 'Rediger dokument');
assert.equal(accessibilityLabel.attributes.title, 'Vis gemt adgangskode');
assert.equal(mutationCallbacks.length, 1, 'the main content should observe dynamic UI changes');
const insertedText = makeTextNode('Could not load saved password · enter a new one or use the eye to retry');
mutationCallbacks[0]([{type: 'childList', addedNodes: [insertedText]}]);
assert.equal(insertedText.nodeValue,
  'Kunne ikke hente den gemte adgangskode · indtast en ny, eller brug øjet for at prøve igen');
accessibilityLabel.attributes.title = 'Hide password';
mutationCallbacks[0]([{type: 'attributes', target: accessibilityLabel, addedNodes: []}]);
assert.equal(accessibilityLabel.attributes.title, 'Skjul adgangskode');

assert.equal(
  context.window.cyberdeckApiError({
    error: 'Import would overwrite existing files: {files}',
    error_params: {files: 'public/guide.pdf'}
  }, 409),
  'Importen ville overskrive eksisterende filer: public/guide.pdf'
);
for (const message of [
  'Combined bundle contains duplicate archive paths',
  'Duplicate catalogue upload filename'
]) {
  const translation = danish[idByDefault.get(message)];
  assert.notEqual(translation, english[idByDefault.get(message)].default);
  assert.equal(context.window.cyberdeckApiError({error: message}, 400), translation);
}
assert.equal(context.window.cyberdeckApiError({
  error: 'Subject {subject} already exists; map it to an existing subject',
  error_params: {subject: 'preparedness'}
}, 409), 'Emnet preparedness findes allerede; tilknyt det til et eksisterende emne');
assert.equal(context.window.cyberdeckApiError({
  error: 'Map imported subject {title} to an existing subject or create it',
  error_params: {title: 'Emergency planning'}
}, 409), 'Tilknyt det importerede emne Emergency planning til et eksisterende emne, eller opret det');
assert.equal(context.window.cyberdeckApiError({}, 502), 'Anmodningen mislykkedes (502)');
assert.equal(context.window.cyberdeckApiError({}, 500), 'Anmodningen mislykkedes (500)');
assert.equal(context.window.cyberdeckTranslate('Network request failed.'), 'Netværksanmodningen mislykkedes.');
assert.equal(context.window.cyberdeckNetworkError(), 'Netværksanmodningen mislykkedes.');
assert.equal(context.window.cyberdeckTranslate(
  'Online sources are recorded for later acquisition; preview does not download content.'
), 'Onlinekilder gemmes til senere hentning. Forhåndsvisningen downloader ikke indhold.');
assert.equal(
  context.window.cyberdeckTranslate('Documents could not be loaded. Use Refresh documents to retry.'),
  'Dokumenterne kunne ikke indlæses. Brug Opdater dokumenter for at prøve igen.'
);
