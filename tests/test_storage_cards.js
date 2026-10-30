/* Disk cards follow live mount state and wait for the host operation to finish. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app/static/admin.js'), 'utf8');
const english = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'app/translations/en.json'), 'utf8'));
const danish = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'app/translations/da.json'), 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ''; }
  append(...children) { this.children.push(...children); }
  get childElementCount() { return this.children.length; }
}
const descendants = element => [element, ...element.children.flatMap(descendants)];
const context = {
  document: {createElement: tag => new Element(tag)},
  t(id, values = {}) {
    return Object.entries(values).reduce((result, [key, value]) => result.replaceAll(`{${key}}`, value),
      english[id]?.default || id);
  },
  formatBytes: bytes => String(bytes),
  storageButton(label, handler) {
    const button = new Element('button');
    button.textContent = context.t(label);
    button.click = handler;
    return button;
  },
  renderStorageDiskUsage() {},
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function createStorageCard(disk){'),
                            source.indexOf('async function refreshStorage(){')), context);
vm.runInContext(source.slice(source.indexOf('async function changeStorageMount('),
                            source.indexOf('async function useExistingStorage(')), context);
const mount = '/mnt/cyberdeck-disks/12345678-1234-1234-1234-123456789abc';
const disk = {model: 'Test USB disk', stable_id: 'usb-test', adopted: true, adoptable: true,
              managed_mount: mount, mount, partitions: [{filesystem: 'ext4', size_bytes: 100}]};
const primary = card => descendants(card).find(item => item.className === 'storage-disk-primary-actions');

async function verify() {
  const mounted = context.createStorageCard(disk);
  assert.deepEqual(primary(mounted).children.map(item => item.textContent), ['Unmount']);
  assert(descendants(mounted).some(item => item.textContent === `Mounted at ${mount}`));
  const unmounted = context.createStorageCard({...disk, mount: null});
  assert.deepEqual(primary(unmounted).children.map(item => item.textContent), ['Mount']);
  assert(descendants(unmounted).some(item => item.textContent === 'Unmounted'));
  assert(!descendants(unmounted).some(item => item.textContent.startsWith('Mounted at ')));
  assert.equal(primary(context.createStorageCard({...disk, system_disk: true})).children.length, 0);
  const systemCard = context.createStorageCard({...disk, model: 'Unknown disk', system_disk: true});
  assert(descendants(systemCard).some(item => item.tag === 'h4' && item.textContent.startsWith('System storage')));
  assert(!descendants(systemCard).some(item => item.textContent.includes('Unknown disk')));
  assert.equal(primary(context.createStorageCard({...disk, active_data_disk: true})).children.length, 0);
  assert.equal(primary(context.createStorageCard({...disk, adoption_stale: true})).children.length, 0);

  const calls = [];
  let complete;
  const worker = new Promise(resolve => { complete = resolve; });
  context.beginStorageOperation = message => calls.push(message);
  context.postStorage = async (action, target) => calls.push([action, target.stable_id]);
  context.watchStorageOperation = async (kind, identity) => {
    calls.push([kind, identity]);
    await worker;
  };
  context.finishStorageOperation = message => calls.push(message);
  let returned = false;
  const pending = primary(mounted).children[0].click().then(() => { returned = true; });
  await new Promise(setImmediate);
  assert.deepEqual(calls, ['Unmounting adopted disk…', ['unmount', 'usb-test'], ['initialization', 'usb-test']]);
  assert.equal(returned, false, 'a queued action must not be reported as completed');
  complete();
  await pending;
  assert.equal(returned, true);

  context.postStorage = async () => { throw new Error('busy disk'); };
  await primary(unmounted).children[0].click();
  assert.equal(calls.at(-1), 'busy disk');
  for (const id of ['ui.0880', 'ui.0881', 'ui.0882', 'ui.0883', 'ui.0884', 'ui.0885', 'ui.0886', 'ui.0887']) {
    assert.equal(typeof danish[id], 'string', `${id} must have a Danish translation`);
  }
  console.log('Storage mount card checks passed.');
}
verify().catch(error => { console.error(error); process.exitCode = 1; });
