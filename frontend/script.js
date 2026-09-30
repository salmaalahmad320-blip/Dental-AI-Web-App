const API_BASE = window.DENTAL_API_BASE || (window.location.pathname.startsWith('/app') ? window.location.origin : 'http://localhost:8000');
const views = [...document.querySelectorAll('.view')];
const navLinks = [...document.querySelectorAll('.nav-link')];
const fileInput = document.querySelector('#file-input');
const analysisFileInput = document.querySelector('#file-input-analysis');
const dropzone = document.querySelector('#dropzone');
const previewWrap = document.querySelector('#preview-wrap');
const previewImage = document.querySelector('#preview-image');
const analyzeButton = document.querySelector('#analyze-button');
const analysisAnalyzeButton = document.querySelector('#analysis-analyze-button');
const clearFileButton = document.querySelector('#clear-file');
const loadingState = document.querySelector('#loading-state');
const resultImage = document.querySelector('#result-image');
const originalImage = document.querySelector('#original-image');
const resultStage = document.querySelector('#result-stage');
const detectionOverlay = document.querySelector('#detection-overlay');
const historySearch = document.querySelector('#case-search');
const patientFields = document.createElement('div');
patientFields.className = 'patient-fields';
patientFields.innerHTML = '<label>Patient name<input id="patient-name-input" type="text" placeholder="Optional"></label><label>Patient ID<input id="patient-id-input" type="text" placeholder="Optional"></label>';
document.querySelector('.upload-card > p').after(patientFields);
const patientNameInput = document.querySelector('#patient-name-input');
const patientIdInput = document.querySelector('#patient-id-input');
const settingsDefaults = { clinicName: 'Northside Dental', clinicianName: 'Dr. Maya Reynolds', confidenceThreshold: 25, clinicalMode: true };
let settings = { ...settingsDefaults, ...JSON.parse(localStorage.getItem('dental-settings') || '{}') };
let selectedFile = null;
let cases = [];
const zoomLevels = { 'original-image': 1, 'result-image': 1 };
const panOffsets = { 'original-image': { x: 0, y: 0 }, 'result-image': { x: 0, y: 0 } };

function saveSettings() {
  localStorage.setItem('dental-settings', JSON.stringify(settings));
}

function getInitials(name) {
  return name.replace(/^Dr\.\s*/i, '').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'DR';
}

function applySettings() {
  document.querySelector('#clinic-name-input').value = settings.clinicName;
  document.querySelector('#clinician-name-input').value = settings.clinicianName;
  document.querySelector('#confidence-threshold').value = settings.confidenceThreshold;
  document.querySelector('#threshold-value').textContent = `${settings.confidenceThreshold}%`;
  document.querySelector('#clinic-name-display').textContent = settings.clinicName;
  document.querySelector('#clinic-avatar').textContent = settings.clinicName.trim().charAt(0).toUpperCase() || 'N';
  document.querySelector('#clinician-name-display').textContent = settings.clinicianName;
  document.querySelector('#profile-avatar').textContent = getInitials(settings.clinicianName);
  document.querySelector('.top-avatar').textContent = getInitials(settings.clinicianName);
  document.querySelector('#dashboard-greeting').textContent = `Good morning, ${settings.clinicianName}`;
  const toggle = document.querySelector('#clinical-mode-toggle');
  toggle.classList.toggle('on', settings.clinicalMode);
  toggle.setAttribute('aria-pressed', String(settings.clinicalMode));
  document.querySelector('#clinical-disclaimer').classList.toggle('hidden', !settings.clinicalMode);
}

function updateProfileSettings() {
  settings.clinicName = document.querySelector('#clinic-name-input').value.trim() || settingsDefaults.clinicName;
  settings.clinicianName = document.querySelector('#clinician-name-input').value.trim() || settingsDefaults.clinicianName;
  saveSettings();
  applySettings();
}

function setSelectedFile(file) {
  if (!file || !['image/jpeg', 'image/png'].includes(file.type)) return window.alert('Please choose a JPEG or PNG image.');
  if (file.size > 15 * 1024 * 1024) return window.alert('The image must be smaller than 15 MB.');
  selectedFile = file;
  previewImage.src = URL.createObjectURL(file);
  previewWrap.classList.remove('hidden');
  analyzeButton.disabled = false;
  analysisAnalyzeButton.disabled = false;
  originalImage.src = URL.createObjectURL(file);
  originalImage.classList.remove('hidden');
  resetZoom('original-image');
  resetZoom('result-image');
  document.querySelector('#analysis-status').textContent = 'Ready to analyze';
  showView('analysis');
}

function applyZoom(imageId) {
  const image = document.querySelector(`#${imageId}`);
  if (!image) return;
  image.style.transform = `translate(${panOffsets[imageId].x}px, ${panOffsets[imageId].y}px) scale(${zoomLevels[imageId]})`;
  image.style.cursor = zoomLevels[imageId] > 1 ? 'zoom-out' : 'zoom-in';
  const resetButton = document.querySelector(`[data-zoom-target="${imageId}"][data-zoom-action="reset"]`);
  if (resetButton) resetButton.textContent = `${zoomLevels[imageId]}x`;
}

function resetZoom(imageId) {
  zoomLevels[imageId] = 1;
  panOffsets[imageId] = { x: 0, y: 0 };
  applyZoom(imageId);
}

function limitPan(imageId) {
  const image = document.querySelector(`#${imageId}`);
  const stage = image.closest('.image-stage');
  const limit = Math.max(0, (Math.min(stage.clientWidth, stage.clientHeight) * (zoomLevels[imageId] - 1)) / 2);
  panOffsets[imageId].x = Math.max(-limit, Math.min(limit, panOffsets[imageId].x));
  panOffsets[imageId].y = Math.max(-limit, Math.min(limit, panOffsets[imageId].y));
}

function positionDetectionBoxes() {
  const image = resultImage;
  if (!image.naturalWidth || !image.naturalHeight || image.classList.contains('hidden')) return;
  const stageRect = resultStage.getBoundingClientRect();
  const imageRect = image.getBoundingClientRect();
  detectionOverlay.querySelectorAll('.detection-box').forEach(box => {
    const [x1, y1, x2, y2] = box.dataset.bbox.split(',').map(Number);
    box.style.left = `${imageRect.left - stageRect.left + x1 * imageRect.width / image.naturalWidth}px`;
    box.style.top = `${imageRect.top - stageRect.top + y1 * imageRect.height / image.naturalHeight}px`;
    box.style.width = `${(x2 - x1) * imageRect.width / image.naturalWidth}px`;
    box.style.height = `${(y2 - y1) * imageRect.height / image.naturalHeight}px`;
  });
}

function renderDetectionBoxes(detections) {
  detectionOverlay.innerHTML = detections.map((item, index) => `<button class="detection-box detection-${item.class.toLowerCase().replace(/\s+/g, '-') }" data-detection-index="${index}" data-bbox="${item.bbox.join(',')}" type="button" aria-label="Finding ${index + 1}: ${escapeHtml(item.class)} ${item.confidence.toFixed(1)}%"><em>#${index + 1}</em><span>${escapeHtml(item.class)}<b>${item.confidence.toFixed(1)}%</b></span></button>`).join('');
  detectionOverlay.querySelectorAll('.detection-box').forEach(box => box.addEventListener('click', event => {
    event.stopPropagation();
    detectionOverlay.querySelectorAll('.detection-box').forEach(item => item.classList.remove('selected'));
    box.classList.add('selected');
    document.querySelectorAll('[data-finding-index]').forEach(row => row.classList.toggle('selected', row.dataset.findingIndex === box.dataset.detectionIndex));
  }));
  resultImage.addEventListener('load', positionDetectionBoxes, { once: true });
  positionDetectionBoxes();
}

fileInput.addEventListener('change', event => setSelectedFile(event.target.files[0]));
analysisFileInput.addEventListener('change', event => setSelectedFile(event.target.files[0]));
['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add('dragging'); }));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove('dragging'); }));
dropzone.addEventListener('drop', event => setSelectedFile(event.dataTransfer.files[0]));
clearFileButton.addEventListener('click', () => { selectedFile = null; fileInput.value = ''; analysisFileInput.value = ''; previewWrap.classList.add('hidden'); analyzeButton.disabled = true; analysisAnalyzeButton.disabled = true; originalImage.classList.add('hidden'); });

function setLoading(isLoading) {
  loadingState.classList.toggle('hidden', !isLoading);
  analyzeButton.disabled = isLoading || !selectedFile;
  analysisAnalyzeButton.disabled = isLoading || !selectedFile;
  if (isLoading) document.querySelector('#analysis-status').textContent = 'Analyzing image';
}

function renderFindings(detections) {
  const target = document.querySelector('#findings-list');
  document.querySelector('#finding-count').textContent = `${detections.length} finding${detections.length === 1 ? '' : 's'}`;
  if (!detections.length) return void (target.innerHTML = '<div class="empty-row">No findings above the confidence threshold.</div>');
  target.innerHTML = detections.map((item, index) => `<button class="finding-row" data-finding-index="${index}" type="button"><span class="finding-name"><b class="finding-number">#${index + 1}</b>${escapeHtml(item.class)}</span><span class="bar"><i style="width:${Math.min(item.confidence, 100)}%"></i></span><span class="finding-confidence">${item.confidence.toFixed(1)}%</span></button>`).join('');
  target.querySelectorAll('[data-finding-index]').forEach(row => row.addEventListener('click', () => {
    const box = detectionOverlay.querySelector(`[data-detection-index="${row.dataset.findingIndex}"]`);
    if (!box) return;
    detectionOverlay.querySelectorAll('.detection-box').forEach(item => item.classList.remove('selected'));
    box.classList.add('selected');
  }));
}

function renderCaseRows(items, target) {
  if (!items.length) return void (target.innerHTML = '<div class="empty-row">No saved cases yet.</div>');
  target.innerHTML = items.slice(0, 6).map(item => {
    const names = [...new Set(item.detections.map(detection => detection.class))];
    const chips = names.length ? names.map(name => `<span class="finding-chip">${escapeHtml(name)}</span>`).join('') : '<span>None</span>';
    const date = new Date(item.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
    const patient = item.patient_name ? `${item.patient_name}${item.patient_id ? ` · ${item.patient_id}` : ''}` : 'Patient details not provided';
    if (target.id === 'dashboard-cases') return `<div class="case-row"><img class="case-thumb" src="${API_BASE}${item.image_url}" alt=""><div><strong>${escapeHtml(item.patient_name || item.case_id)}</strong><small>${escapeHtml(patient)} · ${date}</small></div><a href="${API_BASE}${item.report_url}" target="_blank">Report →</a></div>`;
    return `<article class="case-card"><img src="${API_BASE}${item.image_url}" alt="Dental X-ray for ${escapeHtml(item.patient_name || item.case_id)}"><div class="case-card-body"><strong>${escapeHtml(item.patient_name || item.case_id)}</strong><small>${escapeHtml(patient)} · ${date}</small><div class="case-tags">${chips}</div><div class="case-card-footer"><span>${item.detections.length} finding${item.detections.length === 1 ? '' : 's'}</span><a href="${API_BASE}${item.report_url}" target="_blank">Open report →</a></div></div></article>`;
  }).join('');
}

function renderCases() {
  const query = (historySearch.value || '').toLowerCase();
  const filtered = cases.filter(item => `${item.case_id} ${item.patient_name || ''} ${item.patient_id || ''} ${item.original_filename}`.toLowerCase().includes(query));
  document.querySelector('#record-count').textContent = `${filtered.length} case${filtered.length === 1 ? '' : 's'}`;
  renderCaseRows(filtered, document.querySelector('#cases-grid'));
}

function renderReports() {
  const target = document.querySelector('#reports-list');
  if (!cases.length) return void (target.innerHTML = '<div class="empty-row">Reports will appear after an analysis is completed.</div>');
  target.innerHTML = cases.map(item => `<div class="report-item"><span class="report-icon">PDF</span><div><strong>${escapeHtml(item.case_id)}</strong><small>${new Date(item.created_at).toLocaleString()} · ${escapeHtml(item.original_filename)}</small></div><a href="${API_BASE}${item.report_url}" target="_blank">Download report →</a></div>`).join('');
}

async function loadHistory() {
  try {
    const response = await fetch(`${API_BASE}/cases`);
    if (!response.ok) return;
    cases = await response.json();
    document.querySelector('#case-count').textContent = cases.length;
    document.querySelector('#month-count').textContent = cases.length;
    const confidences = cases.flatMap(item => item.detections.map(detection => detection.confidence));
    document.querySelector('#dashboard-confidence').textContent = confidences.length ? `${(confidences.reduce((sum, value) => sum + value, 0) / confidences.length).toFixed(1)}%` : '—';
    renderCaseRows(cases, document.querySelector('#dashboard-cases'));
    renderCases();
    renderReports();
  } catch (error) { console.warn('Case history unavailable', error); }
}

async function analyze() {
  if (!selectedFile) return;
  setLoading(true);
  resultImage.classList.add('hidden');
  const formData = new FormData(); formData.append('file', selectedFile); formData.append('confidence', settings.confidenceThreshold / 100); formData.append('patient_name', patientNameInput.value.trim()); formData.append('patient_id', patientIdInput.value.trim());
  try {
    const response = await fetch(`${API_BASE}/predict`, { method: 'POST', body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Analysis failed');
    resultImage.src = `${API_BASE}${payload.annotated_image_url}`;
    resultImage.classList.remove('hidden');
    renderDetectionBoxes(payload.detections);
    document.querySelector('#case-label').textContent = payload.case_id;
    document.querySelector('#analysis-status').textContent = 'Analysis complete';
    document.querySelector('#condition-count').textContent = payload.detections.length;
    const average = payload.detections.length ? payload.detections.reduce((sum, item) => sum + item.confidence, 0) / payload.detections.length : 0;
    document.querySelector('#confidence-score').textContent = payload.detections.length ? `${average.toFixed(1)}%` : '—';
    document.querySelector('#condition-detail').textContent = payload.detections.length ? [...new Set(payload.detections.map(item => item.class))].join(', ') : 'No target findings';
    renderFindings(payload.detections);
    document.querySelector('#report-content').textContent = payload.report;
    const reportUrl = `${API_BASE}${payload.report_url}`;
    document.querySelector('#download-button').href = reportUrl;
    document.querySelector('#download-button').classList.remove('disabled');
    await loadHistory();
    document.querySelector('.analysis-results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    window.alert(error.message);
  } finally { setLoading(false); }
}

function showView(name) {
  const target = ['dashboard', 'analysis', 'cases', 'reports', 'settings'].includes(name) ? name : 'dashboard';
  views.forEach(view => view.classList.toggle('active', view.dataset.page === target));
  navLinks.forEach(link => link.classList.toggle('active', link.dataset.view === target));
  document.querySelector('#page-label').textContent = target.charAt(0).toUpperCase() + target.slice(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.querySelectorAll('[data-view], [data-navigate]').forEach(element => element.addEventListener('click', event => {
  const target = element.dataset.view || element.dataset.navigate;
  event.preventDefault(); history.replaceState(null, '', `#${target}`); showView(target);
}));
window.addEventListener('hashchange', () => showView(window.location.hash.slice(1)));
analyzeButton.addEventListener('click', analyze);
analysisAnalyzeButton.addEventListener('click', analyze);
historySearch.addEventListener('input', renderCases);
document.querySelectorAll('[data-zoom-action]').forEach(button => button.addEventListener('click', () => {
  const imageId = button.dataset.zoomTarget;
  const action = button.dataset.zoomAction;
  if (action === 'in') zoomLevels[imageId] = Math.min(3, zoomLevels[imageId] + 0.25);
  if (action === 'out') zoomLevels[imageId] = Math.max(1, zoomLevels[imageId] - 0.25);
  if (action === 'reset') return resetZoom(imageId);
  if (zoomLevels[imageId] === 1) panOffsets[imageId] = { x: 0, y: 0 };
  limitPan(imageId);
  applyZoom(imageId);
  if (imageId === 'result-image') window.requestAnimationFrame(positionDetectionBoxes);
}));
document.querySelectorAll('.image-stage').forEach(stage => {
  const image = stage.querySelector('img');
  if (!image) return;
  let dragStart = null;
  stage.addEventListener('pointerdown', event => {
    if (zoomLevels[image.id] <= 1 || event.target.closest('.zoom-controls')) return;
    dragStart = { x: event.clientX - panOffsets[image.id].x, y: event.clientY - panOffsets[image.id].y };
    stage.setPointerCapture(event.pointerId);
    stage.classList.add('is-panning');
  });
  stage.addEventListener('pointermove', event => {
    if (!dragStart) return;
    panOffsets[image.id] = { x: event.clientX - dragStart.x, y: event.clientY - dragStart.y };
    limitPan(image.id);
    applyZoom(image.id);
    if (image.id === 'result-image') positionDetectionBoxes();
  });
  const stopDragging = () => { dragStart = null; stage.classList.remove('is-panning'); };
  stage.addEventListener('pointerup', stopDragging);
  stage.addEventListener('pointercancel', stopDragging);
});
window.addEventListener('resize', positionDetectionBoxes);
document.querySelector('#save-profile-button').addEventListener('click', updateProfileSettings);
document.querySelector('#confidence-threshold').addEventListener('input', event => {
  settings.confidenceThreshold = Number(event.target.value);
  saveSettings();
  applySettings();
});
document.querySelector('#clinical-mode-toggle').addEventListener('click', () => {
  settings.clinicalMode = !settings.clinicalMode;
  saveSettings();
  applySettings();
});
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = value; return div.innerHTML; }
applySettings();
loadHistory();
showView(window.location.hash.slice(1) || 'dashboard');
