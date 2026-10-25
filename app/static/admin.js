const headers = {'X-CSRF-Token': document.querySelector('.admin-head').dataset.csrf};
const t = window.cyberdeckTranslate;
const adminStart = document.querySelector('#admin-start');
if (adminStart) {
  const startAdminPage = () => {
    if (!window.location.hash || window.location.hash === '#admin-start') {
      const rootStyle = document.documentElement.style;
      const previousScrollBehavior = rootStyle.scrollBehavior;
      rootStyle.scrollBehavior = 'auto';
      window.scrollTo(0, 0);
      rootStyle.scrollBehavior = previousScrollBehavior;
    }
  };
  window.addEventListener('pageshow', () => requestAnimationFrame(startAdminPage));
  requestAnimationFrame(startAdminPage);
}
const nativeAlert = window.alert.bind(window);
const nativeConfirm = window.confirm.bind(window);
const nativePrompt = window.prompt.bind(window);
window.alert = message => nativeAlert(t(String(message)));
window.confirm = message => nativeConfirm(t(String(message)));
window.prompt = (message, value) => nativePrompt(t(String(message)), value);
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
    const entries = await requestJson('/api/admin/export/options');
    const legend = document.createElement('legend');
    legend.textContent = t('ui.0070');
    exportOptions.replaceChildren(legend);
    for (const entry of entries) {
      const label = document.createElement('label');
      label.className = 'check';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.name = 'selected'; checkbox.value = entry.id;
      checkbox.checked = entry.mode === 'online';
      const text = document.createElement('span');
      text.textContent = `${entry.title} · ${t(entry.subject || 'Unassigned')} · ${t(entry.mode === 'online' ? 'Online source (JSON)' : 'Local files (ZIP)')}`;
      label.append(checkbox, text); exportOptions.append(label);
    }
    exportStatus.textContent = t(entries.length ? 'Online sources selected by default. Choose any local catalogues to include.' : 'No content is available to export.');
    exportForm.querySelector('[type="submit"]').disabled = !entries.length;
  } catch (error) { exportStatus.textContent = error.message; }
}
document.querySelector('#export-reload').onclick = refreshExportOptions;
for (const [id, checked] of [['export-all', true], ['export-none', false]]) {
  document.getElementById(id).onclick = () => {
    exportOptions.querySelectorAll('input').forEach(input => { input.checked = checked; });
    clearExportDownloads();
  };
}
exportForm.addEventListener('change', clearExportDownloads);
exportForm.addEventListener('submit', async event => {
  event.preventDefault(); clearExportDownloads();
  const button = exportForm.querySelector('[type="submit"]');
  button.disabled = true; exportStatus.textContent = t('ui.0237');
  try {
    const selected = [...exportOptions.querySelectorAll('input:checked')].map(input => input.value);
    const result = await requestJson('/api/admin/export', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: exportForm.elements.name.value, selected, include_settings: exportForm.elements.include_settings.checked})});
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
    const bundleFields=[['csrf_token',headers['X-CSRF-Token']],['name',exportForm.elements.name.value],['include_settings',String(exportForm.elements.include_settings.checked)],...selected.map(value=>['selected',value])];
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
  if ([importProfile, importFiles, importForm.elements.mode, importForm.elements.remove_omitted_subjects].includes(event.target)) {
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
            body: JSON.stringify({token: result.token, subject_mapping, apply_settings: importForm.elements.apply_settings.checked})});
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
    const mappings = document.createElement('fieldset'); mappings.className = 'stack';
    const legend = document.createElement('legend'); legend.textContent = t('ui.0246'); mappings.append(legend);
    for (const subject of result.subjects) {
    const label = document.createElement('label'); label.textContent = `${t(subject.title)} (${subject.id})`;
      const select = document.createElement('select'); select.dataset.subjectId = subject.id;
      const incoming = document.createElement('option'); incoming.value = subject.exists ? subject.id : '__create__';
      incoming.textContent = subject.exists ? t('ui.0247', {title: t(subject.title)}) : t('ui.0248', {title: t(subject.title)}); select.append(incoming);
      for (const target of result.existing_subjects || []) {
        if (target.id === subject.id) continue;
        const option = document.createElement('option'); option.value = target.id; option.textContent = t('ui.0249', {title: t(target.title)}); select.append(option);
      }
      label.append(select); mappings.append(label);
    }
    importPreview.append(mappings);
    const zimSelection = new Set((result.zim_options || []).filter(item => !item.duplicate).map(item => item.key));
    const documentSelection = new Set((result.document_options || []).filter(item => !item.duplicate).map(item => item.key));
    const onlinePdfSelection = new Set((result.online_pdf_options || []).filter(item => !item.duplicate).map(item => item.key));
    if (result.document_options?.length) {
      const documentGroup = document.createElement('fieldset'); documentGroup.className = 'stack';
      const documentLegend = document.createElement('legend'); documentLegend.textContent = t('ui.0526'); documentGroup.append(documentLegend);
      const documentHint = document.createElement('p'); documentHint.className = 'subtle';
      documentHint.textContent = t('ui.0532'); documentGroup.append(documentHint);
      for (const item of result.document_options) {
        const label = document.createElement('label'); label.className = 'check';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = !item.duplicate;
        checkbox.dataset.documentKey = item.key;
        const content = document.createElement('span');
        const text = document.createElement('span'); text.textContent = `${item.title} · ${formatBytes(item.bytes)}`;
        content.append(text);
        if (item.duplicate) {
          const error = document.createElement('span'); error.className = 'import-option-error';
          error.textContent = t('ui.0533', {reason: item.reason}); content.append(error);
        }
        label.append(checkbox, content); documentGroup.append(label);
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) documentSelection.add(item.key); else documentSelection.delete(item.key);
          updateImportCapacity();
        });
      }
      importPreview.append(documentGroup);
    }
    if (result.online_pdf_options?.length) {
      const onlinePdfGroup = document.createElement('fieldset'); onlinePdfGroup.className = 'stack';
      const onlinePdfLegend = document.createElement('legend'); onlinePdfLegend.textContent = t('ui.0527'); onlinePdfGroup.append(onlinePdfLegend);
      const onlinePdfHint = document.createElement('p'); onlinePdfHint.className = 'subtle';
      onlinePdfHint.textContent = t('ui.0572'); onlinePdfGroup.append(onlinePdfHint);
      for (const item of result.online_pdf_options) {
        const label = document.createElement('label'); label.className = 'check';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = !item.duplicate;
        checkbox.dataset.onlinePdfKey = item.key;
        const content = document.createElement('span');
        const text = document.createElement('span'); text.textContent = `${item.title} · ${item.bytes ? formatBytes(item.bytes) : t('ui.0354')}`;
        content.append(text);
        if (item.duplicate) {
          const error = document.createElement('span'); error.className = 'import-option-error';
          error.textContent = t('ui.0533', {reason: item.reason}); content.append(error);
        }
        label.append(checkbox, content); onlinePdfGroup.append(label);
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) onlinePdfSelection.add(item.key); else onlinePdfSelection.delete(item.key);
          updateImportCapacity();
        });
      }
      importPreview.append(onlinePdfGroup);
    }
    if (result.zim_options?.length) {
      const zimGroup = document.createElement('fieldset'); zimGroup.className = 'stack';
      const zimLegend = document.createElement('legend'); zimLegend.textContent = t('ui.0352'); zimGroup.append(zimLegend);
      const zimHint = document.createElement('p'); zimHint.className = 'subtle';
      zimHint.textContent = t('ui.0531'); zimGroup.append(zimHint);
      for (const item of result.zim_options) {
        const label = document.createElement('label'); label.className = 'check';
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = !item.duplicate;
        checkbox.dataset.zimKey = item.key;
        const content = document.createElement('span');
        const text = document.createElement('span');
        text.textContent = `${item.title} · ${item.bytes ? formatBytes(item.bytes) : t('ui.0354')}${item.kind === 'download' ? ` · ${t('ui.0573')}` : ''}`;
        content.append(text);
        if (item.duplicate) {
          const error = document.createElement('span'); error.className = 'import-option-error';
          error.textContent = t('ui.0537', {reason: item.reason}); content.append(error);
        }
        label.append(checkbox, content); zimGroup.append(label);
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) zimSelection.add(item.key); else zimSelection.delete(item.key);
          updateImportCapacity();
        });
      }
      importPreview.append(zimGroup);
    }
    const capacity = document.createElement('p'); capacity.className = 'subtle'; importPreview.append(capacity);
    for (const warning of result.warnings) { const p = document.createElement('p'); p.className = 'subtle'; p.textContent = t(warning); importPreview.append(p); }
    const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'button primary';
    apply.textContent = t('ui.0250');
    importPreview.append(apply);
    const applyBlocks = [];
    const updateImportCapacity = () => {
      const chosen = (result.zim_options || []).filter(item => zimSelection.has(item.key));
      const omittedDocumentBytes = (result.document_options || []).filter(item => !documentSelection.has(item.key)).reduce((sum, item) => sum + item.bytes, 0);
      const documentRequired = Math.max(0, result.required_bytes - omittedDocumentBytes);
      const required = chosen.filter(item => item.kind === 'catalogue').reduce((sum, item) => sum + item.bytes, 0) +
        chosen.filter(item => item.kind === 'download').reduce((sum, item) => sum + item.bytes, 0) + result.reserve_bytes;
      const selectedOnlinePdfs = (result.online_pdf_options || []).filter(item => onlinePdfSelection.has(item.key));
      const onlinePdfBytes = selectedOnlinePdfs.reduce((sum, item) => sum + item.bytes, 0);
      const libraryRequired = required + onlinePdfBytes;
      const selectedConflicts = (result.zim_options || []).filter(item => zimSelection.has(item.key) && item.conflict);
      const selectedOnlinePdfConflicts = selectedOnlinePdfs.filter(item => item.conflict);
      const uncoveredConflicts = result.path_conflicts.filter(path =>
        !(result.zim_options || []).some(item => item.path === path));
      capacity.textContent = t('ui.0542', {
        pdf_count: selectedOnlinePdfs.length, required: formatBytes(libraryRequired),
        available: formatBytes(result.available_data_bytes)});
      capacity.textContent += ` ${t('ui.0534', {
        required: formatBytes(documentRequired), available: formatBytes(result.available_bytes)})}`;
      const blockedByConflict = uncoveredConflicts.length > 0 || selectedConflicts.length > 0 || selectedOnlinePdfConflicts.length > 0;
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
          body: JSON.stringify({token: result.token, subject_mapping, apply_settings: importForm.elements.apply_settings.checked,
            selected_zims: [...zimSelection], selected_documents: [...documentSelection],
            selected_online_pdfs: [...onlinePdfSelection]})});
        importStatus.textContent = t('ui.0544', {filename: done.saved_config, catalogues: done.imported_catalogues, included: done.imported_zims + done.zim_downloads_started, deferred: done.zims_deferred, zim_downloads: done.zim_downloads_started, pdf_downloads: done.pdf_downloads_started || 0, skipped_pdfs: done.skipped_pdf_attachments, sources: done.pending_sources});
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
async function requestJson(url, options={}) { let response;try{response=await fetch(url,{...options,headers:{...headers,...options.headers}})}catch{throw new Error(window.cyberdeckNetworkError())}if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(window.cyberdeckApiError(body,response.status))}return response.status===204?null:response.json(); }
let pdfImportPoll;
async function refreshPdfImports(){
  const panel=document.querySelector('#pdf-import-status');if(!panel)return;
  try{
    const {imports}=await requestJson('/api/admin/import/pdf');panel.replaceChildren();
    if(!imports.length){clearTimeout(pdfImportPoll);return;}
    const heading=document.createElement('h3');heading.textContent=t('ui.0689');panel.append(heading);
    let active=false;
    for(const job of imports){
      let jobActive=false;
      const group=document.createElement('section');group.className='pdf-import-job';
      const list=document.createElement('div');list.className='item-list';
      for(const file of job.files){
        const row=document.createElement('div');row.className='pdf-import-row';
        const label=document.createElement('div');const title=document.createElement('strong');title.textContent=file.title;
        const state=document.createElement('span');state.className=`pdf-import-state is-${file.status}`;
        const stateKey={queued:'ui.0690',downloading:'ui.0691',downloaded:'ui.0692',failed:'ui.0693'}[file.status]||'ui.0690';
        state.textContent=t(stateKey);label.append(title,state);
        if(file.error){const error=document.createElement('small');error.className='error';error.textContent=file.error;label.append(error)}
        row.append(label);list.append(row);
        if(file.status==='queued'||file.status==='downloading'){active=true;jobActive=true;}
      }
      group.append(list);
      if(!jobActive&&job.files.some(file=>file.status==='failed')){
        const retry=document.createElement('button');retry.type='button';retry.className='button';retry.textContent=t('ui.0694');
        retry.onclick=async()=>{retry.disabled=true;try{await requestJson(`/api/admin/import/pdf/${encodeURIComponent(job.id)}/retry`,{method:'POST'});await refreshPdfImports()}catch(error){retry.disabled=false;const message=document.createElement('p');message.className='error';message.textContent=error.message;group.append(message)}};
        group.append(retry);
      }
      panel.append(group);
    }
    clearTimeout(pdfImportPoll);if(active)pdfImportPoll=setTimeout(refreshPdfImports,3000);
  }catch(error){panel.replaceChildren();const message=document.createElement('p');message.className='error';message.textContent=error.message;panel.append(message)}
}
function row(title, detail, buttonText, callback) { const el=document.createElement('div');el.className='item-row';const label=document.createElement('div');const strong=document.createElement('strong');strong.textContent=title;const small=document.createElement('span');small.textContent=` ${detail||''}`;label.append(strong,small);const button=document.createElement('button');button.className='button';button.type='button';button.textContent=t(buttonText);button.onclick=callback;el.append(label,button);return el; }
function zimProgressText(item){const status=item.status.startsWith('pid:')?t('ui.0397'):item.status.startsWith('failed')?t('ui.0400'):t(item.status);if(item.status==='ready')return t('ui.0371',{size:formatBytes(item.bytes)});if(item.status.startsWith('failed'))return `${status} · ${item.failure_reason||item.status.replace(/^failed:\s*/, '')}`;if(item.pause_requested)return t('ui.0372');if(!item.expected_bytes)return status;const received=item.received_bytes||0;const progress=t('ui.0373',{received:formatBytes(received),total:formatBytes(item.expected_bytes),percent:Math.floor(received*100/item.expected_bytes)});if(item.phase==='verifying')return t('ui.0374',{status});if(item.phase==='stalled')return t('ui.0375',{status,elapsed:formatUptime(item.progress_age_seconds)});if(item.phase==='connecting')return t('ui.0376',{status});return t('ui.0377',{status,progress})}
function createZimRow(item){
  const el=row(item.title,'','Remove',async()=>{
    const current=el.zimItem;
    if(!confirm(t('ui.0378',{title:current.title,filename:current.filename})))return;
    try{await requestJson(`/api/admin/zims/${current.id}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:current.filename})});await refreshZims();await refreshSubjects()}catch(error){alert(error.message)}
  });
  el.classList.add('zim-row');el.dataset.zimId=item.id;el.zimItem=item;
  const remove=el.querySelector('button');remove.dataset.zimAction='remove';
  const edit=document.createElement('button');edit.type='button';edit.className='button';edit.textContent='Edit';edit.onclick=()=>openZimEditor(el.zimItem,true);
  el.insertBefore(edit,remove);
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
    el.append(retry);
  }else if(item.status==='ready'&&retry){retry.remove();retry=null}
  if(retry&&!el.dataset.actionPending){
    retry.textContent=t(item.pause_requested?'Pausing…':active?'Pause':'Resume / retry');
    retry.disabled=Boolean(item.pause_requested)||item.status==='downloading';
    retry.classList.toggle('pause-download',active);
    retry.title=active?'Stop this job and keep downloaded bytes for Resume.':'Continue from the retained download.';
  }
}

async function refreshZims(){const list=document.querySelector('#zim-list');const items=await requestJson('/api/admin/zims');zimPolling=items.some(item=>item.status.startsWith('pid:')||item.status==='downloading');const previous=new Map(Array.from(list.children,el=>[el.dataset.zimId,el]));const ordered=[];for(const item of items){const el=previous.get(item.id)||createZimRow(item);previous.delete(item.id);updateZimRow(el,item);ordered.push(el)}for(const el of previous.values())el.remove();const current=Array.from(list.children);if(current.length!==ordered.length||current.some((el,index)=>el!==ordered[index]))for(const el of ordered)list.append(el)}
function createManagedDocumentRow(item){
  const el=row(item.title,'','Remove',async()=>{
    const warning=item.managed?' '+t('ui.0301'):'';
    if(!confirm(t('ui.0379',{title:item.title,filename:item.filename})+warning))return;
    try{await requestJson(`/api/admin/archive/${encodeURIComponent(item.filename)}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:item.filename})});await refreshDocuments();await refreshSubjects()}catch(error){alert(error.message)}
  });
  const subject=subjectName(item.subject);
  const subjectLabel=document.createElement('span');subjectLabel.textContent=subject||'Unassigned';
  if(!subject)subjectLabel.className='archive-unassigned';
  el.querySelector('span').replaceChildren(' ',subjectLabel,document.createTextNode(t('ui.0380',{filename:item.filename,availability:item.available?formatBytes(item.bytes):t('ui.0368')})));
  const remove=el.querySelector('button');
  if(!item.available){remove.disabled=true;remove.title=t('ui.0302')}
  const edit=document.createElement('button');edit.type='button';edit.className='button';edit.textContent='Edit';edit.onclick=()=>openZimEditor(item,true,null,'archive');el.insertBefore(edit,remove);
  el.classList.add('document-row');return el;
}
function createUploadedDocumentRow(item){
  const totalBytes=item.attachments.every(attachment=>Number.isSafeInteger(attachment.bytes))?item.attachments.reduce((total,attachment)=>total+attachment.bytes,0):null;
  const attachmentCount=item.attachments.length;
  const detail=attachmentCount===1?t('ui.0381',{subject:subjectName(item.subject),count:attachmentCount,size:formatBytes(totalBytes)}):t('ui.0382',{subject:subjectName(item.subject),count:attachmentCount,size:formatBytes(totalBytes)});
  const el=row(item.title,detail,'Remove',async()=>{
    if(!confirm(t('ui.0383',{title:item.title})))return;
    try{await requestJson(`/api/admin/items/${item.id}`,{method:'DELETE'});await refreshDocuments();await refreshSubjects()}catch(error){alert(error.message)}
  });
  el.classList.add('document-row');
  if(item.cover_url){const image=document.createElement('img');image.className='cover-thumb';image.src=item.cover_url;image.alt='';el.prepend(image)}
  const edit=document.createElement('button');edit.className='button';edit.type='button';edit.textContent='Edit';edit.onclick=()=>openZimEditor(item,true,null,'document');el.insertBefore(edit,el.querySelector('button'));
  for(const attachment of item.attachments){
    const action=t(attachment.kind==='html-zip'?'View':'Download');
    const size=formatBytes(attachment.bytes);
    const link=document.createElement('a');link.className='button compact-download';link.textContent=`${action} · ${size}`;link.title=attachment.filename;link.setAttribute('aria-label',t('ui.0503',{action,filename:attachment.filename,size}));
    link.href=attachment.kind==='html-zip'?`/documents/${item.id}/${attachment.id}/viewer`:`/documents/${item.id}/${attachment.id}`;el.append(link);
  }
  return el;
}
let documentsRefresh=0;
async function refreshDocuments(){
  const generation=++documentsRefresh;
  const status=document.querySelector('#documents-status');status.textContent='Loading documents...';
  const [result]=await Promise.allSettled([requestJson('/api/admin/documents')]);
  if(generation!==documentsRefresh)return;
  if(result.status==='rejected'){console.error('Could not load admin documents:',result.reason);status.textContent=t('ui.0384');return}
  const entries=result.value.sort((a,b)=>a.title.localeCompare(b.title));
  document.querySelector('#documents-list').replaceChildren(...entries.map(item=>item.record_type==='managed'?createManagedDocumentRow(item):createUploadedDocumentRow(item)));
  status.textContent=entries.length?(entries.length===1?t('ui.0385',{count:entries.length}):t('ui.0386',{count:entries.length})):t('ui.0304');
}
document.querySelector('#documents-reload').onclick=refreshDocuments;
// Keep old admin bookmarks useful after merging the two sections.
function redirectDocumentAnchor(){if(['#archive','#private'].includes(location.hash)){location.replace('#documents')}}
window.addEventListener('hashchange',redirectDocumentAnchor);redirectDocumentAnchor();
async function refreshSubjects(){const list=document.querySelector('#subject-list');list.replaceChildren();for(const subject of await requestJson('/api/admin/subjects')){const detail=subject.assigned_count===null?t('ui.0387',{id:subject.id}):t('ui.0388',{id:subject.id,count:subject.assigned_count});const el=row(t(subject.title),detail,subject.can_delete?'Delete':'In use',async()=>{if(!confirm(t('ui.0389',{title:t(subject.title)})))return;try{await requestJson(`/api/admin/subjects/${encodeURIComponent(subject.id)}`,{method:'DELETE'});window.location.reload()}catch(error){alert(error.message)}});const button=el.querySelector('button');if(!subject.can_delete){button.disabled=true;button.title=t('ui.0306')}list.append(el)}}
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
    const dataFilesystem=info.filesystems?.find(item=>item.mount===info.data_filesystem_mount);
    addSystemFact(facts,'ui.0619',t('ui.0652',{
      path:info.data_root,
      mount:info.data_filesystem_mount||t('ui.0233'),
      device:dataFilesystem?.device||t('ui.0233'),
      type:dataFilesystem?.filesystem||t('ui.0233'),
    }));
    addSystemFact(facts,'Uptime',formatUptime(info.uptime_seconds));
    target.append(facts);
    const heading=document.createElement('h3');
    heading.className='system-storage-heading';
    heading.textContent=t('ui.0314');
    target.append(heading);
    if(!info.filesystems.length){
      const empty=document.createElement('p');
      empty.className='subtle';
      empty.textContent=t('ui.0316');
      target.append(empty);
      return;
    }
    const disks=document.createElement('div');
    disks.className='system-disks';
    for(const disk of info.filesystems){
      const row=document.createElement('div');
      row.className='system-disk';
      const top=document.createElement('div');
      top.className='system-disk-top';
      const mount=document.createElement('strong');
      mount.textContent=disk.mount===info.data_filesystem_mount
        ?t('ui.0360',{mount:disk.mount}):disk.mount;
      const summary=document.createElement('span');
      summary.textContent=t('ui.0391',{
        free:formatBytes(disk.free_bytes),
        total:formatBytes(disk.total_bytes),
        percent:disk.used_percent,
      });
      top.append(mount,summary);
      const source=document.createElement('small');
      source.textContent=`${disk.usb_storage?t('ui.0315')+' · ':''}${t(disk.device)} · ${t(disk.filesystem)}`;
      const meter=document.createElement('progress');
      meter.max=100;
      meter.value=disk.used_percent;
      meter.setAttribute('aria-label',t('ui.0392',{mount:disk.mount,percent:disk.used_percent}));
      row.append(top,source,meter);
      disks.append(row);
    }
    target.append(disks);
  }catch(error){
    renderSystemNetwork(null);
    target.textContent=t('ui.0393',{error:error.message});
  }
}

const storageList=document.querySelector('#storage-management-list');
const storageStatus=document.querySelector('#storage-management-status');
const storageConfirmation=document.querySelector('#storage-action-confirmation');
function storageButton(label,action){const button=document.createElement('button');button.className='button';button.type='button';button.textContent=t(label);button.addEventListener('click',action);return button}
async function postStorage(action,target,extra={}){const identity=typeof target==='string'?{target_mount:target}:target?.stable_id?{stable_id:target.stable_id}:target?.target_mount?{target_mount:target.target_mount}:{};return requestJson('/api/admin/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...identity,...extra})})}
function showStorageStatus(){storageStatus.scrollIntoView({block:'nearest',behavior:'smooth'})}
function beginStorageOperation(message){const progress=document.createElement('progress');progress.className='storage-operation-progress';progress.setAttribute('aria-label',t('ui.0621'));const label=document.createElement('span');label.textContent=message;storageStatus.replaceChildren(progress,label);storageStatus.setAttribute('aria-busy','true');storageStatus.classList.add('storage-operation-running');document.querySelectorAll('#storage-management button').forEach(button=>button.disabled=true);showStorageStatus()}
function finishStorageOperation(message,scroll=true){storageStatus.removeAttribute('aria-busy');storageStatus.classList.remove('storage-operation-running');storageStatus.textContent=message;document.querySelectorAll('#storage-management button').forEach(button=>button.disabled=false);if(scroll)showStorageStatus()}
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
    if(!armed){armed=true;confirmButton.textContent=t('ui.0645');confirmButton.setAttribute('aria-pressed','true');storageStatus.textContent=t('ui.0632');armTimer=setTimeout(()=>{reset();storageStatus.textContent=t('ui.0646')},8000);return}
    reset();hideStorageConfirmation();
    try{await onConfirm(confirmationValue||'')}catch(error){finishStorageOperation(error.message)}
  });
  const cancel=storageButton('ui.0633',()=>{const wasArmed=armed;reset();hideStorageConfirmation();if(wasArmed)storageStatus.textContent=t('ui.0646')});
  actions.append(confirmButton,cancel);form.append(actions);storageConfirmation.replaceChildren(form);storageConfirmation.hidden=false;heading.scrollIntoView({block:'nearest'});
}
function storageOperationPhase(status,kind){if(status.status==='queued')return t('ui.0634');if(kind==='initialization'){if(status.operation==='use-existing')return t('ui.0627');const phases={checking:'ui.0635',wiping:'ui.0636',partitioning:'ui.0637',formatting:'ui.0638',mounting:'ui.0639'};return t(phases[status.phase]||'ui.0622')}const phases={copying:'ui.0663',quiescing:'ui.0664',verifying:'ui.0665',switching:'ui.0666','pending-health':'ui.0667'};return t(phases[status.status]||'ui.0608',{destination:status.destination||t('ui.0233')})}
function initializationCompletionMessage(status){if(status.operation==='use-existing')return t('ui.0661',{mount:status.mount||t('ui.0233')});return t('ui.0660',{mount:status.mount||t('ui.0233')})}
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
async function startDiskInitialization(disk,confirmValue){beginStorageOperation(t('ui.0622'));await new Promise(requestAnimationFrame);try{await postStorage('initialize',disk,{confirm:confirmValue});await watchStorageOperation('initialization',disk.stable_id)}catch(error){finishStorageOperation(error.message)}}
function initializeStorage(disk,button){
  const label=t('ui.0593');
  const reset=()=>{if(button.dataset.armTimer)clearTimeout(Number(button.dataset.armTimer));delete button.dataset.armTimer;delete button.dataset.armed;button.textContent=label;button.removeAttribute('aria-pressed')};
  if(button.dataset.armed==='true'){
    reset();
    void startDiskInitialization(disk,disk.stable_id);
    return;
  }
  button.dataset.armed='true';button.textContent=t('ui.0645');button.setAttribute('aria-pressed','true');
  storageStatus.textContent=`${t('ui.0615',{model:disk.model,capacity:formatBytes(disk.capacity_bytes),id:disk.stable_id})} ${t('ui.0632')}`;
  button.dataset.armTimer=String(setTimeout(()=>{if(button.dataset.armed==='true'){reset();storageStatus.textContent=t('ui.0646')}},8000));
}
async function adoptStorage(disk){beginStorageOperation(t('ui.0626'));try{await postStorage('adopt',disk);await refreshStorage();finishStorageOperation(t('ui.0602',{message:t('ui.0592')}))}catch(error){finishStorageOperation(error.message)}}
async function useExistingStorage(disk){beginStorageOperation(t('ui.0627'));try{await postStorage('use-existing',disk);await watchStorageOperation('initialization',disk.stable_id)}catch(error){finishStorageOperation(error.message)}}
async function moveLibraryStorage(targetMount){beginStorageOperation(t('ui.0662'));await new Promise(resolve=>setTimeout(resolve,0));try{const preview=await postStorage('migration-preview',targetMount);if(!preview.eligible){finishStorageOperation(t('ui.0610'));return}const existingNotice=preview.destination_empty===true?'':t('ui.0670');const summary=`${t('ui.0601',{bytes:formatBytes(preview.copy_bytes),source:preview.data_root,destination:preview.destination,free:formatBytes(preview.free_bytes),model:preview.model,id:preview.uuid,filesystem:preview.filesystem,mount:preview.mount})} ${existingNotice} ${t('ui.0604')} ${t('ui.0609')}`;finishStorageOperation(t('ui.0668'),false);showStorageConfirmation({title:t('ui.0643'),detail:summary,confirmationValue:preview.target_id,submitLabel:t('ui.0595'),onConfirm:async confirmValue=>{beginStorageOperation(t('ui.0608'));await new Promise(resolve=>setTimeout(resolve,0));try{await postStorage('move-library',{target_mount:preview.target_mount},{target_id:preview.target_id,confirm:confirmValue});await watchStorageOperation('migration',preview.target_id)}catch(error){finishStorageOperation(error.message)}}})}catch(error){finishStorageOperation(error.message)}}
let storageInventorySignature=null;
let storageTerminalNoticeKey=null;
function createStorageCard(disk){
  const card=document.createElement('article');
  card.className='storage-disk-card';
  const heading=document.createElement('h4');
  heading.textContent=t('ui.0587',{model:disk.model,capacity:formatBytes(disk.capacity_bytes)});
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
  card.append(heading,transport,identity,inventory);
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
    }
    if(disk.adoption_stale){
      const warning=document.createElement('p');
      warning.className='storage-safety-note';
      warning.textContent=t('ui.0624');
      card.append(warning);
      if(disk.adoptable)card.append(storageButton('ui.0623',()=>adoptStorage(disk)));
    }else{
      const actions=document.createElement('div');
      actions.className='button-row';
      if(!disk.mount){const initialize=storageButton('ui.0593',()=>initializeStorage(disk,initialize));actions.append(initialize)}
      if(!disk.mount&&disk.partitions?.length===1&&disk.partitions[0].filesystem==='ext4')actions.append(storageButton('ui.0611',()=>useExistingStorage(disk)));
      card.append(actions);
    }
  }else if(disk.adoptable){
    card.append(storageButton('ui.0591',()=>adoptStorage(disk)));
  }
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
      if(!cards.length)cards.push(document.createTextNode(t('ui.0596')));
      if(migration.status&&migration.status!=='idle'){
        const state=document.createElement('p');
        state.className=migration.status==='failed'?'storage-safety-note':'subtle';
        state.textContent=migration.status==='failed'
          ?t('ui.0673',{error:migration.error||t('ui.0233')})
          :t('ui.0603',{status:migration.status});
        cards.push(state);
      }
      storageList.replaceChildren(...cards);
    }
    if(storageStatus.hasAttribute('aria-busy')){
      document.querySelectorAll('#storage-management button').forEach(button=>button.disabled=true);
    }else if(initialization.status==='queued'||initialization.status==='initializing'){
      beginStorageOperation(storageOperationPhase(initialization,'initialization'));
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
          finishStorageOperation(migration.status==='failed'
            ?t('ui.0673',{error:migration.error||t('ui.0233')})
            :t('ui.0669',{destination:migration.destination||t('ui.0233'),source:migration.source||t('ui.0233')}));
        }
      }else if(initialization.status==='completed'||initialization.status==='failed'){
        const noticeKey=`initialization:${initialization.updated_at}:${initialization.stable_id}:${initialization.status}`;
        if(noticeKey!==storageTerminalNoticeKey){
          storageTerminalNoticeKey=noticeKey;
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
function openZimEditor(item,editing,sourceButton=null,kind='zim'){
  zimSelection={item,editing,sourceButton,kind};
  zimEditorForm.reset();zimEditorError.hidden=true;
  document.querySelector('#document-description').hidden=kind!=='document';
  zimEditorForm.elements.description.value=kind==='document'?item.description:'';
  zimEditorForm.elements.title.value=item.title;
  const subjects=zimEditorForm.elements.subject;
  subjects.value=item.subject||([...subjects.options].some(option=>option.value==='general-reference')?'general-reference':subjects.options[0]?.value||'');
  document.querySelector('#zim-editor-heading').textContent=editing?'Edit library details':'Add library';
  zimEditorSave.textContent=editing?'Save changes':'Start download';
  document.querySelector('#zim-editor-note').textContent=editing?'Updates the title and subject shown in Cyberdeck. The archive, download progress, and titles inside Kiwix stay unchanged.':'Choose where this library appears in Cyberdeck. The download size and integrity will be verified before it becomes available.';
  renderZimDetails(document.querySelector('#zim-editor-details'),editing?{filename:item.filename}:item);
  document.querySelector('#zim-editor-kind').textContent=kind==='zim'?t('ui.0188'):t('ui.0502');
  if(kind==='archive'){
    document.querySelector('#zim-editor-heading').textContent='Edit document';
    document.querySelector('#zim-editor-note').textContent='Changes the display title and subject for everyone. The file stays unchanged. These edits take precedence over starter-content metadata.';
  }
  if(kind==='document'){
    document.querySelector('#zim-editor-heading').textContent='Edit document';
    document.querySelector('#zim-editor-note').textContent='Changes the title, description, and subject for everyone. Attachments stay unchanged.';
    renderZimDetails(document.querySelector('#zim-editor-details'),{filename:item.attachments.map(a=>a.filename).join(', ')});
  }
  zimEditor.showModal();
}
zimEditorCancel.addEventListener('click',()=>zimEditor.close());
zimEditor.addEventListener('cancel',event=>{if(zimEditorBusy)event.preventDefault()});
zimEditorForm.addEventListener('submit',async event=>{
  event.preventDefault();if(zimEditorBusy||!zimSelection)return;
  const {item,editing,sourceButton,kind}=zimSelection;
  const body={title:zimEditorForm.elements.title.value.trim(),subject:zimEditorForm.elements.subject.value};
  if(!editing)body.url=item.url;
  if(kind==='document')body.description=zimEditorForm.elements.description.value;
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
document.querySelector('#subject-form').addEventListener('submit',async event=>{event.preventDefault();const formElement=event.currentTarget;try{await requestJson('/api/admin/subjects',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(formElement)))});window.location.reload()}catch(error){alert(error.message)}});
const accentInput=document.querySelector('#preferences-form [name="accent_color"]');
const accentStatus=document.querySelector('#accent-color-status');
document.querySelector('#preferences-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const formElement=event.currentTarget;
  const form=new FormData(formElement);
  try{
    if(window.cyberdeckSaveAccent)await window.cyberdeckSaveAccent();
    const result=await requestJson('/api/admin/settings',{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({pdf_open_mode:form.get('pdf_open_mode'),accent_color:form.get('accent_color'),home_columns:form.get('home_columns'),subtitle:form.get('subtitle'),hide_empty_subjects:form.has('hide_empty_subjects'),always_show_subjects:form.getAll('always_show_subjects')})});
    document.querySelector('#brand-subtitle').textContent=result.settings.subtitle;
    if(window.cyberdeckSetAccent)window.cyberdeckSetAccent(result.settings.accent_color);
    accentInput.value=result.settings.accent_color;
    accentStatus.textContent='Site preferences saved.';
  }catch(error){accentStatus.textContent=t('ui.0444',{error:error.message});alert(error.message)}
});
if(document.querySelector('#hotspot')){
document.querySelectorAll('[data-hotspot]').forEach(button=>button.addEventListener('click',async()=>{try{await requestJson('/api/admin/hotspot',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.hotspot})});if(button.dataset.hotspot==='stop')hotspotConfigLoaded=false;await Promise.all([hotspotStatus(),refreshSystemOverview()])}catch(error){alert(error.message)}}));
document.querySelector('#hotspot-form').addEventListener('submit',async event=>{event.preventDefault();const formElement=event.currentTarget;const form=new FormData(formElement);try{await requestJson('/api/admin/hotspot',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action:'configure',device:form.get('device'),ssid:form.get('ssid'),password:form.get('password'),upstream_ssids:String(form.get('upstream_ssids')||'').split(/\r?\n/).map(value=>value.trim()).filter(Boolean),redundancy_minutes:Number(form.get('redundancy_minutes')),autostart:form.has('autostart')})});formElement.elements.password.value='';hotspotConfigLoaded=false;hotspotPasswordLoaded=false;await hotspotStatus();alert('Hotspot profile saved.')}catch(error){alert(error.message)}});
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
const powerPanel=document.querySelector('#management');
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
        armTimer=setTimeout(()=>{if(armedButton===button){button.textContent=label;delete button.dataset.originalLabel;armedButton=null;powerStatus.textContent=t('ui.0553')}},8000);
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
      cyberchefToggle.dataset.action=state.active?'disable':'enable';
      cyberchefToggle.textContent=t(state.active?'ui.0723':'ui.0722');
      cyberchefStatus.textContent=state.active?t('ui.0720'):state.installed?t('ui.0721'):t('ui.0719');
    }catch(error){cyberchefToggle.disabled=true;cyberchefStatus.textContent=t('ui.0729',{error:error.message})}
  }
  cyberchefToggle.addEventListener('click',async()=>{
    const action=cyberchefToggle.dataset.action;
    cyberchefToggle.disabled=true;
    cyberchefStatus.textContent=t(action==='enable'?'ui.0724':'ui.0725');
    try{await requestJson('/api/admin/cyberchef',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({action})});await refreshCyberChef()}
    catch(error){cyberchefStatus.textContent=t(action==='enable'?'ui.0726':'ui.0727',{error:error.message});cyberchefToggle.disabled=false}
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
  if(!hostnameArmed){hostnameArmed=true;hostnameButton.textContent=t('ui.0645');hostnameButton.setAttribute('aria-pressed','true');hostnameMessage.textContent=`${t('ui.0414',{url})} ${t('ui.0632')}`;hostnameArmTimer=setTimeout(()=>{resetHostnameArm();hostnameMessage.textContent=t('ui.0646')},8000);return}
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
Promise.all([refreshSubjects(),refreshZims(),refreshDocuments(),refreshExportOptions(),refreshPdfImports()]).catch(error=>alert(error.message));setInterval(()=>{if(zimPolling)refreshZims().catch(()=>{})},10000);
