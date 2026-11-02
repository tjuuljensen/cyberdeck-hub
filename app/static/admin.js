const headers = {'X-CSRF-Token': document.querySelector('.admin-head').dataset.csrf};
const t = window.cyberdeckTranslate;
const nativeAlert = window.alert.bind(window);
window.alert = message => nativeAlert(t(String(message)));
const exportForm = document.querySelector('#export-form');
const exportOptions = document.querySelector('#export-options');
const exportStatus = document.querySelector('#export-status');
const exportDownloads = document.querySelector('#export-downloads');
let exportObjectUrl = null;
function clearExportDownloads() {
  if (exportObjectUrl) URL.revokeObjectURL(exportObjectUrl);
  exportObjectUrl = null;
  exportDownloads.replaceChildren();
}
async function refreshExportOptions() {
  clearExportDownloads();
  exportStatus.textContent = t('ui.0069');
  exportForm.querySelector('[type="submit"]').disabled = true;
  try {
    const [entries, cardOptions] = await Promise.all([
      requestJson('/api/admin/export/options'), requestJson('/api/admin/export/cards')
    ]);
    const intro = document.createElement('p');
    intro.className = 'subtle export-options-intro';
    intro.textContent = t('ui.0836');
    exportOptions.replaceChildren(intro);

    const makeCategory = (title, {name = '', checked = false, description = ''} = {}) => {
      const details = document.createElement('details');
      details.className = 'export-category';
      const summary = document.createElement('summary');
      const toggle = document.createElement('input');
      toggle.type = 'checkbox';
      toggle.setAttribute('aria-label', t(title));
      if (name) toggle.name = name;
      else toggle.dataset.exportGroup = 'true';
      toggle.checked = checked;
      const heading = document.createElement('span');
      heading.textContent = t(title);
      summary.append(toggle, heading);
      details.append(summary);
      if (description) {
        const help = document.createElement('p');
        help.className = 'subtle export-category-help';
        help.textContent = t(description);
        details.append(help);
      }
      return {details, toggle};
    };
    const makeItemGroup = (title, groupEntries, {includePdfToggle = false} = {}) => {
      const category = makeCategory(title);
      category.details.open = true;
      const heading = category.details.querySelector('summary span');
      if (heading) heading.textContent = `${t(title)} (${groupEntries.length})`;
      const list = document.createElement('div');
      list.className = 'export-category-items';
      if (includePdfToggle) {
        const pdfToggleLabel = document.createElement('label');
        pdfToggleLabel.className = 'check export-pdf-toggle';
        const pdfToggle = document.createElement('input');
        pdfToggle.type = 'checkbox'; pdfToggle.name = 'include_online_source_pdfs';
        const pdfToggleText = document.createElement('span');
        pdfToggleText.textContent = t('ui.0864');
        pdfToggleLabel.append(pdfToggle, pdfToggleText);
        category.details.append(pdfToggleLabel);
        const pdfHelp = document.createElement('p');
        pdfHelp.className = 'subtle export-category-help';
        pdfHelp.textContent = t('ui.0865');
        category.details.append(pdfHelp);
      }
      const checkboxes = [];
      for (const entry of groupEntries) {
        const label = document.createElement('label');
        label.className = 'check';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; checkbox.name = 'selected'; checkbox.value = entry.id;
        // Keep the established default: URL-based content is selected; local files are not.
        checkbox.checked = entry.mode === 'online';
        const text = document.createElement('span');
        text.textContent = `${entry.title} · ${t(entry.subject || 'Unassigned')}`;
        label.append(checkbox, text); list.append(label); checkboxes.push(checkbox);
      }
      if (!groupEntries.length) {
        const empty = document.createElement('p');
        empty.className = 'subtle'; empty.textContent = t('ui.0837'); list.append(empty);
      }
      category.details.append(list);
      const updateMaster = () => {
        const selectedCount = checkboxes.filter(input => input.checked).length;
        category.toggle.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
        category.toggle.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
      };
      category.toggle.addEventListener('change', () => {
        checkboxes.forEach(input => { input.checked = category.toggle.checked; });
        category.toggle.indeterminate = false;
      });
      checkboxes.forEach(input => input.addEventListener('change', updateMaster));
      updateMaster();
      return category.details;
    };
    const makeCardGroup = (title, cards, name, description) => {
      const category = makeCategory(title, {description});
      const list = document.createElement('div'); list.className = 'export-category-items';
      const checkboxes = [];
      for (const card of cards) {
        const label = document.createElement('label'); label.className = 'check';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox';
        checkbox.name = name; checkbox.value = card.id; checkbox.checked = true;
        const text = document.createElement('span');
        text.textContent = `${card.title} · ${(card.entries || card.feeds || card.links || []).length} entries`;
        label.append(checkbox, text); list.append(label); checkboxes.push(checkbox);
      }
      if (!cards.length) { const empty = document.createElement('p'); empty.className = 'subtle'; empty.textContent = t('ui.0837'); list.append(empty); }
      category.details.append(list);
      const updateMaster = () => { const count = checkboxes.filter(input => input.checked).length; category.toggle.checked = checkboxes.length > 0 && count === checkboxes.length; category.toggle.indeterminate = count > 0 && count < checkboxes.length; };
      category.toggle.addEventListener('change', () => { checkboxes.forEach(input => { input.checked = category.toggle.checked; }); category.toggle.indeterminate = false; });
      checkboxes.forEach(input => input.addEventListener('change', updateMaster)); updateMaster();
      return category.details;
    };

    appendSiteSettingsGroup({site_settings:cardOptions.site_settings},exportOptions,
      {masterName:'include_settings',leafName:'export_site_setting_keys'});
    exportOptions.append(makeItemGroup('ui.0840', entries.filter(entry => entry.category === 'zims')));

    const documents = document.createElement('details');
    documents.className = 'export-category';
    documents.open = true;
    const documentsSummary = document.createElement('summary');
    documentsSummary.textContent = t('ui.0841');
    documents.append(documentsSummary,
      makeItemGroup('ui.0842', entries.filter(entry => entry.category === 'documents-online'), {includePdfToggle: true}),
      makeItemGroup('ui.0843', entries.filter(entry => entry.category === 'documents-local')));
    exportOptions.append(documents);

    exportOptions.append(makeCardGroup('ui.0844', cardOptions.online_source_cards, 'online_source_card_ids', 'ui.0846'));
    exportOptions.append(makeCardGroup('ui.0845', cardOptions.rss_cards, 'rss_card_ids', 'ui.0847'));

    exportStatus.textContent = t(entries.length ? 'ui.0848' : 'ui.0849');
    exportForm.querySelector('[type="submit"]').disabled = false;
  } catch (error) { exportStatus.textContent = error.message; }
}
document.querySelector('#export-reload').onclick = refreshExportOptions;
for (const [id, checked] of [['export-all', true], ['export-none', false]]) {
  document.getElementById(id).onclick = () => {
    exportOptions.querySelectorAll('input[type="checkbox"]').forEach(input => {
      input.checked = checked; input.indeterminate = false;
    });
    clearExportDownloads();
  };
}
exportForm.addEventListener('change', clearExportDownloads);
exportForm.addEventListener('submit', async event => {
  event.preventDefault(); clearExportDownloads();
  const button = exportForm.querySelector('[type="submit"]');
  button.disabled = true; exportStatus.textContent = t('ui.0237');
  try {
    const selected = [...exportOptions.querySelectorAll('input[name="selected"]:checked')].map(input => input.value);
    const onlineSourceCardIds = [...exportOptions.querySelectorAll('input[name="online_source_card_ids"]:checked')].map(input => input.value);
    const rssCardIds = [...exportOptions.querySelectorAll('input[name="rss_card_ids"]:checked')].map(input => input.value);
    const siteSettingKeys = [...exportOptions.querySelectorAll('input[name="export_site_setting_keys"]:checked')].map(input => input.value);
    const result = await requestJson('/api/admin/export', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: exportForm.elements.name.value, selected,
        include_settings: siteSettingKeys.length > 0,site_setting_keys:siteSettingKeys,
        include_online_source_cards: onlineSourceCardIds.length > 0,
        include_rss_cards: rssCardIds.length > 0,
        online_source_card_ids: onlineSourceCardIds, rss_card_ids: rssCardIds,
        include_online_source_pdfs: exportForm.elements.include_online_source_pdfs.checked})});
    exportObjectUrl = URL.createObjectURL(new Blob([JSON.stringify(result.config, null, 2) + '\n'], {type: 'application/json'}));
    const link = document.createElement('a');
    link.className = 'button primary'; link.href = exportObjectUrl; link.download = result.filename;
    link.textContent = t('ui.0238', {filename: result.filename}); exportDownloads.append(link);
    for (const catalogue of result.catalogues) {
      // Native downloads keep large ZIPs out of browser JavaScript memory.
      const form = document.createElement('form');
      form.method = 'POST'; form.action = '/api/admin/export/catalogue'; form.target = '_blank'; form.rel = 'noopener';
      for (const [name, value] of [['csrf_token', headers['X-CSRF-Token']], ['token', catalogue.token]]) {
        const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; form.append(input);
      }
      const download = document.createElement('button'); download.type = 'submit'; download.className = 'button';
      download.textContent = t('ui.0239', {title: catalogue.title, size: formatBytes(catalogue.bytes)});
      form.append(download); exportDownloads.append(form);
    }
    const bundleForm=document.createElement('form');bundleForm.method='POST';bundleForm.action='/api/admin/export/bundle';bundleForm.target='_blank';bundleForm.rel='noopener';
    const bundleFields=[['csrf_token',headers['X-CSRF-Token']],['name',exportForm.elements.name.value],
      ['include_settings',String(siteSettingKeys.length > 0)],
      ['include_online_source_cards',String(onlineSourceCardIds.length > 0)],
      ['include_rss_cards',String(rssCardIds.length > 0)],
      ['include_online_source_pdfs',String(exportForm.elements.include_online_source_pdfs.checked)],
      ...onlineSourceCardIds.map(value=>['online_source_card_ids',value]),
      ...rssCardIds.map(value=>['rss_card_ids',value]),
      ...siteSettingKeys.map(value=>['site_setting_keys',value]),
      ...selected.map(value=>['selected',value])];
    for(const[name,value]of bundleFields){const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;bundleForm.append(input)}
    const bundleButton=document.createElement('button');bundleButton.type='submit';bundleButton.className='button primary';bundleButton.textContent=t('ui.0240');bundleForm.append(bundleButton);exportDownloads.append(bundleForm);
    exportStatus.textContent = t('ui.0241', {online: result.config.assets.length, catalogues: result.catalogues.length});
  } catch (error) { exportStatus.textContent = error.message; }
  finally { button.disabled = false; }
});
const importForm = document.querySelector('#import-form');
const importPreview = document.querySelector('#import-preview');
const importStatus = document.querySelector('#import-status');
const importProfile = document.querySelector('#import-profile');
const importProfileLabel = document.querySelector('#import-profile-label');
let importPlan = null;
function appendSiteSettingsGroup(result,root=importPreview,{masterName='apply_display_preferences',leafName='site_setting_keys'}={}){
  const settings=result.site_settings||{};
  const groups=[
    {title:'ui.0876',keys:['pdf_open_mode','accent_color','home_columns']},
    {title:'ui.0877',keys:['subtitle','display_timezone','show_start_card']},
  ];
  const labels={pdf_open_mode:'ui.0093',accent_color:'ui.0097',home_columns:'ui.0100',
    subtitle:'ui.0104',display_timezone:'ui.0815',show_start_card:'ui.0878'};
  const rows=groups.map(group=>({...group,keys:group.keys.filter(key=>Object.prototype.hasOwnProperty.call(settings,key))}));
  const known=new Set(rows.flatMap(group=>group.keys));
  const extraKeys=Object.keys(settings).filter(key=>!known.has(key));
  rows[1].keys.push(...extraKeys);
  if(!rows.some(group=>group.keys.length))return null;

  const details=document.createElement('details');details.className='export-category site-settings-category';
  const summary=document.createElement('summary');
  const master=document.createElement('input');master.type='checkbox';master.name=masterName;
  master.setAttribute('aria-label',t('ui.0838'));
  const heading=document.createElement('span');heading.textContent=t('ui.0838');
  summary.append(master,heading);details.append(summary);
  const help=document.createElement('p');help.className='subtle export-category-help';help.textContent=t('ui.0839');details.append(help);
  const allLeaves=[];const groupControls=[];
  const displayValue=(key,value)=>{
    if(key==='pdf_open_mode')return t(value==='same_tab'?'ui.0094':'ui.0095');
    if(key==='accent_color')return String(value);
    if(key==='home_columns')return t(`ui.${({'3':'0101','4':'0102','5':'0103'})[String(value)]||'0101'}`);
    if(key==='show_start_card')return t(value===true||value==='true'?'ui.0432':'ui.0433');
    if(typeof value==='string')return value;
    return JSON.stringify(value);
  };
  const syncParents=()=>{
    for(const group of groupControls){
      const count=group.leaves.filter(input=>input.checked).length;
      group.checkbox.checked=group.leaves.length>0&&count===group.leaves.length;
      group.checkbox.indeterminate=count>0&&count<group.leaves.length;
    }
    const count=allLeaves.filter(input=>input.checked).length;
    master.checked=allLeaves.length>0&&count===allLeaves.length;
    master.indeterminate=count>0&&count<allLeaves.length;
  };
  for(const group of rows){
    if(!group.keys.length)continue;
    const subsection=document.createElement('details');subsection.className='export-category import-settings-subcategory';
    const subSummary=document.createElement('summary');
    const subMaster=document.createElement('input');subMaster.type='checkbox';subMaster.setAttribute('aria-label',t(group.title));
    const subHeading=document.createElement('span');subHeading.textContent=t(group.title);
    subSummary.append(subMaster,subHeading);subsection.append(subSummary);
    const list=document.createElement('div');list.className='export-category-items';const leaves=[];
    for(const key of group.keys){
      const label=document.createElement('label');label.className='check import-setting-choice';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.name=leafName;checkbox.value=key;
      const content=document.createElement('span');
      const title=document.createElement('span');title.textContent=t(labels[key]||key.replaceAll('_',' '));content.append(title);
      const value=document.createElement('span');value.className='subtle import-setting-value';value.textContent=displayValue(key,settings[key]);content.append(value);
      if(key==='accent_color'&&/^#[0-9a-f]{6}$/i.test(String(settings[key]))){
        const swatch=document.createElement('span');swatch.className='import-setting-color';swatch.style.backgroundColor=settings[key];content.append(swatch);
      }
      label.append(checkbox,content);list.append(label);leaves.push(checkbox);allLeaves.push(checkbox);
      checkbox.addEventListener('change',syncParents);
    }
    subsection.append(list);details.append(subsection);groupControls.push({checkbox:subMaster,leaves});
    subMaster.addEventListener('change',()=>{leaves.forEach(input=>{input.checked=subMaster.checked});syncParents()});
  }
  master.addEventListener('change',()=>{allLeaves.forEach(input=>{input.checked=master.checked});syncParents()});
  syncParents();root.append(details);return details;
}
function appendImportConfigGroup(result, kind, root=importPreview){
  if(kind==='preferences')return appendSiteSettingsGroup(result,root);
  const group={
    online:{available:result.online_source_cards!==null,title:'ui.0844',help:'ui.0846',name:'apply_online_source_cards'},
    rss:{available:result.rss_cards!==null,title:'ui.0845',help:'ui.0847',name:'apply_rss_cards'},
  }[kind];
  if(!group?.available)return null;
  const details=document.createElement('details');details.className='export-category import-config-category';
  const summary=document.createElement('summary');
  const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.name=group.name;
  checkbox.checked=group.name!=='apply_display_preferences'&&result.mode!=='settings_only';
  checkbox.setAttribute('aria-label',t(group.title));
  const heading=document.createElement('span');heading.textContent=t(group.title);
  summary.append(checkbox,heading);details.append(summary);
  const help=document.createElement('p');help.className='subtle export-category-help';help.textContent=t(group.help);
  details.append(help);
  if(kind==='online'||kind==='rss'){
    const cards=kind==='online'?result.online_source_cards:result.rss_cards;
    const idsName=kind==='online'?'online_source_card_ids':'rss_card_ids';
    const list=document.createElement('div');list.className='export-category-items';const children=[];
    for(const card of cards||[]){const label=document.createElement('label');label.className='check';const input=document.createElement('input');input.type='checkbox';input.name=idsName;input.value=card.id;input.checked=checkbox.checked;const text=document.createElement('span');text.textContent=`${card.title} · ${(card.entries||card.feeds||card.links||[]).length} entries`;label.append(input,text);list.append(label);children.push(input)}
    if(!(cards||[]).length){const empty=document.createElement('p');empty.className='subtle';empty.textContent=t('ui.0558');list.append(empty)}
    details.append(list);
    const syncMaster=()=>{const count=children.filter(input=>input.checked).length;checkbox.checked=children.length>0&&count===children.length;checkbox.indeterminate=count>0&&count<children.length};
    checkbox.addEventListener('change',()=>{children.forEach(input=>{input.checked=checkbox.checked});checkbox.indeterminate=false});children.forEach(input=>input.addEventListener('change',syncMaster));
  }
  root.append(details);return details;
}
function importConfigChoices(){
  const onlineIds=[...importPreview.querySelectorAll('input[name="online_source_card_ids"]:checked')].map(input=>input.value);
  const rssIds=[...importPreview.querySelectorAll('input[name="rss_card_ids"]:checked')].map(input=>input.value);
  const siteSettingKeys=[...importPreview.querySelectorAll('input[name="site_setting_keys"]:checked')].map(input=>input.value);
  return {apply_display_preferences:siteSettingKeys.length>0,site_setting_keys:siteSettingKeys,
    apply_online_source_cards:onlineIds.length>0,apply_rss_cards:rssIds.length>0,
    online_source_card_ids:onlineIds,rss_card_ids:rssIds};
}
function appendImportItemGroup({title,help,items,selection,keyFor,describe,onChange=()=>{},duplicateMessage='ui.0533',showWhenEmpty=false,beforeItems=null}){
  if(!items?.length&&!showWhenEmpty)return null;
  const details=document.createElement('details');details.className='export-category import-item-category';
  details.open=true;
  const summary=document.createElement('summary');
  const master=document.createElement('input');master.type='checkbox';master.setAttribute('aria-label',t(title));
  master.disabled=!items?.length;
  const heading=document.createElement('span');heading.textContent=`${t(title)} (${items.length})`;
  summary.append(master,heading);details.append(summary);
  if(help){const note=document.createElement('p');note.className='subtle export-category-help';note.textContent=t(help);details.append(note)}
  if(beforeItems)details.append(beforeItems());
  const list=document.createElement('div');list.className='export-category-items';
  const checkboxes=[];
  const updateMaster=()=>{
    const count=checkboxes.filter(input=>input.checked).length;
    master.checked=checkboxes.length>0&&count===checkboxes.length;
    master.indeterminate=count>0&&count<checkboxes.length;
  };
  for(const item of items){
    const label=document.createElement('label');label.className='check';
    const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=!item.duplicate;
    checkbox.dataset[keyFor]=item.key;
    const content=document.createElement('span');
    const text=document.createElement('span');text.textContent=describe(item);content.append(text);
    if(item.duplicate){const error=document.createElement('span');error.className='import-option-error';error.textContent=`${t(title)} — ${t(duplicateMessage,{reason:item.reason})}`;content.append(error)}
    label.append(checkbox,content);list.append(label);checkboxes.push(checkbox);
    checkbox.addEventListener('change',()=>{
      if(checkbox.checked)selection.add(item.key);else selection.delete(item.key);
      updateMaster();onChange();
    });
  }
  if(!items?.length&&showWhenEmpty){const empty=document.createElement('p');empty.className='subtle';empty.textContent=t('ui.0837');list.append(empty)}
  master.addEventListener('change',()=>{
    checkboxes.forEach((checkbox,index)=>{
      checkbox.checked=master.checked;
      if(master.checked)selection.add(items[index].key);else selection.delete(items[index].key);
    });
    master.indeterminate=false;onChange();
  });
  details.append(list);updateMaster();return details;
}
async function loadImportProfiles() {
  try {
    const result = await requestJson('/api/admin/import/profiles');
    importProfile.replaceChildren(new Option(t('ui.0162'), ''));
    for (const profile of result.profiles) {
      importProfile.append(new Option(profile.name, profile.filename));
    }
    importProfileLabel.hidden = result.profiles.length === 0;
    importProfile.disabled = result.profiles.length === 0;
  } catch (error) {
    console.error('Could not load installed profiles:', error);
    importProfileLabel.hidden = true;
  }
}
loadImportProfiles();
const importFiles = importForm.querySelector('input[name="files"]');
importForm.addEventListener('change', event => {
  if (event.target === importProfile && importProfile.value) {
    importFiles.value = '';
  } else if (event.target === importFiles && importFiles.files.length) {
    importProfile.value = '';
  }
  if ([importProfile, importFiles].includes(event.target)) {
    importPlan = null;
    importPreview.replaceChildren();
  }
});
importForm.addEventListener('submit', async event => {
  event.preventDefault(); importPlan = null; importPreview.replaceChildren();
  importStatus.textContent = t('ui.0242');
  try {
    const form = new FormData(importForm);
    const selectedFiles = form.getAll('files').filter(file => file && file.name && file.size);
    const selectedProfile = importProfile.value;
    if (selectedProfile) {
      if (selectedFiles.some(file => file.name.toLowerCase().endsWith('.json'))) {
        throw new Error(t('ui.0164'));
      }
      const installed = await requestJson(`/api/admin/import/profiles/${encodeURIComponent(selectedProfile)}`);
      form.append('files', new File([JSON.stringify(installed.profile)], installed.filename,
        {type: 'application/json'}));
    } else if (!selectedFiles.length) {
      throw new Error(t('ui.0165'));
    }
    const result = await requestJson('/api/admin/import/preview', {method: 'POST', body: form});
    importPlan = result;
    if (result.mode === 'settings_only') {
      const heading = document.createElement('h3');
      heading.textContent = t('ui.0555', {name: result.name});
      importPreview.append(heading);
      const note = document.createElement('p'); note.className = 'subtle';
      note.textContent = t('ui.0556');
      importPreview.append(note);
      const ignored = document.createElement('p'); ignored.className = 'subtle';
      ignored.textContent = t('ui.0557', result.ignored_content);
      importPreview.append(ignored);
      appendImportConfigGroup(result,'preferences');
      appendImportConfigGroup(result,'online');
      appendImportConfigGroup(result,'rss');
      const addList = (title, entries, describe) => {
        const section = document.createElement('section'); section.className = 'stack';
        const h = document.createElement('h4'); h.textContent = `${title} (${entries.length})`; section.append(h);
        if (!entries.length) { const empty = document.createElement('p'); empty.className = 'subtle'; empty.textContent = t('ui.0558'); section.append(empty); }
        for (const [index, entry] of entries.entries()) { const p = document.createElement('p'); p.textContent = describe(entry, index); section.append(p); }
        importPreview.append(section);
      };
      const fieldLabels = {title: t('ui.0117'), description: t('ui.0254'), display_order: t('ui.0579')};
      addList(t('ui.0580'), result.incoming_subjects, (item, index) => `${index + 1}. ${item.title} (${item.id})`);
      addList(t('ui.0559'), result.additions, item => `${item.title} (${item.id})`);
      addList(t('ui.0560'), result.edits, item => `${item.title} (${item.id}): ${Object.entries(item.changes).map(([key, change]) => `${fieldLabels[key] || key}: ${change.from} → ${change.to}`).join('; ')}`);
      const omitted = result.omitted || [];
      const removed = omitted.filter(item => item.action === 'remove');
      const retained = omitted.filter(item => item.action !== 'remove');
      addList(t('ui.0561'), retained, item => `${item.title} (${item.id}) · ${item.assigned_count === null ? t('ui.0562') : t('ui.0563', {count: item.assigned_count})}`);
      addList(t('ui.0564'), removed, item => `${item.title} (${item.id})`);
      const mappings = document.createElement('fieldset'); mappings.className = 'stack';
      const legend = document.createElement('legend'); legend.textContent = t('ui.0565'); mappings.append(legend);
      let needsMapping = false;
      for (const item of removed.filter(row => row.assigned_count > 0)) {
        needsMapping = true;
        const label = document.createElement('label'); label.textContent = `${item.title} (${item.id}) · ${t('ui.0563', {count: item.assigned_count})}`;
        const select = document.createElement('select'); select.dataset.subjectId = item.id;
        const empty = new Option(t('ui.0566'), ''); select.append(empty);
        for (const subject of result.incoming_subjects) {
          select.append(new Option(`${subject.title} (${subject.id})`, subject.id));
        }
        label.append(select); mappings.append(label);
        if (item.assigned_items?.length) {
          const list = document.createElement('ul');
          for (const assigned of item.assigned_items) { const li = document.createElement('li'); li.textContent = `${assigned.kind}: ${assigned.title}`; list.append(li); }
          label.append(list);
          if (item.assigned_count > item.assigned_items.length) {
            const more = document.createElement('small');
            more.textContent = t('ui.0581', {shown: item.assigned_items.length, total: item.assigned_count});
            label.append(more);
          }
        }
      }
      if (needsMapping) importPreview.append(mappings);
      if (result.omitted.some(item => item.assigned_count === null) && result.remove_omitted) {
        const blocked = document.createElement('p'); blocked.className = 'error';
        blocked.textContent = t('ui.0567'); importPreview.append(blocked);
      }
      const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'button primary'; apply.textContent = t('ui.0568'); importPreview.append(apply);
      const updateApply = () => {
        apply.disabled = result.remove_omitted && result.omitted.some(item => item.assigned_count === null) ||
          [...mappings.querySelectorAll('select')].some(select => !select.value);
      };
      mappings.addEventListener('change', updateApply); updateApply();
      apply.onclick = async () => {
        apply.disabled = true; importStatus.textContent = t('ui.0569');
        const subject_mapping = Object.fromEntries([...mappings.querySelectorAll('select')].map(select => [select.dataset.subjectId, select.value]));
        try {
          const done = await requestJson('/api/admin/import/apply', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: result.token, subject_mapping, ...importConfigChoices()})});
          importStatus.textContent = t('ui.0570',
            {added: done.subjects_added, updated: done.subjects_updated, removed: done.subjects_removed, remapped: done.content_records_remapped});
          importPlan = null; importPreview.replaceChildren();
          await Promise.all([refreshSubjects(), refreshExportOptions()]);
        } catch (error) { importStatus.textContent = error.message; apply.disabled = false; }
      };
      importStatus.textContent = t('ui.0571');
      return;
    }
    const heading = document.createElement('h3'); heading.textContent = t('ui.0243', {name: result.name}); importPreview.append(heading);
    const details = document.createElement('p');
    details.textContent = t('ui.0356', {count: result.catalogues.length, online: result.online_sources, local: result.local_sources, private_required: formatBytes(result.required_bytes), expanded: formatBytes(result.expanded_html_bytes), private_available: formatBytes(result.available_bytes), library_available: formatBytes(result.available_data_bytes)});
    importPreview.append(details);
    const zimSelection = new Set((result.zim_options || []).filter(item => !item.duplicate).map(item => item.key));
    const documentSelection = new Set((result.document_options || []).filter(item => !item.duplicate).map(item => item.key));
    const cachedOnlineOptions=(result.document_options||[]).filter(item=>item.location==='cached_online');
    const bundledOnlinePaths=new Set(cachedOnlineOptions.map(item=>item.path));
    const onlinePdfSelection = new Set((result.online_pdf_options || [])
      .filter(item => !item.duplicate || bundledOnlinePaths.has(item.path)).map(item => item.key));
    const mappingMenu=document.createElement('details');mappingMenu.className='export-category import-mapping-category';
    const mappingSummary=document.createElement('summary');
    const mappingHeading=document.createElement('span');mappingSummary.append(mappingHeading);
    const mappings=document.createElement('div');mappings.className='stack';
    for (const subject of result.subjects) {
    const label = document.createElement('label'); label.textContent = `${t(subject.title)} (${subject.id})`;
      const select = document.createElement('select'); select.dataset.subjectId = subject.id;
      const incoming = document.createElement('option'); incoming.value = subject.exists ? subject.id : '__create__';
      incoming.className=subject.exists?'mapping-existing-option':'mapping-create-option';
      incoming.textContent = subject.exists ? t('ui.0247', {title: t(subject.title)}) : t('ui.0248', {title: t(subject.title)}); select.append(incoming);
      for (const target of result.existing_subjects || []) {
        if (target.id === subject.id) continue;
        const option = document.createElement('option'); option.value = target.id;option.className='mapping-existing-option'; option.textContent = t('ui.0249', {title: t(target.title)}); select.append(option);
      }
      select.className='card-mapping-select';
      label.append(select); mappings.append(label);
    }
    const updateMappingSummary=()=>{
      const selects=[...mappings.querySelectorAll('select')];
      const create=selects.filter(select=>select.value==='__create__').length;
      selects.forEach(select=>{
        const isCreate=select.value==='__create__';
        select.classList.toggle('mapping-create',isCreate);
        select.classList.toggle('mapping-existing',!isCreate);
      });
      mappingHeading.textContent=t('ui.0246',{create,existing:selects.length-create});
    };
    mappings.addEventListener('change',updateMappingSummary);updateMappingSummary();
    mappingMenu.append(mappingSummary,mappings);importPreview.append(mappingMenu);
    appendImportConfigGroup(result,'preferences');
    const zimGroup=appendImportItemGroup({title:'ui.0840',help:'ui.0531',items:result.zim_options||[],showWhenEmpty:true,
      selection:zimSelection,keyFor:'zimKey',duplicateMessage:'ui.0537',
      describe:item=>`${item.title} · ${item.bytes?formatBytes(item.bytes):t('ui.0354')}${item.kind==='download'?` · ${t('ui.0573')}`:''}`,
      onChange:()=>updateImportCapacity()});
    if(zimGroup)importPreview.append(zimGroup);
    let importCachedCopies=cachedOnlineOptions.length>0;
    const syncCachedCopies=()=>{
      for(const item of cachedOnlineOptions){
        if(importCachedCopies&&onlinePdfSelection.has(`online-pdf:${item.path}`))documentSelection.add(item.key);
        else documentSelection.delete(item.key);
      }
    };
    const cachedCopyToggle=()=>{
      const label=document.createElement('label');label.className='check';
      const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=importCachedCopies;
      checkbox.disabled=!cachedOnlineOptions.length;
      checkbox.addEventListener('change',()=>{importCachedCopies=checkbox.checked;syncCachedCopies();updateImportCapacity()});
      const text=document.createElement('span');text.textContent=t('ui.0874');label.append(checkbox,text);
      const wrapper=document.createElement('div');wrapper.className='export-category-items';wrapper.append(label);
      return wrapper;
    };
    const onlineDocumentGroup=appendImportItemGroup({title:'ui.0842',help:'ui.0875',items:result.online_pdf_options,
      selection:onlinePdfSelection,keyFor:'onlinePdfKey',
      describe:item=>`${item.title} · ${item.bytes?formatBytes(item.bytes):t('ui.0354')}${item.update?` · ${t('ui.0879')}`:''}`,
      onChange:()=>{syncCachedCopies();updateImportCapacity()},beforeItems:cachedCopyToggle});
    const localDocumentGroup=appendImportItemGroup({title:'ui.0843',help:'ui.0532',
      items:(result.document_options||[]).filter(item=>item.location!=='cached_online'),
      selection:documentSelection,keyFor:'documentKey',describe:item=>`${item.title} · ${formatBytes(item.bytes)}`,
      onChange:()=>updateImportCapacity()});
    if(onlineDocumentGroup||localDocumentGroup){
      const documents=document.createElement('details');documents.className='export-category import-documents-category';
      documents.open=true;
      const summary=document.createElement('summary');summary.textContent=t('ui.0841');documents.append(summary);
      if(onlineDocumentGroup)documents.append(onlineDocumentGroup);
      if(localDocumentGroup)documents.append(localDocumentGroup);
      importPreview.append(documents);
    }
    syncCachedCopies();
    appendImportConfigGroup(result,'online');
    appendImportConfigGroup(result,'rss');
    const capacity = document.createElement('p'); capacity.className = 'subtle'; importPreview.append(capacity);
    for (const warning of result.warnings) { const p = document.createElement('p'); p.className = 'subtle'; p.textContent = t(warning); importPreview.append(p); }
    const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'button primary';
    apply.textContent = t('ui.0250');
    importPreview.append(apply);
    const applyBlocks = [];
    const updateImportCapacity = () => {
      const chosen = (result.zim_options || []).filter(item => zimSelection.has(item.key));
      const omittedDocumentBytes = (result.document_options || []).filter(item =>
        item.location === 'private' && !documentSelection.has(item.key)).reduce((sum, item) => sum + item.bytes, 0);
      const documentRequired = Math.max(0, result.required_bytes - omittedDocumentBytes);
      const required = chosen.filter(item => item.kind === 'catalogue').reduce((sum, item) => sum + item.bytes, 0) +
        chosen.filter(item => item.kind === 'download').reduce((sum, item) => sum + item.bytes, 0) + result.reserve_bytes;
      const selectedOnlinePdfs = (result.online_pdf_options || []).filter(item => onlinePdfSelection.has(item.key));
      const cachedOnlinePaths = new Set((result.document_options || []).filter(item =>
        item.location === 'cached_online' && documentSelection.has(item.key)).map(item => item.path));
      const onlinePdfBytes = selectedOnlinePdfs.filter(item => !cachedOnlinePaths.has(item.path))
        .reduce((sum, item) => sum + item.bytes, 0);
      const cachedDocumentBytes = (result.document_options || []).filter(item =>
        item.location !== 'private' && documentSelection.has(item.key)).reduce((sum, item) => sum + item.bytes, 0);
      const libraryRequired = required + onlinePdfBytes + cachedDocumentBytes;
      const selectedConflicts = (result.zim_options || []).filter(item => zimSelection.has(item.key) && item.conflict);
      const selectedOnlinePdfConflicts = selectedOnlinePdfs.filter(item => item.conflict);
      const selectedDocumentConflicts = (result.document_options || []).filter(item =>
        item.location !== 'private' && documentSelection.has(item.key) &&
        result.path_conflicts.includes(item.path));
      const coveredConflictPaths = new Set([
        ...(result.zim_options || []).map(item => item.path),
        ...(result.online_pdf_options || []).map(item => item.path),
        ...(result.document_options || []).map(item => item.path).filter(Boolean),
      ]);
      const uncoveredConflicts = result.path_conflicts.filter(path =>
        !coveredConflictPaths.has(path));
      capacity.textContent = t('ui.0542', {
        zim_count: chosen.length, pdf_count: selectedOnlinePdfs.length,
        required: formatBytes(libraryRequired),
        available: formatBytes(result.available_data_bytes)});
      capacity.textContent += ` ${t('ui.0534', {
        required: formatBytes(documentRequired), available: formatBytes(result.available_bytes)})}`;
      const blockedByConflict = uncoveredConflicts.length > 0 || selectedConflicts.length > 0 ||
        selectedOnlinePdfConflicts.length > 0 || selectedDocumentConflicts.length > 0;
      const blockedBySpace = result.available_data_bytes < libraryRequired;
      applyBlocks.length = 0;
      if (blockedByConflict) applyBlocks.push(t('ui.0349'));
      if (result.available_bytes < documentRequired) applyBlocks.push(t('ui.0350', {
        required: formatBytes(documentRequired), available: formatBytes(result.available_bytes)}));
      if (blockedBySpace) applyBlocks.push(t('ui.0543', {
        required: formatBytes(libraryRequired), available: formatBytes(result.available_data_bytes)}));
      apply.disabled = applyBlocks.length > 0;
      let blocked = importPreview.querySelector('.import-apply-blocked');
      if (applyBlocks.length) {
        if (!blocked) { blocked = document.createElement('p'); blocked.className = 'error import-apply-blocked'; importPreview.insertBefore(blocked, apply); }
        blocked.textContent = applyBlocks.join(' ');
      } else if (blocked) blocked.remove();
    };
    updateImportCapacity();
    apply.onclick = async () => {
      apply.disabled = true; importStatus.textContent = t('ui.0251');
      const subject_mapping = Object.fromEntries([...mappings.querySelectorAll('select')].map(select => [select.dataset.subjectId, select.value]));
      try {
        const done = await requestJson('/api/admin/import/apply', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({token: result.token, subject_mapping, ...importConfigChoices(),
            selected_zims: [...zimSelection], selected_documents: [...documentSelection],
            selected_online_pdfs: [...onlinePdfSelection]})});
        importStatus.textContent = t('ui.0544', {filename: done.saved_config, catalogues: done.imported_catalogues, included: done.imported_zims + done.zim_downloads_started, deferred: done.zims_deferred, zim_downloads: done.zim_downloads_started, queued_zims: done.zim_downloads_queued || 0, pdf_downloads: done.pdf_downloads_started || 0, skipped_pdfs: done.skipped_pdf_attachments, sources: done.pending_sources, online_cards: done.online_source_cards_imported || 0, rss_cards: done.rss_cards_imported || 0});
        if (done.zim_download_errors?.length) {
          const errors = document.createElement('p'); errors.className = 'error';
          errors.textContent = t('ui.0364', {errors: done.zim_download_errors.join('; ')});
          importStatus.append(errors);
        }
        if (done.pdf_download_errors?.length) {
          const errors = document.createElement('p'); errors.className = 'error';
          errors.textContent = t('ui.0545', {errors: done.pdf_download_errors.join('; ')});
          importStatus.append(errors);
        }
        importPlan = null; importPreview.replaceChildren();
        await Promise.all([refreshSubjects(), refreshZims(), refreshDocuments(), refreshExportOptions(), refreshPdfImports()]);
      } catch (error) { importStatus.textContent = error.message; apply.disabled = false; }
    };
    importStatus.textContent = t('ui.0252');
  } catch (error) { importStatus.textContent = error.message; }
});
let hotspotConfigLoaded=false;
let hotspotPasswordLoaded=false;
let zimPolling=false;
let zimLoaded=false;
async function requestJson(url, options={}) { let response;try{response=await fetch(url,{...options,headers:{...headers,...options.headers}})}catch{const error=new Error(window.cyberdeckNetworkError());error.networkError=true;throw error}if(!response.ok){const body=await response.json().catch(()=>({}));const error=new Error(window.cyberdeckApiError(body,response.status));error.status=response.status;throw error}return response.status===204?null:response.json(); }
async function requestJsonWithRetry(url, options={}, attempts=4){
  for(let attempt=0;;attempt++){
    try{return await requestJson(url,options)}catch(error){
      if(attempt+1>=attempts||(error.status&&error.status<500)||(!error.status&&!error.networkError))throw error;
      await new Promise(resolve=>setTimeout(resolve,400*2**attempt));
    }
  }
}
let pdfImportPoll;
let adminDocumentEntries=[];
let pdfImportJobs=[];
let adminCards=[];
async function refreshPdfImports(){
  try{
    const previouslyDownloaded=new Set(pdfImportJobs.flatMap(job=>job.files
      .filter(file=>file.status==='downloaded').map(file=>file.path)));
    const {imports}=await requestJson('/api/admin/import/pdf');pdfImportJobs=imports;
    renderAdminDocuments();
    const newlyDownloaded=imports.some(job=>job.files.some(file=>file.status==='downloaded'&&!previouslyDownloaded.has(file.path)));
    if(newlyDownloaded)await refreshDocuments();
    const active=imports.some(job=>job.files.some(file=>file.status==='queued'||file.status==='downloading')||
      ['queued','starting'].includes(job.deferred_zim_state));
    document.querySelector('#pdf-retry-all').hidden=!imports.some(job=>
      !job.files.some(file=>file.status==='queued'||file.status==='downloading')&&
      !['queued','starting'].includes(job.deferred_zim_state)&&
      (job.files.some(file=>file.status==='failed')||
       job.deferred_zim_state==='failed'||(job.deferred_zim_state==='finished'&&job.deferred_zim_errors?.length)));
    clearTimeout(pdfImportPoll);if(active)pdfImportPoll=setTimeout(refreshPdfImports,3000);
  }catch(error){console.error('Could not load Internet PDF status:',error)}
}
function row(title, detail, buttonText, callback) { const el=document.createElement('div');el.className='item-row';const label=document.createElement('div');const strong=document.createElement('strong');strong.textContent=title;const small=document.createElement('span');small.textContent=` ${detail||''}`;label.append(strong,small);const button=document.createElement('button');button.className='button';button.type='button';button.textContent=t(buttonText);button.onclick=callback;el.append(label,button);return el; }
function recordActions(){const actions=document.createElement('div');actions.className='record-actions';return actions}
const armedRemovals=new Map();
function armRemoval(button,remove,key,confirmLabel=t('ui.0698'),armedClass='danger',finalConfirmLabel=null){
  const confirmLabels=[confirmLabel,...(finalConfirmLabel?[finalConfirmLabel]:[])];
  const armDuration=5000;
  const label=button.textContent;
  button.dataset.removalKey=key;button.dataset.removalLabel=label;
  const disarm=()=>{
    armedRemovals.delete(key);
    document.querySelectorAll('[data-removal-key]').forEach(candidate=>{
      if(candidate.dataset.removalKey===key){delete candidate.dataset.armed;candidate.textContent=candidate.dataset.removalLabel;candidate.classList.remove(armedClass)}
    });
  };
  const scheduleDisarm=state=>{
    state.expires=Date.now()+armDuration;
    const expectedExpiry=state.expires;
    setTimeout(()=>{if(armedRemovals.get(key)===state&&state.expires===expectedExpiry&&Date.now()>=expectedExpiry)disarm()},armDuration);
  };
  const state=armedRemovals.get(key);
  if(state?.expires>Date.now()){
    button.dataset.armed='true';button.textContent=confirmLabels[state.step-1]||confirmLabel;button.classList.add(armedClass);
    setTimeout(()=>{if(armedRemovals.get(key)===state&&Date.now()>=state.expires)disarm()},state.expires-Date.now());
  }else if(state)armedRemovals.delete(key);
  button.onclick=async()=>{
    const current=armedRemovals.get(key);
    if(!(current?.expires>Date.now())){
      const nextState={step:1};armedRemovals.set(key,nextState);scheduleDisarm(nextState);
      button.dataset.armed='true';button.textContent=confirmLabel;button.classList.add(armedClass);
      return;
    }
    if(current.step<confirmLabels.length){
      current.step++;scheduleDisarm(current);button.textContent=confirmLabels[current.step-1];return;
    }
    disarm();button.disabled=true;
    try{await remove()}catch(error){alert(error.message)}finally{button.disabled=false}
  };
}
function zimProgressText(item){const status=item.status.startsWith('pid:')?t('ui.0397'):item.status.startsWith('failed')?t('ui.0400'):t(item.status);if(item.status==='ready')return t('ui.0371',{size:formatBytes(item.bytes)});if(item.status.startsWith('failed'))return `${status} · ${item.failure_reason||item.status.replace(/^failed:\s*/, '')}`;if(item.pause_requested)return t('ui.0372');if(!item.expected_bytes)return status;const received=item.received_bytes||0;const progress=t('ui.0373',{received:formatBytes(received),total:formatBytes(item.expected_bytes),percent:Math.floor(received*100/item.expected_bytes)});if(item.phase==='verifying')return t('ui.0374',{status});if(item.phase==='stalled')return t('ui.0375',{status,elapsed:formatUptime(item.progress_age_seconds)});if(item.phase==='connecting')return t('ui.0376',{status});return t('ui.0377',{status,progress})}
function createZimRow(item){
  const el=row(item.title,'','ui.0495',()=>{});
  el.classList.add('zim-row');el.dataset.zimId=item.id;el.dataset.subject=item.subject;el.zimItem=item;
  const remove=el.querySelector('button');remove.classList.add('remove-action');remove.dataset.zimAction='remove';remove.remove();
  const actions=recordActions();
  armRemoval(remove,async()=>{
    const current=el.zimItem;
    await requestJson(`/api/admin/zims/${current.id}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:current.filename})});
    await refreshZims();await refreshSubjects();
  },`zim:${item.id}`);
  const edit=document.createElement('button');edit.type='button';edit.className='button record-edit-action';edit.textContent='Edit';edit.onclick=()=>openZimEditor(el.zimItem,true);
  actions.append(edit,remove);el.append(actions);
  const detail=document.createElement('small');detail.className='zim-file-detail';el.firstElementChild.append(detail);
  return el;
}
function updateZimRow(el,item){el.zimItem=item;el.querySelector('.zim-file-detail').textContent=`${subjectName(item.subject)} · ${item.filename}`;el.querySelector('strong').textContent=item.title;const label=el.querySelector('span');const active=item.status.startsWith('pid:')||item.status==='downloading';label.textContent=` ${zimProgressText(item)}`;label.className='zim-status';if(active)label.classList.add('is-active');else if(item.status==='ready')label.classList.add('is-ready');else if(item.status.startsWith('failed'))label.classList.add('is-failed');else if(['interrupted','queued','paused'].includes(item.status))label.classList.add('is-pending');if(item.phase==='stalled'||item.pause_requested)label.classList.add('is-stalled');let progress=el.querySelector('.zim-progress');if(item.expected_bytes&&item.status!=='ready'){if(!progress){progress=document.createElement('progress');progress.className='zim-progress';el.firstElementChild.append(progress)}progress.max=item.expected_bytes;progress.value=Math.min(item.received_bytes||0,item.expected_bytes);progress.classList.toggle('is-pending',item.phase==='stalled'||['interrupted','paused'].includes(item.status))}else if(progress)progress.remove();let retry=el.querySelector('[data-zim-action="retry"]');
  if(item.status!=='ready'&&!retry){
    retry=document.createElement('button');retry.type='button';retry.className='button';retry.dataset.zimAction='retry';
    retry.onclick=async()=>{
      if(el.dataset.actionPending)return;
      const current=el.zimItem;
      const pausing=current.status.startsWith('pid:');
      el.dataset.actionPending='true';retry.disabled=true;
      retry.textContent=t(pausing?'Pausing…':'Resuming…');
      try{
        await requestJson(`/api/admin/zims/${current.id}/${pausing?'pause':'retry'}`,{method:'POST'});
        zimPolling=true;
        if(pausing)el.zimItem={...current,pause_requested:true};
        await refreshZims();
      }catch(error){alert(error.message)}
      finally{delete el.dataset.actionPending;updateZimRow(el,el.zimItem)}
    };
    el.querySelector('.record-actions').append(retry);
  }else if(item.status==='ready'&&retry){retry.remove();retry=null}
  if(retry&&!el.dataset.actionPending){
    retry.textContent=t(item.pause_requested?'Pausing…':active?'Pause':'Resume / retry');
    retry.disabled=Boolean(item.pause_requested)||item.status==='downloading';
    retry.classList.toggle('pause-download',active);
    retry.title=active?'Stop this job and keep downloaded bytes for Resume.':'Continue from the retained download.';
  }
}

async function refreshZims(){const list=document.querySelector('#zim-list');let items;try{items=await requestJsonWithRetry('/api/admin/zims')}catch(error){document.querySelector('#zim-status').textContent=`Could not load ZIMs: ${error.message}`;throw error}zimLoaded=true;document.querySelector('#zim-status').textContent='';zimPolling=items.some(item=>item.status.startsWith('pid:')||item.status==='downloading');const previous=new Map(Array.from(list.children,el=>[el.dataset.zimId,el]));const ordered=[];for(const item of items){const el=previous.get(item.id)||createZimRow(item);previous.delete(item.id);updateZimRow(el,item);ordered.push(el)}for(const el of previous.values())el.remove();const current=Array.from(list.children);if(current.length!==ordered.length||current.some((el,index)=>el!==ordered[index]))for(const el of ordered)list.append(el);document.querySelector('#zim-count').textContent=ordered.length;applyContentCardFilters()}
function createManagedDocumentRow(item,importStatus=null){
  const el=row(item.title,'','ui.0495',()=>{});
  el.dataset.subject=item.subject||'';
  const subject=subjectName(item.subject);
  const subjectLabel=document.createElement('span');subjectLabel.textContent=subject||'Unassigned';
  if(!subject)subjectLabel.className='archive-unassigned';
  el.querySelector('span').replaceChildren(' ',subjectLabel,document.createTextNode(t('ui.0380',{filename:item.filename,availability:item.available?formatBytes(item.bytes):t('ui.0368')})));
  const remove=el.querySelector('button');remove.classList.add('remove-action');remove.remove();
  const actions=recordActions();
  armRemoval(remove,async()=>{
    await requestJson(`/api/admin/archive/${encodeURIComponent(item.filename)}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:item.filename})});
    await refreshDocuments();await refreshSubjects();
  },`archive:${item.filename}`);
  const edit=document.createElement('button');edit.type='button';edit.className='button record-edit-action';edit.textContent='Edit';edit.onclick=()=>openZimEditor(item,true,null,'archive');
  const download=document.createElement(item.available?'a':'button');download.className='button compact-download';download.textContent=t('ui.0699',{size:formatBytes(item.bytes)});
  if(item.available){download.href=`/library/${encodeURIComponent(item.filename)}`;download.download=item.filename}
  else{download.disabled=true;download.title=t('ui.0302')}
  actions.append(edit,download,remove);
  if(importStatus){
    const state=document.createElement('span');state.className=`document-status is-${importStatus.status}`;
    state.textContent=t(importStatus.status==='downloaded'?'ui.0692':'ui.0691');
    el.firstElementChild.append(state);
  }
  el.append(actions);el.classList.add('document-row');return el;
}
function createUploadedDocumentRow(item){
  const totalBytes=item.attachments.every(attachment=>Number.isSafeInteger(attachment.bytes))?item.attachments.reduce((total,attachment)=>total+attachment.bytes,0):null;
  const attachmentCount=item.attachments.length;
  const detail=attachmentCount===1?t('ui.0381',{subject:subjectName(item.subject),count:attachmentCount,size:formatBytes(totalBytes)}):t('ui.0382',{subject:subjectName(item.subject),count:attachmentCount,size:formatBytes(totalBytes)});
  const el=row(item.title,detail,'ui.0495',()=>{});
  el.dataset.subject=item.subject||'';
  el.classList.add('document-row');
  if(item.cover_url){const image=document.createElement('img');image.className='cover-thumb';image.src=item.cover_url;image.alt='';el.prepend(image)}
  const remove=el.querySelector('button');remove.classList.add('remove-action');remove.remove();
  armRemoval(remove,async()=>{await requestJson(`/api/admin/items/${item.id}`,{method:'DELETE'});await refreshDocuments();await refreshSubjects()},`item:${item.id}`);
  const actions=recordActions();
  const edit=document.createElement('button');edit.className='button record-edit-action';edit.type='button';edit.textContent='Edit';edit.onclick=()=>openZimEditor(item,true,null,'document');actions.append(edit);
  for(const attachment of item.attachments){
    const size=formatBytes(attachment.bytes);
    if(attachment.kind==='html-zip'){
      const view=document.createElement('a');view.className='button compact-download';view.textContent=`${t('View')} · ${size}`;view.title=attachment.filename;
      view.href=`/documents/${item.id}/${attachment.id}/viewer`;actions.append(view);
    }
    const link=document.createElement('a');link.className='button compact-download';link.textContent=t('ui.0699',{size});link.title=attachment.filename;
    link.setAttribute('aria-label',t('ui.0503',{action:t('Download'),filename:attachment.filename,size}));
    link.href=`/documents/${item.id}/${attachment.id}`;link.download=attachment.filename;
    actions.append(link);
  }
  actions.append(remove);el.append(actions);
  return el;
}
function createPdfImportDocumentRow(job,file,fileIndex){
  const filename=file.path.startsWith('public/')?file.path.slice(7):file.path;
  const detail=[subjectName(file.subject),filename].filter(Boolean).join(' · ');
  const el=row(file.title,detail,'ui.0495',()=>{});el.dataset.subject=file.subject||'';el.querySelector(':scope > button').remove();el.classList.add('document-row','pdf-import-document');
  const stateKey={queued:'ui.0690',downloading:'ui.0691',failed:'ui.0693',canceled:'ui.0697'}[file.status]||'ui.0690';
  const state=document.createElement('span');state.className=`document-status is-${file.status}`;state.textContent=t(stateKey);el.firstElementChild.append(state);
  if(file.status==='downloading'){
    const received=file.received_bytes||0;const progress=document.createElement('progress');progress.className='document-progress';
    if(file.expected_bytes){progress.max=file.expected_bytes;progress.value=Math.min(received,file.expected_bytes)}
    el.firstElementChild.append(progress);
    const progressText=document.createElement('small');progressText.className='document-progress-text';
    progressText.textContent=file.expected_bytes?t('ui.0700',{received:formatBytes(received),total:formatBytes(file.expected_bytes),percent:Math.floor(received*100/file.expected_bytes)}):formatBytes(received);
    el.firstElementChild.append(progressText);
  }
  if(file.error){const error=document.createElement('small');error.className='error';error.textContent=file.error;el.firstElementChild.append(error)}
  if(fileIndex===0&&job.deferred_zim_errors?.length){const error=document.createElement('small');error.className='error';error.textContent=job.deferred_zim_errors.join('; ');el.firstElementChild.append(error)}
  const actions=recordActions();
  if(file.status==='failed'||file.status==='canceled'){
    const retry=document.createElement('button');retry.type='button';retry.className='button';retry.textContent=t('ui.0695');
    retry.onclick=async()=>{retry.disabled=true;try{await requestJson(`/api/admin/import/pdf/${encodeURIComponent(job.id)}/files/${fileIndex}/retry`,{method:'POST'});await refreshPdfImports()}catch(error){retry.disabled=false;alert(error.message)}};
    actions.append(retry);
  }
  const remove=document.createElement('button');remove.type='button';remove.className='button remove-action';remove.textContent=t('ui.0495');
  armRemoval(remove,async()=>{await requestJson(`/api/admin/import/pdf/${encodeURIComponent(job.id)}/files/${fileIndex}/remove`,{method:'POST'});await refreshPdfImports()},`pdf:${job.id}:${fileIndex}`);
  actions.append(remove);
  el.append(actions);return el;
}
function fillCardFilter(selectId,kind){
  const select=document.querySelector(`#${selectId}`);if(!select)return;
  const previous=select.value;select.replaceChildren(new Option('Show all',''));
  for(const card of adminCards.filter(item=>item.type===kind)){const option=new Option(card.display_title||card.title,card.id);option.dataset.userContent='true';select.add(option)}
  if([...select.options].some(option=>option.value===previous))select.value=previous;
}
function applyContentCardFilters(){
  const documentFilter=document.querySelector('#document-card-filter')?.value||'';
  document.querySelectorAll('#documents-list>.item-row').forEach(el=>{el.hidden=Boolean(documentFilter)&&el.dataset.subject!==documentFilter});
  const zimFilter=document.querySelector('#zim-card-filter')?.value||'';
  document.querySelectorAll('#zim-list>.item-row').forEach(el=>{el.hidden=Boolean(zimFilter)&&el.zimItem?.subject!==zimFilter});
}
function renderAdminDocuments(){
  const list=document.querySelector('#documents-list');if(!list)return;
  const downloaded=new Map();
  for(const job of pdfImportJobs)for(const file of job.files){
    if(file.status==='downloaded'&&file.path.startsWith('public/'))downloaded.set(file.path.slice(7),file);
  }
  const rows=adminDocumentEntries.map(item=>item.record_type==='managed'
    ?createManagedDocumentRow(item,downloaded.get(item.filename)||null)
    :createUploadedDocumentRow(item));
  for(const job of pdfImportJobs)for(const [fileIndex,file] of job.files.entries()){
    if(['removed','downloaded'].includes(file.status))continue;
    rows.push(createPdfImportDocumentRow(job,file,fileIndex));
  }
  rows.sort((a,b)=>a.querySelector('strong').textContent.localeCompare(b.querySelector('strong').textContent));
  list.replaceChildren(...rows);
  document.querySelector('#documents-count').textContent=rows.length;
  applyContentCardFilters();
}
let documentsRefresh=0;
async function refreshDocuments(){
  const generation=++documentsRefresh;
  const status=document.querySelector('#documents-status');status.textContent='Loading documents...';
  const [result]=await Promise.allSettled([requestJsonWithRetry('/api/admin/documents')]);
  if(generation!==documentsRefresh)return;
  if(result.status==='rejected'){console.error('Could not load admin documents:',result.reason);status.textContent=t('ui.0384');return}
  adminDocumentEntries=result.value.sort((a,b)=>a.title.localeCompare(b.title));renderAdminDocuments();
  const count=adminDocumentEntries.length+pdfImportJobs.reduce((total,job)=>total+job.files.filter(file=>!['removed','downloaded'].includes(file.status)).length,0);
  document.querySelector('#documents-count').textContent=count;
  status.textContent=count?(count===1?t('ui.0385',{count}):t('ui.0386',{count})):t('ui.0304');
}
document.querySelector('#documents-reload').onclick=refreshDocuments;
document.querySelector('#pdf-retry-all').onclick=async event=>{
  const button=event.currentTarget;button.disabled=true;
  try{
    const jobs=pdfImportJobs.filter(job=>!job.files.some(file=>file.status==='queued'||file.status==='downloading')&&
      !['queued','starting'].includes(job.deferred_zim_state)&&
      (job.files.some(file=>file.status==='failed')||job.deferred_zim_state==='failed'||
       (job.deferred_zim_state==='finished'&&job.deferred_zim_errors?.length)));
    for(const job of jobs)await requestJson(`/api/admin/import/pdf/${encodeURIComponent(job.id)}/retry`,{method:'POST'});
    await refreshPdfImports();
  }catch(error){alert(error.message)}finally{button.disabled=false}
};
// Keep old admin bookmarks useful after merging the two sections.
function redirectDocumentAnchor(){if(['#archive','#private'].includes(location.hash)){location.replace('#documents')}}
window.addEventListener('hashchange',redirectDocumentAnchor);redirectDocumentAnchor();
async function refreshSubjects(){await refreshCards()}
function formatBytes(bytes){if(bytes===null||bytes===undefined)return t('ui.0233');const units=['B','KB','MB','GB','TB'];let value=bytes,index=0;while(value>=1024&&index<units.length-1){value/=1024;index++}return`${value.toFixed(index?1:0)} ${units[index]}`}
function formatUptime(seconds){if(seconds===null||seconds===undefined)return t('ui.0233');const days=Math.floor(seconds/86400);seconds%=86400;const hours=Math.floor(seconds/3600);seconds%=3600;const minutes=Math.floor(seconds/60);return days?`${days}d ${hours}h ${minutes}m`:hours?`${hours}h ${minutes}m`:`${minutes}m`}
function addSystemFact(grid,label,value){const fact=document.createElement('div');fact.className='system-fact';const heading=document.createElement('span');heading.textContent=t(label);const detail=document.createElement('strong');detail.textContent=t(value);fact.append(heading,detail);grid.append(fact)}
function renderSystemNetwork(network){
  const target=document.querySelector('#system-interfaces');
  target.replaceChildren();
  if(!network?.available){target.textContent='Network interface information unavailable.';return}
  if(!network.interfaces.length){target.textContent='No network interfaces found.';return}
  for(const item of network.interfaces){
    const row=document.createElement('div');row.className='system-interface';
    const name=document.createElement('strong');name.textContent=item.device;
    const state=document.createElement('span');state.className=item.active?'interface-active':'subtle';
    state.textContent=item.active?t('ui.0234'):t(item.state);
    const detail=document.createElement('small');
    detail.textContent=[item.type,item.connection].filter(Boolean).join(' · ');
    row.append(name,state,detail);target.append(row);
  }
}
function renderSystemHotspot(state){
  const target=document.querySelector('#system-hotspot');target.replaceChildren();
  if(!state){addSystemFact(target,'Hotspot','Unavailable');return}
  addSystemFact(target,'Hotspot',state.active?'Running':state.configured?'Off':'Not configured');
  addSystemFact(target,'Automatic fallback',state.autostart?'Enabled':'Disabled');
  if(state.configured)addSystemFact(target,'Hotspot network',[state.ssid,state.selected_device].filter(Boolean).join(' · ')||'Unavailable');
}
let approvedLocationsSystemInfo=null;
let approvedLocationsStorageInfo=null;
let approvedLocationsSignature=null;
function renderApprovedStorageLocations(){
  const target=document.querySelector('#storage-approved-locations');
  if(!target)return;
  const info=approvedLocationsSystemInfo;
  if(!info){target.replaceChildren(document.createTextNode(t('ui.0585')));return}
  const filesystems=info.filesystems||[];
  const disks=approvedLocationsStorageInfo?.disks||[];
  const adoptedMounts=new Set(disks.filter(disk=>disk.adopted&&disk.mount).map(disk=>disk.mount));
  const signature=JSON.stringify({data_root:info.data_root,data_mount:info.data_filesystem_mount,
    filesystems:filesystems.map(item=>[item.mount,item.device,item.filesystem]),
    adopted:disks.filter(disk=>disk.adopted&&disk.mount).map(disk=>[disk.mount,disk.device,disk.model,disk.transport])});
  if(signature===approvedLocationsSignature)return;
  approvedLocationsSignature=signature;
  const rows=[];
  const migrationMountsShown=new Set();
  const add=(label,path,filesystem,extra='',targetMount=null)=>{
    const item=document.createElement('li');
    const name=document.createElement('strong');name.textContent=t(label);
    const location=document.createElement('span');location.textContent=t('ui.0652',{path,mount:filesystem?.mount||t('ui.0233'),device:filesystem?.device||t('ui.0233'),type:filesystem?.filesystem||t('ui.0233')});
    item.append(name,location);
    if(extra){const note=document.createElement('small');note.textContent=extra;item.append(note)}
    if(targetMount&&targetMount===info.data_filesystem_mount){
      const current=document.createElement('small');current.textContent=t('ui.0653',{path:info.data_root,mount:info.data_filesystem_mount||t('ui.0233')});item.append(current);
    }else if(targetMount&&filesystem?.filesystem==='ext4'&&!migrationMountsShown.has(targetMount)){
      migrationMountsShown.add(targetMount);
      item.append(storageButton('ui.0644',()=>moveLibraryStorage(targetMount)));
    }
    rows.push(item);
  };
  const root=filesystems.find(item=>item.mount==='/');
  const home=filesystems.filter(item=>{const mount=item.mount==='/'?'/':item.mount.replace(/\/$/,'');return mount==='/'||mount==='/home'||'/home'.startsWith(mount+'/')}).sort((a,b)=>b.mount.length-a.mount.length)[0];
  add('ui.0654','/',root,undefined,root?.mount);
  add('ui.0655','/home',home||root,home?.mount==='/home'?'':t('ui.0659'),home?.mount);
  for(const filesystem of filesystems){
    if(filesystem.mount==='/'||filesystem.mount==='/home'||adoptedMounts.has(filesystem.mount))continue;
    add('ui.0656',filesystem.mount,filesystem,'',adoptedMounts.has(filesystem.mount)?filesystem.mount:null);
  }
  for(const disk of disks){
    if(!disk.adopted||!disk.mount)continue;
    const filesystem=filesystems.find(item=>item.mount===disk.mount);
    add('ui.0657',`${disk.mount}/.cyberdeck-library`,filesystem||{mount:disk.mount,device:disk.device,filesystem:disk.partitions?.find(part=>part.mounts?.includes(disk.mount))?.filesystem||t('ui.0233')},`${disk.model} · ${disk.transport||t('ui.0233')}`,disk.mount);
  }
  target.replaceChildren(...(rows.length?rows:[document.createTextNode(t('ui.0658'))]));
  const current=document.querySelector('#storage-data-location');
  const partition=document.querySelector('#storage-config-partition');
  if(partition){const filesystem=info.filesystems?.find(item=>item.mount===info.data_filesystem_mount);partition.textContent=filesystem?.device||info.data_filesystem_mount||t('ui.0233')}
  if(current){
    const filesystem=info.filesystems?.find(item=>item.mount===info.data_filesystem_mount);
    current.textContent=t('ui.0652',{path:info.data_root,mount:info.data_filesystem_mount||t('ui.0233'),
      device:filesystem?.device||t('ui.0233'),type:filesystem?.filesystem||t('ui.0233')});
  }
}
async function refreshSystemOverview(){
  const target=document.querySelector('#system-overview');
  try{
    const info=await requestJson('/api/admin/system');
    const serverSummary=document.querySelector('#hostname-summary');
    if(serverSummary)serverSummary.textContent=info.hostname||t('ui.0233');
    approvedLocationsSystemInfo=info;
    renderApprovedStorageLocations();
    renderSystemNetwork(info.network);
    target.replaceChildren();
    const facts=document.createElement('div');
    facts.className='system-facts';
    addSystemFact(facts,'Hostname',info.hostname);
    addSystemFact(facts,'Operating system',info.operating_system);
    addSystemFact(facts,'Kernel',info.kernel);
    addSystemFact(facts,'Architecture',info.architecture);
    addSystemFact(facts,'CPU threads',info.cpu_threads??t('ui.0233'));
    addSystemFact(facts,'Memory',t('ui.0390',{
      total:formatBytes(info.memory.total_bytes),
      available:formatBytes(info.memory.available_bytes),
    }));
    addSystemFact(facts,'Uptime',formatUptime(info.uptime_seconds));
    target.append(facts);
    renderStorageDiskUsage();
  }catch(error){
    renderSystemNetwork(null);
    target.textContent=t('ui.0393',{error:error.message});
  }
}

const storageList=document.querySelector('#storage-management-list');
const storageActions=document.querySelector('#storage-management-actions');
const storageStatus=document.querySelector('#storage-management-status');
const storageFolderStatusSlot=document.querySelector('#storage-folder-status-slot');
let storageStatusDiskId=null;
const storageConfirmation=document.querySelector('#storage-action-confirmation');
function renderStorageDiskUsage(card,disk,info=approvedLocationsSystemInfo){
  if(!card){
    document.querySelectorAll('#storage-management-list .storage-disk-card').forEach(item=>
      renderStorageDiskUsage(item,item._storageDisk,info));
    return;
  }
  card.querySelectorAll('.storage-disk-space').forEach(item=>item.remove());
  if(!disk)return;
  if(!info?.filesystems)return;
  const mounts=new Set([...(disk.mounts||[]),...(disk.partitions||[]).flatMap(part=>part.mounts||[])]);
  for(const filesystem of info.filesystems.filter(item=>mounts.has(item.mount))){
    const usage=document.createElement('div');
    usage.className='storage-disk-space';
    const detail=document.createElement('p');
    detail.className='subtle';
    detail.textContent=`${filesystem.mount} · ${t('ui.0391',{free:formatBytes(filesystem.free_bytes),total:formatBytes(filesystem.total_bytes)})}`;
    const meter=document.createElement('progress');
    meter.max=100;
    meter.value=filesystem.used_percent;
    meter.setAttribute('aria-label',t('ui.0392',{mount:filesystem.mount,percent:filesystem.used_percent}));
    usage.append(detail,meter);
    if(filesystem.mount===info.data_filesystem_mount){
      const libraryPath=document.createElement('small');
      libraryPath.textContent=`${t('ui.0619')}: ${t('ui.0652',{path:info.data_root,mount:info.data_filesystem_mount||t('ui.0233'),device:filesystem.device||t('ui.0233'),type:filesystem.filesystem||t('ui.0233')})}`;
      usage.append(libraryPath);
    }
    card.append(usage);
  }
}
function storageButton(label,action){const button=document.createElement('button');button.className='button';button.type='button';button.textContent=t(label);button.addEventListener('click',action);return button}
async function postStorage(action,target,extra={}){const identity=typeof target==='string'?{target_mount:target}:target?.stable_id?{stable_id:target.stable_id}:target?.target_mount?{target_mount:target.target_mount}:{};return requestJson('/api/admin/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...identity,...extra})})}
function showStorageStatus(){storageStatus.scrollIntoView({block:'nearest',behavior:'smooth'})}
function selectStorageStatus(diskId=null){storageStatusDiskId=diskId;const card=diskId?[...storageList.querySelectorAll('.storage-disk-card')].find(item=>item._storageDisk?.stable_id===diskId):null;(card||storageFolderStatusSlot).append(storageStatus)}
function beginStorageOperation(message,diskId=null){selectStorageStatus(diskId);if(!diskId)document.querySelector('.storage-folder-configuration')?.setAttribute('open','');const progress=document.createElement('progress');progress.className='storage-operation-progress';progress.setAttribute('aria-label',t('ui.0621'));const label=document.createElement('span');label.textContent=message;storageStatus.replaceChildren(progress,label);storageStatus.setAttribute('aria-busy','true');storageStatus.classList.add('storage-operation-running');document.querySelectorAll('#storage-management button, .storage-folder-configuration button').forEach(button=>button.disabled=true);showStorageStatus()}
function finishStorageOperation(message,scroll=true){storageStatus.removeAttribute('aria-busy');storageStatus.classList.remove('storage-operation-running');storageStatus.textContent=message;document.querySelectorAll('#storage-management button, .storage-folder-configuration button').forEach(button=>button.disabled=false);if(scroll)showStorageStatus()}
function hideStorageConfirmation(){storageConfirmation.hidden=true;storageConfirmation.replaceChildren()}
function showStorageConfirmation({title,detail,confirmationValue,submitLabel,onConfirm}){
  const heading=document.createElement('h4');heading.textContent=title;
  const explanation=document.createElement('p');explanation.textContent=detail;
  const form=document.createElement('div');form.className='storage-confirmation-form';form.append(heading,explanation);
  const actions=document.createElement('div');actions.className='button-row';
  const confirmButton=document.createElement('button');confirmButton.className='button danger';confirmButton.type='button';confirmButton.textContent=submitLabel;
  let armed=false;let armTimer=null;
  const reset=()=>{if(armTimer)clearTimeout(armTimer);armTimer=null;armed=false;confirmButton.textContent=submitLabel;confirmButton.removeAttribute('aria-pressed')};
  confirmButton.addEventListener('click',async()=>{
    if(!armed){armed=true;confirmButton.textContent=t('ui.0645');confirmButton.setAttribute('aria-pressed','true');storageStatus.textContent=t('ui.0632');armTimer=setTimeout(()=>{reset();storageStatus.textContent=t('ui.0646')},5000);return}
    reset();hideStorageConfirmation();
    try{await onConfirm(confirmationValue||'')}catch(error){finishStorageOperation(error.message)}
  });
  const cancel=storageButton('ui.0633',()=>{const wasArmed=armed;reset();hideStorageConfirmation();if(wasArmed)storageStatus.textContent=t('ui.0646')});
  actions.append(confirmButton,cancel);form.append(actions);storageConfirmation.replaceChildren(form);storageConfirmation.hidden=false;heading.scrollIntoView({block:'nearest'});
}
function storageOperationPhase(status,kind){if(status.status==='queued')return t('ui.0634');if(kind==='initialization'){if(status.operation==='use-existing')return t('ui.0627');if(status.operation==='mount')return t('ui.0883');if(status.operation==='unmount')return t('ui.0884');const phases={checking:'ui.0635',wiping:'ui.0636',partitioning:'ui.0637',formatting:'ui.0638',mounting:'ui.0639'};return t(phases[status.phase]||'ui.0622')}const phases={copying:'ui.0663',quiescing:'ui.0664',verifying:'ui.0665',switching:'ui.0666','pending-health':'ui.0667'};return t(phases[status.status]||'ui.0608',{destination:status.destination||t('ui.0233')})}
function initializationCompletionMessage(status){if(status.operation==='unmount')return t('ui.0886');if(status.operation==='mount')return t('ui.0885',{mount:status.mount||t('ui.0233')});if(status.operation==='use-existing')return t('ui.0661',{mount:status.mount||t('ui.0233')});return t('ui.0660',{mount:status.mount||t('ui.0233')})}
async function waitForStorageOperation(kind,operationId){for(;;){const result=await refreshStorage();const status=result?.[kind];const matches=kind==='migration'?(status?.target_id===operationId||status?.stable_id===operationId):status?.stable_id===operationId;if(matches){if(status.status==='failed')throw new Error(status.error||t('ui.0640'));if(status.status==='completed'||status.status==='committed')return status;if(status.status==='queued'||status.status==='initializing'||['copying','quiescing','verifying','switching','pending-health'].includes(status.status)){const label=storageStatus.querySelector('span');if(label)label.textContent=storageOperationPhase(status,kind)}}await new Promise(resolve=>setTimeout(resolve,1500))}}
let activeStorageWatchKey=null;
async function watchStorageOperation(kind,operationId){
  const key=`${kind}:${operationId}`;
  if(activeStorageWatchKey===key)return;
  activeStorageWatchKey=key;
  try{
    const status=await waitForStorageOperation(kind,operationId);
    if(kind==='initialization'){
      storageTerminalNoticeKey=`initialization:${status.updated_at}:${status.stable_id}:${status.status}`;
      await Promise.all([refreshStorage(),refreshSystemOverview()]);
      finishStorageOperation(initializationCompletionMessage(status));
    }else{
      storageTerminalNoticeKey=`migration:${status.updated_at}:${status.target_id||status.stable_id}:${status.status}`;
      await Promise.all([refreshStorage(),refreshSystemOverview()]);
      finishStorageOperation(t('ui.0669',{destination:status.destination||t('ui.0233'),
        source:status.source||t('ui.0233')}));
    }
  }catch(error){
    finishStorageOperation(error.message);
  }finally{
    activeStorageWatchKey=null;
  }
}
async function startDiskInitialization(disk,confirmValue){beginStorageOperation(t('ui.0622'),disk.stable_id);await new Promise(requestAnimationFrame);try{await postStorage('initialize',disk,{confirm:confirmValue});await watchStorageOperation('initialization',disk.stable_id)}catch(error){finishStorageOperation(error.message)}}
function initializeStorage(disk,button){
  selectStorageStatus(disk.stable_id);
  const label=t('ui.0593');
  const reset=()=>{if(button.dataset.armTimer)clearTimeout(Number(button.dataset.armTimer));delete button.dataset.armTimer;delete button.dataset.armed;button.textContent=label;button.removeAttribute('aria-pressed')};
  if(button.dataset.armed==='true'){
    reset();
    void startDiskInitialization(disk,disk.stable_id);
    return;
  }
  button.dataset.armed='true';button.textContent=t('ui.0645');button.setAttribute('aria-pressed','true');
  storageStatus.textContent=`${t('ui.0615',{model:disk.model,capacity:formatBytes(disk.capacity_bytes),id:disk.stable_id})} ${t('ui.0632')}`;
  button.dataset.armTimer=String(setTimeout(()=>{if(button.dataset.armed==='true'){reset();storageStatus.textContent=t('ui.0646')}},5000));
}
async function adoptStorage(disk){beginStorageOperation(t('ui.0626'),disk.stable_id);try{await postStorage('adopt',disk);await refreshStorage();finishStorageOperation(t('ui.0602',{message:t('ui.0592')}))}catch(error){finishStorageOperation(error.message)}}
async function changeStorageMount(disk,action){beginStorageOperation(t(action==='mount'?'ui.0883':'ui.0884'),disk.stable_id);try{await postStorage(action,disk);await watchStorageOperation('initialization',disk.stable_id)}catch(error){finishStorageOperation(error.message)}}
async function useExistingStorage(disk){beginStorageOperation(t('ui.0627'),disk.stable_id);try{await postStorage('use-existing',disk);await watchStorageOperation('initialization',disk.stable_id)}catch(error){finishStorageOperation(error.message)}}
async function moveLibraryStorage(targetMount){beginStorageOperation(t('ui.0662'));await new Promise(resolve=>setTimeout(resolve,0));try{const preview=await postStorage('migration-preview',targetMount);if(!preview.eligible){finishStorageOperation(t('ui.0610'));return}const existingNotice=preview.destination_empty===true?'':t('ui.0670');const summary=`${t('ui.0601',{bytes:formatBytes(preview.copy_bytes),source:preview.data_root,destination:preview.destination,free:formatBytes(preview.free_bytes),model:preview.model,id:preview.uuid,filesystem:preview.filesystem,mount:preview.mount})} ${existingNotice} ${t('ui.0604')} ${t('ui.0609')}`;finishStorageOperation(t('ui.0668'),false);showStorageConfirmation({title:t('ui.0643'),detail:summary,confirmationValue:preview.target_id,submitLabel:t('ui.0595'),onConfirm:async confirmValue=>{beginStorageOperation(t('ui.0608'));await new Promise(resolve=>setTimeout(resolve,0));try{await postStorage('move-library',{target_mount:preview.target_mount},{target_id:preview.target_id,confirm:confirmValue});await watchStorageOperation('migration',preview.target_id)}catch(error){finishStorageOperation(error.message)}}})}catch(error){finishStorageOperation(error.message)}}
let storageInventorySignature=null;
let storageTerminalNoticeKey=null;
function createStorageCard(disk){
  const card=document.createElement('article');
  card.className='storage-disk-card';
  card._storageDisk=disk;
  const headerRow=document.createElement('div');
  headerRow.className='storage-disk-header';
  const heading=document.createElement('h4');
  const model=disk.model==='Unknown disk'&&disk.system_disk?t('ui.0887'):disk.model;
  heading.textContent=t('ui.0587',{model,capacity:formatBytes(disk.capacity_bytes)});
  const primaryActions=document.createElement('div');
  primaryActions.className='storage-disk-primary-actions';
  const addPrimaryAction=button=>primaryActions.append(button);
  headerRow.append(heading,primaryActions);
  const transport=document.createElement('p');
  transport.className='subtle';
  transport.textContent=t('ui.0616',{transport:disk.transport?disk.transport.toUpperCase():t('ui.0233')});
  const identity=document.createElement('p');
  identity.className='subtle';
  identity.textContent=t('ui.0588',{id:disk.stable_id||t('ui.0233')});
  const inventory=document.createElement('p');
  inventory.className='subtle';
  if(disk.partitions?.length){
    inventory.textContent=t('ui.0589',{summary:disk.partitions.map(part=>t('ui.0606',{filesystem:part.filesystem||'Unknown',size:formatBytes(part.size_bytes)})).join('; ')});
  }else{
    inventory.textContent=t('ui.0590');
  }
  card.append(headerRow,transport,identity,inventory);
  const actionBox=document.createElement('div');
  actionBox.className='storage-disk-actions';
  const addAction=button=>actionBox.append(button);
  if(disk.system_disk){
    const protectedNote=document.createElement('p');
    protectedNote.className='storage-protected-note storage-system-disk-note';
    protectedNote.textContent=t('ui.0597');
    card.append(protectedNote);
  }else if(disk.active_data_disk&&disk.adopted){
    const activeNote=document.createElement('p');
    activeNote.className='storage-protected-note storage-active-library-note';
    activeNote.textContent=t('ui.0679');
    card.append(activeNote);
    if(disk.mount){
      const mount=document.createElement('p');
      mount.className='subtle';
      mount.textContent=t('ui.0605',{mount:disk.mount});
      card.append(mount);
    }
  }else if(disk.active_data_disk){
    const protectedNote=document.createElement('p');
    protectedNote.className='storage-protected-note';
    protectedNote.textContent=t('ui.0612');
    card.append(protectedNote);
  }else if(disk.adopted){
    const adopted=document.createElement('p');
    adopted.className='storage-adopted-note';
    adopted.textContent=t('ui.0592');
    card.append(adopted);
    if(disk.mount){
      const mount=document.createElement('p');
      mount.className='subtle';
      mount.textContent=t('ui.0605',{mount:disk.mount});
      card.append(mount);
    }else{
      const unmounted=document.createElement('p');
      unmounted.className='subtle';
      unmounted.textContent=t('ui.0882');
      card.append(unmounted);
    }
    if(disk.adoption_stale){
      const warning=document.createElement('p');
      warning.className='storage-safety-note';
      warning.textContent=t('ui.0624');
      card.append(warning);
      if(disk.adoptable)addAction(storageButton('ui.0623',()=>adoptStorage(disk)));
    }else{
      if(disk.mount?.startsWith('/mnt/cyberdeck-disks/'))addPrimaryAction(storageButton('ui.0881',()=>changeStorageMount(disk,'unmount')));
      else if(!disk.mount&&disk.managed_mount?.startsWith('/mnt/cyberdeck-disks/'))addPrimaryAction(storageButton('ui.0880',()=>changeStorageMount(disk,'mount')));
      const actionRow=document.createElement('div');
      actionRow.className='button-row';
      if(!disk.mount){const initialize=storageButton('ui.0593',()=>initializeStorage(disk,initialize));actionRow.append(initialize)}
      if(!disk.mount&&!disk.managed_mount&&disk.partitions?.length===1&&disk.partitions[0].filesystem==='ext4')actionRow.append(storageButton('ui.0611',()=>useExistingStorage(disk)));
      if(actionRow.childElementCount)addAction(actionRow);
    }
  }else if(disk.adoptable){
    addPrimaryAction(storageButton('ui.0591',()=>adoptStorage(disk)));
  }
  if(actionBox.childElementCount)card.append(actionBox);
  renderStorageDiskUsage(card,disk);
  return card;
}
async function refreshStorage(){
  if(!storageList)return null;
  try{
    const result=await requestJson('/api/admin/storage');
    approvedLocationsStorageInfo=result;
    renderApprovedStorageLocations();
    const disks=result.disks||[];
    const migration=result.migration||{};
    const initialization=result.initialization||{};
    const signature=JSON.stringify({disks,migration:{status:migration.status,stable_id:migration.stable_id,
      target_id:migration.target_id,target_mount:migration.target_mount,error:migration.error},initialization});
    if(signature!==storageInventorySignature){
      storageInventorySignature=signature;
      const cards=disks.map(createStorageCard);
      const actionCards=[];
      if(!cards.length)cards.push(document.createTextNode(t('ui.0596')));
      if(migration.status&&migration.status!=='idle'){
        const state=document.createElement('p');
        state.className=migration.status==='failed'?'storage-safety-note':'subtle';
        state.textContent=migration.status==='failed'
          ?t('ui.0673',{error:migration.error||t('ui.0233')})
          :t('ui.0603',{status:migration.status});
        actionCards.push(state);
      }
      storageList.replaceChildren(...cards);
      storageActions.replaceChildren(...actionCards);
      selectStorageStatus(storageStatusDiskId);
    }
    if(storageStatus.hasAttribute('aria-busy')){
      document.querySelectorAll('#storage-management button, .storage-folder-configuration button').forEach(button=>button.disabled=true);
    }else if(initialization.status==='queued'||initialization.status==='initializing'){
      beginStorageOperation(storageOperationPhase(initialization,'initialization'),initialization.stable_id);
      if(activeStorageWatchKey!==`initialization:${initialization.stable_id}`)
        void watchStorageOperation('initialization',initialization.stable_id);
    }else if(migration.status&&['queued','copying','quiescing','verifying','switching','pending-health'].includes(migration.status)){
      const operationId=migration.target_id||migration.stable_id;
      beginStorageOperation(storageOperationPhase(migration,'migration'));
      if(activeStorageWatchKey!==`migration:${operationId}`)
        void watchStorageOperation('migration',operationId);
    }else{
      const migrationIsLatest=['committed','failed'].includes(migration.status)&&
        Number(migration.updated_at||0)>=Number(initialization.updated_at||0);
      if(migrationIsLatest){
        const noticeKey=`migration:${migration.updated_at}:${migration.target_id||migration.stable_id}:${migration.status}`;
        if(noticeKey!==storageTerminalNoticeKey){
          storageTerminalNoticeKey=noticeKey;
          selectStorageStatus(null);
          finishStorageOperation(migration.status==='failed'
            ?t('ui.0673',{error:migration.error||t('ui.0233')})
            :t('ui.0669',{destination:migration.destination||t('ui.0233'),source:migration.source||t('ui.0233')}));
        }
      }else if(initialization.status==='completed'||initialization.status==='failed'){
        const noticeKey=`initialization:${initialization.updated_at}:${initialization.stable_id}:${initialization.status}`;
        if(noticeKey!==storageTerminalNoticeKey){
          storageTerminalNoticeKey=noticeKey;
          selectStorageStatus(initialization.stable_id);
          if(initialization.status==='completed')finishStorageOperation(initializationCompletionMessage(initialization));
          else finishStorageOperation(initialization.error||t('ui.0640'));
        }
      }
    }
    return result;
  }catch(error){
    const message=t('ui.0586',{error:error.message});
    if(storageInventorySignature===null)storageList.textContent=message;
    else if(!storageStatus.hasAttribute('aria-busy'))storageStatus.textContent=message;
    return null;
  }
}
document.querySelector('#storage-reload')?.addEventListener('click',()=>{refreshStorage()});
const catalogForm=document.querySelector('#catalog-form');
const catalogQuery=document.querySelector('#catalog-query');
const catalogButton=catalogForm.querySelector('button[type="submit"]');
const catalogMessage=document.querySelector('#catalog-message');
const catalogResults=document.querySelector('#catalog-results');
const zimEditor=document.querySelector('#zim-editor');
const zimEditorForm=document.querySelector('#zim-editor-form');
function foldedFields(form,title,kind){
  let details=form.querySelector(`[data-extra-fields="${kind}"]`);
  if(details)return details;
  details=document.createElement('details');details.className='entry-translations';details.dataset.extraFields=kind;
  const summary=document.createElement('summary');summary.textContent=t(title);details.append(summary);
  const fields=document.createElement('div');fields.className='stack';details.append(fields);
  const actions=form.querySelector(':scope > .button-row,:scope > button:not([type="button"])');
  if(actions)actions.before(details);else form.append(details);
  return details;
}
function ensureOriginField(form){
  if(!form)return;
  const details=foldedFields(form,'Metadata','metadata');const fields=details.lastElementChild;
  if(!form.elements.origin_source){
    const label=document.createElement('label');label.append(document.createTextNode(t('Origin Source (optional)')));
    const input=document.createElement('input');input.name='origin_source';input.type='url';input.maxLength=2048;label.append(input);fields.append(label);
    const help=document.createElement('p');help.className='subtle';help.textContent=t('Publisher or reference page describing the content. This is separate from the file download URL.');fields.append(help);
  }
  const search=form.querySelector('[name="search_terms"]')?.closest('label');
  if(search){const help=search.nextElementSibling;fields.append(search);if(help?.tagName==='P')fields.append(help)}
}
function ensureVerificationFields(form){
  const details=foldedFields(form,'Download verification','verification');
  const label=document.createElement('label');label.textContent=t('Expected SHA-256 (optional)');
  const input=document.createElement('input');input.name='expected_sha256';input.pattern='[0-9a-fA-F]{64}';input.maxLength=64;input.autocomplete='off';label.append(input);
  const help=document.createElement('p');help.className='subtle';help.textContent=t('Leave blank to fetch the publisher checksum automatically. A supplied checksum must match the publisher checksum when available.');
  details.lastElementChild.append(label,help);
}
ensureOriginField(zimEditorForm);ensureOriginField(document.querySelector('#item-form'));ensureOriginField(document.querySelector('#zim-form'));
ensureVerificationFields(zimEditorForm);ensureVerificationFields(document.querySelector('#zim-form'));
const zimEditorSave=document.querySelector('#zim-editor-save');
const zimEditorCancel=document.querySelector('#zim-editor-cancel');
const zimEditorError=document.querySelector('#zim-editor-error');
let zimSelection=null;
let zimEditorBusy=false;
function subjectName(id){return [...zimEditorForm.elements.subject.options].find(option=>option.value===id)?.textContent||id}
function renderZimDetails(target,item){
  target.replaceChildren();
  if(item.description){const description=document.createElement('p');description.textContent=item.description;target.append(description)}
  const facts=[];
  if(item.language)facts.push(t('ui.0401',{value:item.language}));
  if(item.edition)facts.push(t('ui.0402',{value:item.edition}));
  if(item.flavour)facts.push(t('ui.0403',{value:item.flavour}));
  if(item.bytes)facts.push(t('ui.0404',{size:formatBytes(item.bytes)}));
  if(facts.length){const metadata=document.createElement('p');metadata.className='subtle';metadata.textContent=facts.join(' · ');target.append(metadata)}
  const filename=document.createElement('p');filename.className='zim-filename';filename.textContent=item.filename||'';target.append(filename);
}
function renderFileDetails(item,kind){
  const details=document.querySelector('#editor-file-details');const target=details.lastElementChild;target.replaceChildren();
  const files=kind==='document'?item.attachments:[item];
  for(const file of files){
    for(const [label,value]of [['Filename',file.filename],['File size',Number.isSafeInteger(file.bytes)?formatBytes(file.bytes):''],['Stored SHA-256',file.sha256],['Expected SHA-256',file.expected_sha256],['Download URL',kind==='zim'?file.source_url||file.url:'']]){
      if(!value)continue;const field=document.createElement('label');field.textContent=t(label);const input=document.createElement('input');input.readOnly=true;input.value=value;field.append(input);target.append(field);
    }
  }
  details.hidden=!target.childElementCount;
}
function renderDocumentSources(item,kind,editing){
  const target=document.querySelector('#document-download-sources');target.replaceChildren();
  if(!editing||kind==='zim'){target.hidden=true;return}
  const files=kind==='document'?item.attachments:[item];
  for(const file of files.filter(file=>file.download_url)){
    const group=document.createElement('div');group.className='stack';const label=document.createElement('label');label.textContent=t('Download URL');
    if(kind==='document'){const filename=document.createElement('span');filename.dataset.userContent='true';filename.textContent=file.filename;label.append(filename)}
    const input=document.createElement('input');input.type='url';input.required=true;input.maxLength=2048;input.value=file.download_url;input.dataset.documentUrl='true';input.name=`download_url_${file.id||'archive'}`;if(kind==='document')input.dataset.attachmentId=file.id;label.append(input);
    const update=document.createElement('button');update.dataset.updateCopy='true';update.type='button';update.className='button';update.textContent=t('Update downloaded copy');
    update.addEventListener('click',async()=>{
      if(zimEditorBusy||editorHasUnsavedChanges())return;zimEditorBusy=true;zimEditorError.hidden=true;
      const controls=[...zimEditorForm.elements].map(control=>[control,control.disabled]);controls.forEach(([control])=>{control.disabled=true});
      const endpoint=kind==='document'?`/api/admin/items/${encodeURIComponent(item.id)}/attachments/${encodeURIComponent(file.id)}/refresh`:`/api/admin/archive/${encodeURIComponent(item.filename)}/refresh`;
      const label=update.textContent;update.textContent=t('Updating downloaded copy…');
      try{await requestJson(endpoint,{method:'POST'});zimEditor.close();await refreshDocuments();await refreshExportOptions()}
      catch(error){zimEditorError.textContent=error.message;zimEditorError.hidden=false}
      finally{zimEditorBusy=false;controls.forEach(([control,disabled])=>{control.disabled=disabled});update.disabled=editorHasUnsavedChanges();update.textContent=label}
    });
    group.append(label,update);target.append(group);
  }
  target.hidden=!target.childElementCount;
  if(!target.hidden){const help=document.createElement('p');help.className='subtle';help.textContent=t('Save changes before updating the downloaded copy. The current copy stays available until the replacement is downloaded and validated.');target.append(help)}
}
function openZimEditor(item,editing,sourceButton=null,kind='zim'){
  zimSelection={item,editing,sourceButton,kind};
  zimEditorForm.reset();zimEditorError.hidden=true;
  zimEditorForm.querySelectorAll('details').forEach(details=>{details.open=false});
  const verification=zimEditorForm.querySelector('[data-extra-fields="verification"]');
  verification.hidden=editing;zimEditorForm.elements.expected_sha256.disabled=editing;
  document.querySelector('#document-description').hidden=kind!=='document';
  zimEditorForm.elements.description.value=kind==='document'?item.description:'';
  document.querySelector('#document-search-terms').hidden=!['document','archive'].includes(kind);
  document.querySelector('#document-search-help').hidden=!['document','archive'].includes(kind);
  zimEditorForm.elements.search_terms.value=['document','archive'].includes(kind)?(item.search_terms||''):'';
  zimEditorForm.elements.title.value=item.title;
  if(zimEditorForm.elements.origin_source)zimEditorForm.elements.origin_source.value=item.origin_source||'';
  const subjects=zimEditorForm.elements.subject;
  subjects.value=item.subject||([...subjects.options].some(option=>option.value==='general-reference')?'general-reference':subjects.options[0]?.value||'');
  document.querySelector('#zim-editor-heading').textContent=editing?'Edit library details':'Add library';
  zimEditorSave.textContent=editing?'Save changes':'Start download';
  document.querySelector('#zim-editor-note').textContent=editing?'Updates the title and subject shown in Cyberdeck. The archive, download progress, and titles inside Kiwix stay unchanged.':'Choose where this library appears in Cyberdeck. The download size and integrity will be verified before it becomes available.';
  document.querySelector('#zim-editor-details').hidden=editing;
  if(editing)document.querySelector('#zim-editor-details').replaceChildren();else renderZimDetails(document.querySelector('#zim-editor-details'),item);
  document.querySelector('#zim-editor-kind').textContent=kind==='zim'?t('ui.0188'):t('ui.0502');
  if(kind==='archive'){
    document.querySelector('#zim-editor-heading').textContent='Edit document';
    document.querySelector('#zim-editor-note').textContent=item.download_url?'Saves document details and download URLs. Use Update downloaded copy separately to fetch a replacement.':'Changes the display title and subject for everyone. The file stays unchanged. These edits take precedence over starter-content metadata.';
  }
  if(kind==='document'){
    document.querySelector('#zim-editor-heading').textContent='Edit document';
    document.querySelector('#zim-editor-note').textContent=item.attachments.some(file=>file.download_url)?'Saves document details and download URLs. Use Update downloaded copy separately to fetch a replacement.':'Changes the title, description, and subject for everyone. Attachments stay unchanged.';
  }
  renderDocumentSources(item,kind,editing);
  renderFileDetails(item,kind);
  zimSelection.snapshot=JSON.stringify([...new FormData(zimEditorForm)]);
  zimEditor.showModal();
}
function editorHasUnsavedChanges(){return zimSelection?.snapshot!==JSON.stringify([...new FormData(zimEditorForm)])}
for(const event of ['input','change'])zimEditorForm.addEventListener(event,()=>{
  zimEditorForm.querySelectorAll('[data-update-copy]').forEach(button=>{button.disabled=zimEditorBusy||editorHasUnsavedChanges()});
});
zimEditorCancel.addEventListener('click',()=>zimEditor.close());
zimEditor.addEventListener('cancel',event=>{if(zimEditorBusy)event.preventDefault()});
zimEditorForm.addEventListener('submit',async event=>{
  event.preventDefault();if(zimEditorBusy||!zimSelection)return;
  const {item,editing,sourceButton,kind}=zimSelection;
  const body={title:zimEditorForm.elements.title.value.trim(),subject:zimEditorForm.elements.subject.value};
  body.origin_source=zimEditorForm.elements.origin_source?.value.trim()||'';
  if(!editing){body.url=item.url;body.expected_sha256=zimEditorForm.elements.expected_sha256.value.trim()}
  if(kind==='archive'&&item.download_url)body.download_url=zimEditorForm.querySelector('[data-document-url]').value.trim();
  if(kind==='document')body.attachment_urls=Object.fromEntries([...zimEditorForm.querySelectorAll('[data-document-url]')].map(input=>[input.dataset.attachmentId,input.value.trim()]));
  if(kind==='document')body.description=zimEditorForm.elements.description.value;
  if(kind==='document'||kind==='archive')body.origin_source=zimEditorForm.elements.origin_source?.value.trim()||'';
  if(kind==='document'||kind==='archive')body.search_terms=zimEditorForm.elements.search_terms.value;
  zimEditorBusy=true;zimEditorSave.disabled=true;zimEditorCancel.disabled=true;zimEditorError.hidden=true;
  try{
    const endpoint=kind==='document'?`/api/admin/items/${encodeURIComponent(item.id)}`:kind==='archive'?`/api/admin/archive/${encodeURIComponent(item.filename)}`:editing?`/api/admin/zims/${encodeURIComponent(item.id)}`:'/api/admin/zims';
    await requestJson(endpoint,{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(sourceButton){sourceButton.disabled=true;sourceButton.textContent=t('ui.0438');catalogMessage.textContent=t('ui.0439',{title:body.title})}
    zimEditor.close();
    // Saving succeeded even if a subsequent status refresh fails; do not offer
    // to submit the same acquisition again in that case.
    try{if(kind!=='zim')await refreshDocuments();else await refreshZims();await refreshSubjects()}catch(error){alert(t('ui.0405',{error:error.message}))}
  }catch(error){zimEditorError.textContent=error.message;zimEditorError.hidden=false}
  finally{zimEditorBusy=false;zimEditorSave.disabled=false;zimEditorCancel.disabled=false}
});
catalogForm.addEventListener('submit',async event=>{
  event.preventDefault();
  const query=catalogQuery.value.trim();
  catalogResults.replaceChildren();
  if(query.length<2){catalogMessage.textContent=t('ui.0324');catalogQuery.focus();return}
  catalogButton.disabled=true;
  catalogMessage.textContent=t('ui.0325');
  try{
    const result=await requestJson(`/api/admin/catalog?q=${encodeURIComponent(query)}`);
    if(!result.items.length){catalogMessage.textContent=t('ui.0440',{query});return}
    catalogMessage.textContent=result.items.length===1?t('ui.0441',{count:result.items.length}):t('ui.0442',{count:result.items.length});
    for(const entry of result.items){
      const resultRow=document.createElement('article');resultRow.className='catalog-result';
      const heading=document.createElement('h4');heading.textContent=entry.title;
      const details=document.createElement('div');details.className='zim-details';renderZimDetails(details,entry);
      const choose=document.createElement('button');choose.type='button';choose.className='button';choose.textContent='Review and add';
      choose.onclick=()=>openZimEditor(entry,false,choose);
      resultRow.append(heading,details,choose);
      catalogResults.append(resultRow);
    }
  }catch(error){catalogMessage.textContent=t('ui.0443',{error:error.message})}
  finally{catalogButton.disabled=false}
});
document.querySelector('#zim-form').addEventListener('submit',async event=>{event.preventDefault();const formElement=event.currentTarget;const form=new FormData(formElement);try{await requestJson('/api/admin/zims',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(form))});formElement.reset();await refreshZims()}catch(error){alert(error.message)}});
document.querySelector('#item-form').addEventListener('submit',async event=>{event.preventDefault();const formElement=event.currentTarget;try{await requestJson('/api/admin/items',{method:'POST',body:new FormData(formElement)});formElement.reset();await refreshDocuments();await refreshSubjects()}catch(error){alert(error.message)}});
const accentInput=document.querySelector('#preferences-form [name="accent_color"]');
const accentStatus=document.querySelector('#accent-color-status');
document.querySelector('#preferences-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const formElement=event.currentTarget;
  const form=new FormData(formElement);
  try{
    if(window.cyberdeckSaveAccent)await window.cyberdeckSaveAccent();
    const result=await requestJson('/api/admin/settings',{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({pdf_open_mode:form.get('pdf_open_mode'),accent_color:form.get('accent_color'),home_columns:form.get('home_columns'),subtitle:form.get('subtitle'),display_timezone:form.get('display_timezone'),show_start_card:form.get('show_start_card')==='on'})});
    document.querySelector('#brand-subtitle').textContent=result.settings.subtitle;
    if(window.cyberdeckSetAccent)window.cyberdeckSetAccent(result.settings.accent_color);
    accentInput.value=result.settings.accent_color;
    accentStatus.textContent='Site preferences saved.';
  }catch(error){accentStatus.textContent=t('ui.0444',{error:error.message});alert(error.message)}
});
const adminPasswordForm=document.querySelector('#admin-password-form');
adminPasswordForm.addEventListener('submit',async event=>{
  event.preventDefault();
  const status=document.querySelector('#admin-password-status');
  const submit=adminPasswordForm.querySelector('[type="submit"]');
  const fields=new FormData(adminPasswordForm);
  status.textContent='';submit.disabled=true;
  try{
    const result=await requestJson('/api/admin/password',{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(fields))});
    headers['X-CSRF-Token']=result.csrf;
    document.querySelector('.admin-head').dataset.csrf=result.csrf;
    adminPasswordForm.reset();status.textContent=t(result.message);
  }catch(error){status.textContent=error.message}
  finally{submit.disabled=false}
});
const hotspotModuleToggle=document.querySelector('#hotspot-module-enabled');
if(hotspotModuleToggle){
  hotspotModuleToggle.addEventListener('change',async()=>{
    const enabled=hotspotModuleToggle.checked;const status=document.querySelector('#hotspot-module-status');
    hotspotModuleToggle.disabled=true;status.textContent=enabled?'Enabling Hotspot module…':'Disabling Hotspot module…';
    try{await requestJson('/api/admin/modules',{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({hotspot_enabled:enabled})});window.location.reload()}
    catch(error){hotspotModuleToggle.checked=!enabled;status.textContent=error.message;hotspotModuleToggle.disabled=false}
  });
}
const firewallToggle=document.querySelector('#firewall-toggle');
if(firewallToggle){
  const firewallStatus=document.querySelector('#firewall-module-status');
  const confirmation=document.querySelector('#firewall-confirmation');
  const confirmationText=document.querySelector('#firewall-confirmation-text');
  const confirmButton=document.querySelector('#firewall-confirm');
  const cancelButton=document.querySelector('#firewall-cancel');
  let firewallState=null;
  let pendingFirewallState=null;
  async function refreshFirewall(){
    try{
      firewallState=await requestJson('/api/admin/firewall',{cache:'no-store'});
      firewallToggle.checked=firewallState.enabled;
      firewallToggle.disabled=!firewallState.available;
      if(firewallState.conflicts?.length){
        firewallStatus.textContent=cyberdeckTranslate('ui.0834',{conflicts:firewallState.conflicts.join(', ')});
      }else if(firewallState.reason){
        firewallStatus.textContent=firewallState.reason;
      }else if(firewallState.active){
        firewallStatus.textContent=cyberdeckTranslate('ui.0829');
      }else{
        firewallStatus.textContent=cyberdeckTranslate('ui.0835',{
          checked:(firewallState.checked_managers||[]).join(', ')
        });
      }
    }catch(error){
      firewallToggle.disabled=true;
      firewallStatus.textContent=error.message;
    }
  }
  firewallToggle.addEventListener('change',()=>{
    if(!firewallState){firewallToggle.checked=false;return}
    pendingFirewallState=firewallToggle.checked;
    firewallToggle.checked=firewallState.enabled;
    confirmationText.textContent=cyberdeckTranslate(pendingFirewallState?'ui.0832':'ui.0833',{
      checked:(firewallState.checked_managers||[]).join(', ')
    });
    confirmation.hidden=false;
  });
  cancelButton.addEventListener('click',()=>{pendingFirewallState=null;confirmation.hidden=true});
  confirmButton.addEventListener('click',async()=>{
    if(pendingFirewallState===null)return;
    const requested=pendingFirewallState;
    confirmButton.disabled=true;cancelButton.disabled=true;firewallToggle.disabled=true;
    firewallStatus.textContent=cyberdeckTranslate(requested?'ui.0830':'ui.0831');
    try{
      await requestJson('/api/admin/firewall',{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({enabled:requested})});
      confirmation.hidden=true;pendingFirewallState=null;await refreshFirewall();
    }catch(error){
      firewallStatus.textContent=error.message;firewallToggle.checked=firewallState?.enabled||false;
      firewallToggle.disabled=!firewallState?.available;
    }finally{confirmButton.disabled=false;cancelButton.disabled=false}
  });
  refreshFirewall();
}
if(document.querySelector('#hotspot')){
document.querySelectorAll('[data-hotspot]').forEach(button=>button.addEventListener('click',async()=>{try{await requestJson('/api/admin/hotspot',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.hotspot})});if(button.dataset.hotspot==='stop')hotspotConfigLoaded=false;await Promise.all([hotspotStatus(),refreshSystemOverview()])}catch(error){alert(error.message)}}));
document.querySelector('#hotspot-form').addEventListener('submit',async event=>{event.preventDefault();const formElement=event.currentTarget;const form=new FormData(formElement);try{await requestJson('/api/admin/hotspot',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action:'configure',device:form.get('device'),ssid:form.get('ssid'),password:form.get('password'),upstream_ssids:String(form.get('upstream_ssids')||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean),redundancy_minutes:Number(form.get('redundancy_minutes')),autostart:form.has('autostart')})});formElement.elements.password.value='';hotspotConfigLoaded=false;hotspotPasswordLoaded=false;await hotspotStatus()}catch(error){alert(error.message)}});
const passwordInput=document.querySelector('#hotspot-password');
const passwordPeek=document.querySelector('#hotspot-password-peek');
passwordPeek.addEventListener('click',async()=>{
  if(passwordInput.type==='text'){
    passwordInput.type='password';passwordPeek.setAttribute('aria-label','Show saved password');passwordPeek.title='Show saved password';return;
  }
  try{
    if(!passwordInput.value){const saved=await requestJson('/api/admin/hotspot/password',{cache:'no-store'});passwordInput.value=saved.password;}
    passwordInput.type='text';passwordPeek.setAttribute('aria-label','Hide password');passwordPeek.title='Hide password';passwordInput.focus();
  }catch(error){alert(error.message)}
});
async function hotspotStatus(){
  const target=document.querySelector('#hotspot-state');
  const start=document.querySelector('[data-hotspot="start"]');
  const stop=document.querySelector('[data-hotspot="stop"]');
  const selector=document.querySelector('#hotspot-device');
  try{
    const state=await requestJson('/api/admin/hotspot');
    renderSystemHotspot(state);
    const adapters=state.wifi_devices||[];
    const signature=JSON.stringify(adapters.map(adapter=>[adapter.device,adapter.state,adapter.ap_supported]));
    if(selector.dataset.adapterSignature!==signature){
      const previous=selector.value;
      selector.replaceChildren();
      for(const adapter of adapters){const option=document.createElement('option');option.value=adapter.device;option.textContent=t('ui.0416',{device:adapter.device,state:t(adapter.state),support:t(adapter.ap_supported?'AP supported':'AP unavailable')});option.disabled=!adapter.ap_supported||['unavailable','unmanaged'].includes(adapter.state.toLowerCase());selector.append(option)}
      if(!selector.options.length){const option=document.createElement('option');option.value='';option.textContent='No Wi-Fi adapters found';selector.append(option)}
      selector.value=[...selector.options].some(option=>option.value===previous)?previous:([...selector.options].some(option=>option.value===state.selected_device)?state.selected_device:'');
      selector.dataset.adapterSignature=signature;
    }
    if(!hotspotConfigLoaded){const form=document.querySelector('#hotspot-form');form.elements.ssid.value=state.ssid||'';document.querySelector('#upstream-ssids').value=(state.upstream_ssids||[]).join('\n');form.elements.redundancy_minutes.value=state.redundancy_minutes||60;form.elements.autostart.checked=state.autostart;hotspotConfigLoaded=true}
    if(state.configured&&!hotspotPasswordLoaded){try{const saved=await requestJson('/api/admin/hotspot/password',{cache:'no-store'});passwordInput.value=saved.password;passwordInput.placeholder='Saved password · use the eye to reveal';hotspotPasswordLoaded=true}catch{passwordInput.placeholder='Could not load saved password · enter a new one or use the eye to retry'}}
    const upstreams=state.available_upstreams||[];
    const upstreamText=state.upstream_scan_unknown?t('ui.0333'):upstreams.length?t('ui.0419',{names:upstreams.join(', ')}):t('ui.0334');
    const message=t('ui.0420',{count:adapters.length,selected:state.selected_device||t('ui.0422'),upstreams:upstreamText,state:t(state.active?'on':'off'),notice:state.configured?'':t('ui.0421')});
    if(target.textContent!==message)target.textContent=message;
    target.classList.toggle('is-active',Boolean(state.active));target.classList.toggle('is-inactive',!state.active);
    const selectedAdapter=(state.wifi_devices||[]).find(adapter=>adapter.device===state.selected_device);
    const startDisabled=!state.configured||!selectedAdapter||!selectedAdapter.ap_supported||['unavailable','unmanaged'].includes(selectedAdapter.state.toLowerCase())||Boolean(state.active);
    if(start.disabled!==startDisabled)start.disabled=startDisabled;
    if(stop.disabled!==!state.active)stop.disabled=!state.active;
  }catch(error){renderSystemHotspot(null);if(target.textContent!==error.message)target.textContent=error.message;target.classList.remove('is-active');target.classList.add('is-inactive');start.disabled=true;stop.disabled=true}
}
hotspotStatus().catch(error=>alert(error.message));
setInterval(()=>hotspotStatus().catch(()=>{}),30000);
}
const powerPanel=document.querySelector('#management .management-power');
if(powerPanel){
  const powerStatus=document.createElement('p');powerStatus.className='subtle';powerStatus.setAttribute('role','status');powerStatus.setAttribute('aria-live','polite');
  powerStatus.textContent=t('ui.0546');
  powerPanel.querySelector('.button-row').insertAdjacentElement('afterend',powerStatus);
  let armedButton=null;let armTimer=null;
  document.querySelectorAll('[data-power]').forEach(button=>{
    const action=button.dataset.power;const label=button.textContent;
    button.addEventListener('click',async()=>{
      const verb=action==='poweroff'?t('ui.0406'):t('ui.0407');
      if(armedButton!==button){
        if(armedButton){armedButton.textContent=armedButton.dataset.originalLabel;delete armedButton.dataset.originalLabel}
        if(armTimer)clearTimeout(armTimer);
        armedButton=button;button.dataset.originalLabel=label;button.textContent=action==='poweroff'?t('ui.0549'):t('ui.0548');
        powerStatus.textContent=t('ui.0547',{action:verb});
        armTimer=setTimeout(()=>{if(armedButton===button){button.textContent=label;delete button.dataset.originalLabel;armedButton=null;powerStatus.textContent=t('ui.0553')}},5000);
        return;
      }
      if(armTimer)clearTimeout(armTimer);armTimer=null;armedButton=null;delete button.dataset.originalLabel;
      button.disabled=true;button.textContent=action==='poweroff'?t('ui.0551'):t('ui.0550');
      powerStatus.textContent=t('ui.0552',{action:verb});
      try{
        await requestJson('/api/admin/power',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action,confirm:action.toUpperCase()})});
        powerStatus.textContent=t('ui.0409',{action:verb});
      }catch(error){powerStatus.textContent=error.message}
      finally{button.disabled=false;button.textContent=label}
    });
  });
}
if(document.querySelector('#system-overview')){
  refreshSystemOverview().catch(error=>alert(error.message));
  setInterval(()=>refreshSystemOverview().catch(()=>{}),30000);
}
const cyberchefToggle=document.querySelector('#cyberchef-toggle');
if(cyberchefToggle){
  const cyberchefStatus=document.querySelector('#cyberchef-status');
  async function refreshCyberChef(){
    try{
      const state=await requestJson('/api/admin/cyberchef',{cache:'no-store'});
      cyberchefToggle.disabled=!state.installed;
      cyberchefToggle.checked=state.active;
      cyberchefStatus.textContent=state.active?t('ui.0720'):state.installed?t('ui.0721'):t('ui.0719');
    }catch(error){cyberchefToggle.disabled=true;cyberchefStatus.textContent=t('ui.0729',{error:error.message})}
  }
  cyberchefToggle.addEventListener('change',async()=>{
    const enabled=cyberchefToggle.checked;const action=enabled?'enable':'disable';
    cyberchefToggle.disabled=true;
    cyberchefStatus.textContent=t(enabled?'ui.0724':'ui.0725');
    try{await requestJson('/api/admin/cyberchef',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action})});await refreshCyberChef()}
    catch(error){cyberchefToggle.checked=!enabled;cyberchefStatus.textContent=t(enabled?'ui.0726':'ui.0727',{error:error.message});cyberchefToggle.disabled=false}
  });
  refreshCyberChef();
}
if(storageList){refreshStorage().catch(()=>{});setInterval(()=>refreshStorage().catch(()=>{}),60000)}
if(document.querySelector('#hostname-form')){
const hostnameForm=document.querySelector('#hostname-form');
const hostnameInput=hostnameForm.elements.hostname;
const hostnameButton=hostnameForm.querySelector('button');
const hostnameMessage=document.querySelector('#hostname-status');
const hostnameLinks=document.querySelector('#hostname-links');
let currentHostname='';
let currentHostnameUrl='';
let hostnamePending=false;
let hostnameArmed=false;
let hostnameArmTimer;
function resetHostnameArm(){clearTimeout(hostnameArmTimer);hostnameArmed=false;hostnameButton.textContent=t('ui.0176');hostnameButton.setAttribute('aria-pressed','false')}
function hostnamePreview(){document.querySelector('#hostname-preview').textContent=hostnameInput.value===currentHostname?t('ui.0410',{url:currentHostnameUrl}):hostnameInput.validity.valid?t('ui.0411',{url:`https://${hostnameInput.value}.local/`}):t('ui.0335')}
function hostnameLink(label,url){const link=document.createElement('a');link.textContent=label;link.href=url;hostnameLinks.append(link)}
async function refreshHostname(){
  try{
    const result=await requestJson('/api/admin/hostname',{cache:'no-store'});
    const change=result.change||{};
    const inProgress=['scheduled','applying'].includes(change.status);
    hostnamePending=inProgress||change.status==='recovery-required';
    currentHostname=result.hostname;currentHostnameUrl=result.url;
    const serverSummary=document.querySelector('#hostname-summary');
    if(serverSummary)serverSummary.textContent=result.hostname||t('ui.0233');
    if(!hostnameArmed)hostnameInput.value=inProgress?(change.hostname||result.hostname):result.hostname;
    hostnamePreview();
    hostnameInput.disabled=hostnamePending;hostnameButton.disabled=hostnamePending;
    hostnameLinks.replaceChildren();hostnameLink(t('ui.0412',{url:result.url}),result.url);
    hostnameMessage.textContent=change.error||(inProgress?'The name change is in progress. Reconnect to Wi-Fi if needed, then open the new address.':change.status==='recovery-required'?'Hostname recovery is required on the server before another change can be made.':'Choose a unique name to distinguish this library from other devices.');
    if(inProgress)hostnameLink('Open the new library address',`https://${change.hostname}.local/`);
    if(!hostnamePending)resetHostnameArm();
  }catch(error){hostnameMessage.textContent=error.message;if(!hostnamePending){hostnameInput.disabled=false;hostnameButton.disabled=false}}
}
hostnameInput.addEventListener('input',()=>{resetHostnameArm();hostnamePreview()});
hostnameForm.addEventListener('submit',async event=>{
  event.preventDefault();if(hostnamePending)return;
  const hostname=hostnameInput.value;
  if(hostname===currentHostname){hostnameMessage.textContent='Choose a different server name.';return}
  const url=`https://${hostname}.local/`;
  if(!hostnameArmed){hostnameArmed=true;hostnameButton.textContent=t('ui.0645');hostnameButton.setAttribute('aria-pressed','true');hostnameMessage.textContent=`${t('ui.0414',{url})} ${t('ui.0632')}`;hostnameArmTimer=setTimeout(()=>{resetHostnameArm();hostnameMessage.textContent=t('ui.0646')},5000);return}
  resetHostnameArm();
  hostnamePending=true;hostnameButton.disabled=true;hostnameInput.disabled=true;
  hostnameMessage.textContent='Checking the new name...';
  try{
    const result=await requestJson('/api/admin/hostname',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hostname,confirm:hostname})});
    hostnameMessage.textContent=t('ui.0370');
    hostnameLinks.replaceChildren();hostnameLink(t('ui.0413',{url:result.url}),result.url);hostnameLink('Previous address (if the change fails)',result.previous_url);
  }catch(error){
    hostnamePending=false;hostnameButton.disabled=false;hostnameInput.disabled=false;
    hostnameMessage.textContent=t('ui.0415',{error:error.message});
  }
});
refreshHostname().catch(error=>alert(error.message));
setInterval(()=>refreshHostname().catch(()=>{}),5000);
}
const cardForm=document.querySelector('#card-form');
const cardStatus=document.querySelector('#card-status');
const cardType=cardForm?.elements.type;
const cardLanguage=cardForm?.dataset.language||'en';
function cardPayloadFromForm(){
  const type=cardType.value;const title=cardForm.elements.title.value.trim();
  let id=cardForm.elements.id.value||cardForm.elements.card_id.value.trim()||slugify(title);if(!id)throw new Error('Add a valid card ID.');if(!cardForm.elements.id.value){const base=id;let suffix=2;while(adminCards.some(card=>card.id===id))id=`${base.slice(0,60)}-${suffix++}`}
  const description=cardForm.elements.description.value.trim();const editing=Boolean(cardForm.elements.id.value);const previous=adminCards.find(card=>card.id===id);const changed_fields=editing?['title','description'].filter(field=>cardForm.elements[field].value.trim()!==(field==='title'?previous?.display_title:previous?.display_description)):['title','description'];
  const payload={id,type,title,description,language:cardLanguage,changed_fields,offline_display:type==='subject'?'hide':cardForm.elements.offline_display.value,show_when_empty:cardForm.elements.show_when_empty.checked};
  const translationLanguage=cardForm.elements.translation_language.value;if(translationLanguage)payload.translation_language=translationLanguage,payload.translation={title:cardForm.elements.translation_title.value.trim(),description:cardForm.elements.translation_description.value.trim()};
  return payload;
}
function slugify(value){return value.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,64)}
function resetCardForm(){cardForm.reset();cardForm.elements.id.value='';cardForm.elements.card_id.disabled=false;cardForm.querySelector('#card-cancel').hidden=true;cardForm.querySelector('#card-type-lock-note').hidden=true;cardType.disabled=false;cardStatus.textContent='';cardForm.elements.translation_language.querySelectorAll('option').forEach(option=>option.disabled=false);updateCardFormVisibility()}
function updateCardFormVisibility(){const subject=cardType.value==='subject';const titleLimit=subject?80:100;const descriptionLimit=subject?300:500;cardForm.elements.title.maxLength=titleLimit;cardForm.elements.description.maxLength=descriptionLimit;cardForm.elements.translation_title.maxLength=titleLimit;cardForm.elements.translation_description.maxLength=descriptionLimit;cardForm.querySelector('[data-kind="offline"]').hidden=subject}
function beginCardEdit(card){
  cardForm.elements.id.value=card.id;cardForm.elements.card_id.value=card.id;cardForm.elements.card_id.disabled=true;cardType.value=card.type;cardType.disabled=Boolean(card.child_count);
  cardForm.elements.title.value=card.display_title||card.title;cardForm.elements.description.value=card.display_description||card.description||'';cardForm.dataset.initialTitle=cardForm.elements.title.value;cardForm.dataset.initialDescription=cardForm.elements.description.value;cardForm.elements.offline_display.value=card.offline_display||'hide';cardForm.elements.show_when_empty.checked=card.show_when_empty===true;
  const translationSelect=cardForm.elements.translation_language;translationSelect.value='';cardForm.elements.translation_title.value='';cardForm.elements.translation_description.value='';cardForm.querySelector('.card-translations').open=false;
  translationSelect.querySelectorAll('option').forEach(option=>{option.disabled=option.value===card.source_language});
  cardForm.querySelector('#card-cancel').hidden=false;cardForm.querySelector('#card-type-lock-note').hidden=!card.child_count;updateCardFormVisibility();cardForm.scrollIntoView({behavior:'smooth',block:'center'});
}
cardForm?.elements.translation_language.addEventListener('change',()=>{const card=adminCards.find(item=>item.id===cardForm.elements.id.value);const language=cardForm.elements.translation_language.value;const translation=card?.translations?.[language]||{};cardForm.elements.translation_title.value=translation.title||'';cardForm.elements.translation_description.value=translation.description||'';cardForm.elements.translation_title.placeholder=translation.title?'':'Uses original-language title';cardForm.elements.translation_description.placeholder=translation.description?'':'Uses original-language description'});
function renderCardRow(card){
  const hasContents=card.child_count>0;const row=document.createElement('div');row.className=`item-row document-row card-definition-row ${hasContents?'has-contents':'empty-card'}`;
  const details=document.createElement('div');const title=document.createElement('strong');title.dataset.userContent='true';title.textContent=card.display_title||card.title;
  const typeLabel=card.type==='subject'?t('ui.0255'):card.type==='rss'?'RSS':'Online Sources';
  const summary=document.createElement('span');summary.textContent=hasContents?`${typeLabel} · Card has contents (${card.child_count})`:typeLabel;
  details.append(title,summary);
  row.append(details);
  const actions=document.createElement('div');actions.className='record-actions';
  const edit=document.createElement('button');edit.type='button';edit.className='button record-edit-action';edit.textContent='Edit';edit.onclick=()=>beginCardEdit(card);actions.append(edit);
  const remove=document.createElement('button');remove.type='button';remove.className='button remove-action';remove.textContent='Delete';remove.title=hasContents?`Delete ${card.child_count} connected contents with this card`:'Delete this empty card';
  armRemoval(remove,async()=>{await requestJson(`/api/admin/cards/${encodeURIComponent(card.id)}`,{method:'DELETE'});await refreshCards();await refreshDocuments();await refreshZims()},`card:${card.id}`,t('ui.0698'),'danger',hasContents?t('ui.0868'):null);
  actions.append(remove);row.append(actions);return row;
}
function uniqueEntryId(card,title){const base=slugify(title)||'entry';let id=base;let suffix=2;while(card.entries.some(entry=>entry.id===id))id=`${base.slice(0,58)}-${suffix++}`;return id}
function appendEntryFormFields(form,card,entry=null){
  const title=document.createElement('input');title.name='title';title.required=true;title.maxLength=120;title.value=entry?.title||'';
  const url=document.createElement('input');url.name='url';url.type='url';url.required=true;url.maxLength=2048;url.value=entry?.url||'';
  form.append(Object.assign(document.createElement('label'),{textContent:'Title'}));form.lastChild.append(title);
  form.append(Object.assign(document.createElement('label'),{textContent:card.type==='rss'?'HTTPS Feed URL':'HTTPS URL'}));form.lastChild.append(url);
  ensureOriginField(form);form.elements.origin_source.value=entry?.origin_source||'';
  if(card.type==='online'){const description=document.createElement('textarea');description.name='description';description.maxLength=300;description.rows=2;description.value=entry?.description||'';form.append(Object.assign(document.createElement('label'),{textContent:'Description'}));form.lastChild.append(description)}
}
async function persistEntry(card,entryId,body,method){const suffix=entryId?`/${encodeURIComponent(entryId)}`:'';await requestJson(`/api/admin/cards/${encodeURIComponent(card.id)}/entries${suffix}`,{method,headers:{'Content-Type':'application/json'},body:method==='DELETE'?undefined:JSON.stringify(body)});await refreshCards()}
const sourceEntryDialog=document.querySelector('#source-entry-editor');
const sourceEntryForm=document.querySelector('#source-entry-editor-form');
for(const form of [sourceEntryForm,document.querySelector('#online-source-entry-form'),document.querySelector('#rss-entry-form')].filter(Boolean))ensureOriginField(form);
function beginEntryEdit(card,entry){
  const form=sourceEntryForm;form.reset();resetEntryTranslationForm(form);form.elements.entry_id.value=entry.id;form.elements.original_card_id.value=card.id;
  const cardSelect=form.elements.card_id;cardSelect.dataset.userContent='true';cardSelect.replaceChildren(...adminCards.filter(item=>item.type===card.type).map(item=>new Option(item.display_title||item.title,item.id)));cardSelect.value=card.id;
  form.querySelectorAll('[data-extra-fields]').forEach(details=>{details.open=false});
  form.elements.title.value=entry.display_title||entry.title;form.elements.url.value=entry.url;form.elements.origin_source.value=entry.origin_source||'';form.elements.description.value=entry.display_description||entry.description||'';form.elements.enabled.checked=entry.enabled!==false;form.dataset.initialTitle=form.elements.title.value;form.dataset.initialDescription=form.elements.description.value;
  const translationSelect=form.elements.translation_language;translationSelect.value='';form.elements.translation_title.value='';form.elements.translation_description.value='';translationSelect.querySelectorAll('option').forEach(option=>{option.disabled=option.value===entry.source_language});
  form.querySelectorAll('[data-entry-kind="online"]').forEach(element=>element.hidden=card.type!=='online');
  document.querySelector('#source-entry-editor-kind').textContent=card.type==='rss'?'RSS FEED':'ONLINE SOURCE';document.querySelector('#source-entry-editor-heading').textContent=card.type==='rss'?'Edit RSS feed':'Edit online source';document.querySelector('#source-entry-editor-note').textContent='Changes apply to this entry. Choose a Card to move it within the same type.';document.querySelector('#source-entry-editor-error').hidden=true;sourceEntryDialog.showModal();
}
document.querySelector('#source-entry-editor-cancel')?.addEventListener('click',()=>sourceEntryDialog.close());
function selectedEntryTranslation(form){const language=form.elements.translation_language.value;if(!language)return{};return{translation_language:language,translation:{title:form.elements.translation_title.value.trim(),description:form.elements.translation_description.value.trim()}}}
function resetEntryTranslationForm(form){form.elements.translation_language.value='';form.elements.translation_title.value='';form.elements.translation_description.value='';form.elements.translation_language.querySelectorAll('option').forEach(option=>option.disabled=false);form.dataset.initialTitle='';form.dataset.initialDescription=''}
for(const form of [sourceEntryForm,document.querySelector('#online-source-entry-form'),document.querySelector('#rss-entry-form')].filter(Boolean)){
  form.elements.translation_language.addEventListener('change',()=>{const cardId=form.elements.original_card_id?.value||form.elements.card?.value;const card=adminCards.find(item=>item.id===cardId);const entry=card?.entries.find(item=>item.id===form.elements.entry_id?.value);const locale=entry?.translations?.[form.elements.translation_language.value]||{};form.elements.translation_title.value=locale.title||'';form.elements.translation_description.value=locale.description||'';form.elements.translation_title.placeholder=locale.title?'':'Uses original-language title';form.elements.translation_description.placeholder=locale.description?'':'Uses original-language description'});
}
sourceEntryDialog?.addEventListener('click',event=>{if(event.target===sourceEntryDialog)sourceEntryDialog.close()});
sourceEntryForm?.addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;const card=adminCards.find(item=>item.id===form.elements.original_card_id.value);const entry=card?.entries.find(item=>item.id===form.elements.entry_id.value);if(!card||!entry)return;const title=form.elements.title.value.trim();const description=form.elements.description.value.trim();const fields=card.type==='online'?['title','description']:['title'];const body={card_id:form.elements.card_id.value,title,url:form.elements.url.value.trim(),origin_source:form.elements.origin_source.value.trim(),language:form.dataset.language,changed_fields:fields.filter(field=>form.elements[field].value.trim()!==(field==='title'?entry.display_title:entry.display_description)),enabled:form.elements.enabled.checked};if(card.type==='online')body.description=description;Object.assign(body,selectedEntryTranslation(form));const button=form.querySelector('[type="submit"]');const error=document.querySelector('#source-entry-editor-error');button.disabled=true;error.hidden=true;try{await persistEntry(card,form.elements.entry_id.value,body,'PUT');sourceEntryDialog.close()}catch(failure){error.textContent=failure.message;error.hidden=false}finally{button.disabled=false}});
function renderEntryRow(card,entry){
  const row=document.createElement('div');row.className='item-row source-entry-row';
  const main=document.createElement('div');main.className='source-entry-details';const headline=document.createElement('div');headline.className='source-entry-headline';const label=document.createElement('label');label.className='check source-entry-enabled';const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=entry.enabled!==false;checkbox.setAttribute('aria-label',`Enable ${entry.display_title||entry.title}`);checkbox.onchange=async()=>{checkbox.disabled=true;try{await persistEntry(card,entry.id,{enabled:checkbox.checked},'PUT')}catch(error){checkbox.checked=!checkbox.checked;alert(error.message)}finally{checkbox.disabled=false}};label.append(checkbox,document.createTextNode(' Enabled'));headline.append(label);const title=document.createElement('strong');title.dataset.userContent='true';title.textContent=entry.display_title||entry.title;headline.append(title);main.append(headline);const url=document.createElement('span');url.className='subtle';url.textContent=entry.url;main.append(url);if(entry.display_description||entry.description){const desc=document.createElement('span');desc.dataset.userContent='true';desc.textContent=entry.display_description||entry.description;main.append(desc)}row.append(main);
  const actions=document.createElement('div');actions.className='record-actions';const edit=document.createElement('button');edit.type='button';edit.className='button record-edit-action';edit.textContent='Edit';edit.onclick=()=>beginEntryEdit(card,entry);actions.append(edit);
  const remove=document.createElement('button');remove.type='button';remove.className='button remove-action';remove.textContent=t('ui.0495');armRemoval(remove,async()=>{await persistEntry(card,entry.id,{},'DELETE')},`entry:${card.id}:${entry.id}`,t('ui.0698'));actions.append(remove);row.append(actions);return row;
}
function renderCards(){
  const all=document.querySelector('#card-list');all.replaceChildren(...adminCards.map(card=>renderCardRow(card)));document.querySelector('#cards-count').textContent=adminCards.length;
  for(const [kind,listId,filterId,formId,countId]of [['online','online-source-card-list','online-source-card-filter','online-source-entry-form','online-source-count'],['rss','rss-card-list','rss-card-filter','rss-entry-form','rss-entry-count']]){
    const list=document.querySelector(`#${listId}`);const filter=document.querySelector(`#${filterId}`);const previous=filter.value;filter.replaceChildren(new Option('Show all',''));
    for(const card of adminCards.filter(item=>item.type===kind)){const option=new Option(card.display_title||card.title,card.id);option.dataset.userContent='true';filter.add(option)}if([...filter.options].some(option=>option.value===previous))filter.value=previous;
    list.classList.toggle('source-card-groups',!filter.value);
    const cards=adminCards.filter(item=>item.type===kind&&(!filter.value||item.id===filter.value));const entries=cards.flatMap(card=>(card.entries||[]).map(entry=>({card,entry})));document.querySelector(`#${countId}`).textContent=entries.length;
    const expandedCards=new Set([...list.querySelectorAll('.source-card-group[open]')].map(group=>group.dataset.cardId));
    if(filter.value){list.replaceChildren(...entries.map(({card,entry})=>renderEntryRow(card,entry)))}
    else{list.replaceChildren(...cards.filter(card=>(card.entries||[]).length).map(card=>{const group=document.createElement('details');group.className='source-card-group';group.dataset.cardId=card.id;group.open=expandedCards.has(card.id);const heading=document.createElement('summary');heading.dataset.userContent='true';const title=document.createElement('span');title.textContent=card.display_title||card.title;const count=document.createElement('small');count.className='source-card-group-count';count.textContent=`${card.entries.length} ${card.entries.length===1?'entry':'entries'}`;heading.append(title,count);const rows=document.createElement('div');rows.className='source-entry-group-list';rows.append(...card.entries.map(entry=>renderEntryRow(card,entry)));group.append(heading,rows);return group}))}
    const select=document.querySelector(`#${formId} [name="card"]`);if(select){select.dataset.userContent='true';const selected=select.value;select.replaceChildren(...adminCards.filter(item=>item.type===kind).map(card=>new Option(card.display_title||card.title,card.id)));if([...select.options].some(option=>option.value===selected))select.value=selected}
  }
  fillCardFilter('document-card-filter','subject');fillCardFilter('zim-card-filter','subject');refreshSubjectSelects();applyContentCardFilters();
}
for(const [kind,formId]of [['online','online-source-entry-form'],['rss','rss-entry-form']]){const form=document.querySelector(`#${formId}`);form?.addEventListener('submit',async event=>{event.preventDefault();const status=kind==='online'?document.querySelector('#online-source-entry-status'):null;if(status)status.textContent='';const card=adminCards.find(item=>item.id===form.elements.card.value);if(!card){const message=`Create a ${kind==='rss'?'RSS':'online source'} card first.`;if(status)status.textContent=message;else alert(message);return}const title=form.elements.title.value.trim();const body={id:uniqueEntryId(card,title),title,url:form.elements.url.value.trim(),origin_source:form.elements.origin_source.value.trim(),language:form.dataset.language,changed_fields:kind==='online'?['title','description']:['title']};if(kind==='online')body.description=form.elements.description.value.trim();Object.assign(body,selectedEntryTranslation(form));const button=form.querySelector('[type="submit"]');button.disabled=true;if(status)status.textContent='Adding online source…';try{await persistEntry(card,null,body,'POST');form.reset();resetEntryTranslationForm(form);if(status)status.textContent='Online source added.'}catch(error){if(status)status.textContent=error.message;else alert(error.message)}finally{button.disabled=false}})}
function refreshSubjectSelects(){
  const subjects=adminCards.filter(card=>card.type==='subject');
  document.querySelectorAll('#zim-form [name="subject"],#item-form [name="subject"],#zim-editor-form [name="subject"]').forEach(select=>{
    if(select.type==='checkbox')return;const previous=select.value;select.replaceChildren(...subjects.map(card=>{const option=new Option(card.display_title||card.title,card.id);option.dataset.userContent='true';return option}));if(subjects.some(card=>card.id===previous))select.value=previous;
  });
}
async function refreshCards(){const result=await requestJsonWithRetry('/api/admin/cards');adminCards=result.cards;renderCards();cardStatus.textContent=''}
cardForm?.addEventListener('submit',async event=>{event.preventDefault();const button=cardForm.querySelector('[type="submit"]');button.disabled=true;try{const card=cardPayloadFromForm();const editing=Boolean(cardForm.elements.id.value);const path=editing?`/api/admin/cards/${encodeURIComponent(card.id)}`:'/api/admin/cards';const saved=await requestJson(path,{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(card)});resetCardForm();await refreshCards();cardStatus.textContent='Card saved.'}catch(error){cardStatus.textContent=error.message}finally{button.disabled=false}});
cardForm?.elements.type.addEventListener('change',updateCardFormVisibility);
cardForm?.querySelector('#card-cancel').addEventListener('click',resetCardForm);
updateCardFormVisibility();
for(const id of ['document-card-filter','zim-card-filter'])document.querySelector(`#${id}`)?.addEventListener('change',applyContentCardFilters);
document.querySelector('#online-source-card-filter')?.addEventListener('change',renderCards);document.querySelector('#rss-card-filter')?.addEventListener('change',renderCards);
document.querySelector('#documents-list')&&new MutationObserver(applyContentCardFilters).observe(document.querySelector('#documents-list'),{childList:true});
document.querySelector('#zim-list')&&new MutationObserver(()=>{const rows=document.querySelectorAll('#zim-list>.item-row').length;document.querySelector('#zim-count').textContent=rows;applyContentCardFilters()}).observe(document.querySelector('#zim-list'),{childList:true});
refreshCards().catch(error=>{cardStatus.textContent=error.message});

const contentResetStatus=document.querySelector('#content-reset-status');
const contentResetButton=document.querySelector('#content-reset');
if(contentResetButton)armRemoval(contentResetButton,async()=>{contentResetStatus.textContent='Deleting all contents…';await requestJson('/api/admin/content/reset',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({confirm:'REMOVE ALL CONTENT'})});await refreshCards();await refreshDocuments();await refreshZims();contentResetStatus.textContent='All contents were deleted.'},'all-content-reset',t('ui.0698'));
Promise.all([refreshZims(),refreshDocuments(),refreshExportOptions(),refreshPdfImports()]).catch(error=>alert(error.message));setInterval(()=>{if(zimPolling||!zimLoaded)refreshZims().catch(error=>{document.querySelector('#zim-status').textContent=`Could not load ZIMs: ${error.message}`})},10000);
