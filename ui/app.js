/* boardcam UI — задания, библиотека, прогоны. Чистый JS, без зависимостей. */
(function () {
'use strict';

var ROLES = ['rough', 'finish', 'profile', 'groove', 'surface'];
var ROLE_LABELS = { rough: 'черновая', finish: 'чистовая', profile: 'контур', groove: 'канавка', surface: 'выравнивание' };
var TOOL_TYPES = ['flat', 'bowl', 'ball', 'vee', 'surfacing'];
var NAME_RE = /^[A-Za-z0-9_.-]+$/;

var state = {
  shapes: [],
  library: { tools: [], materials: [], machine: {} },
  jobs: [],
  job: null,          // редактируемое задание
  runs: [],
  viewer: null
};

/* ---------- утилиты DOM ---------- */
function $(sel, root) { return (root || document).querySelector(sel); }
function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
function h(tag, attrs, children) {
  var e = document.createElement(tag);
  if (attrs) {
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.indexOf('on') === 0) e.addEventListener(k.slice(2), v);
      else if (k === 'checked' || k === 'disabled' || k === 'hidden' || k === 'selected' || k === 'value') e[k] = v;
      else e.setAttribute(k, v);
    });
  }
  append(e, children);
  return e;
}
function append(e, children) {
  if (children === undefined || children === null || children === false) return;
  if (Array.isArray(children)) { children.forEach(function (c) { append(e, c); }); return; }
  e.appendChild(children instanceof Node ? children : document.createTextNode(String(children)));
}
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
function setErr(node, msg) { node.textContent = msg || ''; node.hidden = !msg; }
function enc(s) { return encodeURIComponent(String(s)); }
function fmt(n) { return (n === null || n === undefined || n === '') ? '—' : String(n); }
function num(n, d) { return (typeof n === 'number' && isFinite(n)) ? (d !== undefined ? n.toFixed(d) : String(n)) : fmt(n); }
function kb(bytes) { return typeof bytes === 'number' ? (bytes / 1024).toFixed(1) + ' КБ' : ''; }
function minutes(m) { return typeof m === 'number' ? m.toFixed(1) + ' мин' : ''; }
function spinner(text) { return h('span', { class: 'status' }, [h('span', { class: 'spin' }), text || '']); }
function msgClass(level) {
  var l = String(level || '').toLowerCase();
  if (l === 'error' || l === 'refuse' || l === 'refusal' || l === 'fatal') return 'msg bad';
  if (l === 'warn' || l === 'warning') return 'msg warn';
  return 'msg muted';
}
function msgLine(m) {
  var parts = [];
  if (m.code) parts.push('[' + m.code + ']');
  parts.push(m.text || '');
  if (m.feature) parts.push('(' + m.feature + ')');
  return h('div', { class: msgClass(m.level), text: parts.join(' ') });
}

/* ---------- HTTP ---------- */
async function api(method, path, body) {
  var opts = { method: method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  var res = await fetch(path, opts);
  var text = await res.text();
  var data = null;
  if (text) { try { data = JSON.parse(text); } catch (e) { data = null; } }
  if (!res.ok) {
    var msg = (data && (data.error || data.detail || (Array.isArray(data.errors) && data.errors.join('; ')))) ||
      (text && data === null ? text.slice(0, 300) : '') || (res.status + ' ' + res.statusText);
    var err = new Error(method + ' ' + path + ' → ' + msg);
    err.status = res.status; err.data = data;
    throw err;
  }
  if (data === null && text) throw new Error(method + ' ' + path + ': ответ не JSON');
  return data;
}
async function fetchText(url) {
  var res = await fetch(url);
  if (!res.ok) throw new Error(url + ' → ' + res.status + ' ' + res.statusText);
  return await res.text();
}
async function fetchBuffer(url) {
  var res = await fetch(url);
  if (!res.ok) throw new Error(url + ' → ' + res.status + ' ' + res.statusText);
  return await res.arrayBuffer();
}

/* ---------- вкладки ---------- */
function showTab(name) {
  $all('.tab').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === name); });
  $all('main > section').forEach(function (s) { s.hidden = (s.id !== 'tab-' + name); });
  if (name === 'runs') loadRuns();
  if (name === 'library') loadLibrary();
  if (name === 'surface') loadSurfaceTools();
}

/* ---------- doctor ---------- */
async function loadDoctor() {
  var banner = $('#doctor-banner');
  try {
    var d = await api('GET', '/api/doctor');
    var msgs = [];
    if (!d.openscad) msgs.push(d.openscad_missing || 'OpenSCAD не найден');
    if (d.library_error) msgs.push('Библиотека: ' + d.library_error);
    banner.textContent = msgs.join('\n');
    banner.hidden = !msgs.length;
  } catch (e) {
    setErr($('#global-error'), 'Не удалось опросить сервер (/api/doctor): ' + e.message);
  }
}

/* ---------- формы (shapes) ---------- */
async function loadShapes() {
  try {
    state.shapes = await api('GET', '/api/shapes') || [];
  } catch (e) {
    state.shapes = [];
    setErr($('#global-error'), 'Формы не загружены: ' + e.message);
  }
}
function findShape(name) {
  for (var i = 0; i < state.shapes.length; i++) if (state.shapes[i].name === name) return state.shapes[i];
  return null;
}
/* Тип параметра Customizer: числовой диапазон / перечисление / свободное поле. */
function paramKind(p) {
  var vals = Array.isArray(p.values) ? p.values.map(String) : [];
  if (vals.length >= 3) {
    var nums = vals.map(parseFloat);
    if (nums.every(isFinite)) {
      var step = nums[1] - nums[0];
      var uniform = step > 0 && nums.every(function (n, i) {
        return i === 0 || Math.abs((n - nums[i - 1]) - step) <= 1e-4 * Math.max(1, Math.abs(step));
      });
      if (uniform) return { type: 'range', min: nums[0], max: nums[nums.length - 1], step: parseFloat(step.toPrecision(6)) };
    }
  }
  if (vals.length) return { type: 'enum', values: vals };
  var d = p.default;
  if (typeof d === 'number' || (typeof d === 'string' && d.trim() !== '' && isFinite(Number(d)))) return { type: 'number' };
  return { type: 'text' };
}

/* ---------- библиотека (данные) ---------- */
async function loadLibrary() {
  try {
    var lib = await api('GET', '/api/library');
    state.library = { tools: lib.tools || [], materials: lib.materials || [], machine: lib.machine || {} };
    setErr($('#library-error'), '');
  } catch (e) {
    setErr($('#library-error'), 'Библиотека не загружена: ' + e.message);
  }
  renderLibrary();
  if (state.job) { renderMaterialOptions(); renderToolSelects(); }
}
function findTool(id) {
  for (var i = 0; i < state.library.tools.length; i++) if (state.library.tools[i].id === id) return state.library.tools[i];
  return null;
}
function findMaterial(id) {
  for (var i = 0; i < state.library.materials.length; i++) if (state.library.materials[i].id === id) return state.library.materials[i];
  return null;
}

/* ================= ЗАДАНИЯ ================= */
async function loadJobs() {
  try {
    state.jobs = await api('GET', '/api/jobs') || [];
    setErr($('#jobs-error'), '');
  } catch (e) {
    setErr($('#jobs-error'), 'Список заданий не загружен: ' + e.message);
  }
  renderJobList();
}
function renderJobList() {
  var box = clear($('#job-list'));
  if (!state.jobs.length) { box.appendChild(h('div', { class: 'muted', text: 'Заданий пока нет' })); return; }
  state.jobs.forEach(function (j) {
    if (j.error) {
      box.appendChild(h('div', { class: 'row broken', title: j.error }, [h('b', { text: j.name || '?' }), h('span', { class: 'muted', text: 'ошибка: ' + j.error })]));
      return;
    }
    box.appendChild(h('div', {
      class: 'row' + (state.job && state.job._saved && state.job.name === j.name ? ' sel' : ''),
      onclick: function () { selectJob(j.name); }
    }, [
      h('b', { text: j.name }),
      h('span', { class: 'muted', text: [j.shape, j.preset].filter(Boolean).join(' / ') }),
      h('span', { class: 'muted', text: j.material || '' })
    ]));
  });
}
function normalizeJob(j) {
  j.schema = 1;
  j.overrides = j.overrides && typeof j.overrides === 'object' ? j.overrides : {};
  j.tools = j.tools && typeof j.tools === 'object' ? j.tools : {};
  j.options = j.options && typeof j.options === 'object' ? j.options : {};
  if (!j.options.flatten) j.options.flatten = 'auto';
  if (!j.options.profile_mode) j.options.profile_mode = 'auto';
  j.notes = j.notes || '';
  j.material = j.material || '';
  j.preset = j.preset || '';
  return j;
}
function jobPayload() {
  var j = state.job;
  return { schema: 1, name: j.name, shape: j.shape, preset: j.preset || '', overrides: j.overrides, material: j.material,
    tools: j.tools, options: { flatten: j.options.flatten, profile_mode: j.options.profile_mode }, notes: j.notes };
}
function newJob() {
  var s = state.shapes[0] || null;
  var presets = s && s.presets ? Object.keys(s.presets) : [];
  state.job = normalizeJob({ name: '', shape: s ? s.name : '', preset: presets[0] || '', _saved: false });
  hideResults();
  fillEditor();
  renderJobList();
}
async function selectJob(name) {
  setErr($('#job-error'), '');
  try {
    var j = await api('GET', '/api/jobs/' + enc(name));
    j._saved = true;
    state.job = normalizeJob(j);
    hideResults();
    fillEditor();
    renderJobList();
  } catch (e) {
    setErr($('#jobs-error'), e.message);
  }
}
function hideResults() {
  $('#plan-panel').hidden = true;
  $('#gen-panel').hidden = true;
}

function fillEditor() {
  var j = state.job;
  $('#job-editor').hidden = !j;
  $('#preview-card').hidden = !j;
  if (!j) return;
  $('#job-editor-title').textContent = j._saved ? 'Задание ' + j.name : 'Новое задание';
  $('#job-name').value = j.name || '';
  var sel = clear($('#job-shape'));
  state.shapes.forEach(function (s) { sel.appendChild(h('option', { value: s.name, text: s.name })); });
  if (j.shape && !findShape(j.shape)) sel.appendChild(h('option', { value: j.shape, text: j.shape + ' (нет в каталоге)' }));
  if (!j.shape && state.shapes.length) j.shape = state.shapes[0].name;
  sel.value = j.shape || '';
  renderPresetOptions();
  renderMaterialOptions();
  renderOverrides();
  renderToolSelects();
  $('#job-flatten').value = j.options.flatten;
  $('#job-profile').value = j.options.profile_mode;
  $('#job-notes').value = j.notes;
  $('#job-delete').disabled = !j._saved;
  $('#job-confirm').hidden = true;
  schedulePreview();
}
function renderPresetOptions() {
  var j = state.job, s = findShape(j.shape);
  var sel = clear($('#job-preset'));
  sel.appendChild(h('option', { value: '', text: '— без набора —' }));
  var names = s && s.presets ? Object.keys(s.presets) : [];
  names.forEach(function (n) { sel.appendChild(h('option', { value: n, text: n })); });
  if (j.preset && names.indexOf(j.preset) < 0) sel.appendChild(h('option', { value: j.preset, text: j.preset + ' (нет у формы)' }));
  sel.value = j.preset || '';
}
function renderMaterialOptions() {
  var j = state.job;
  var sel = clear($('#job-material'));
  sel.appendChild(h('option', { value: '', text: '— не выбран —' }));
  state.library.materials.forEach(function (m) {
    sel.appendChild(h('option', { value: m.id, text: (m.title || m.id) + (m.reference ? ' (эталон)' : '') }));
  });
  if (j.material && !findMaterial(j.material)) sel.appendChild(h('option', { value: j.material, text: j.material + ' (нет в библиотеке)' }));
  sel.value = j.material || '';
  updateMaterialHint();
}
function updateMaterialHint() {
  var m = findMaterial(state.job.material);
  var parts = [];
  if (m) {
    if (m.hint) parts.push(m.hint);
    else if (m.notes) parts.push(m.notes);
    var tech = [];
    if (m.janka !== null && m.janka !== undefined) tech.push('Янка ' + m.janka);
    if (m.feed_scale !== undefined) tech.push('подача ×' + m.feed_scale);
    if (m.rpm) tech.push(m.rpm + ' об/мин');
    if (m.dial !== undefined && m.dial !== null && m.dial !== '') tech.push('диск ' + m.dial);
    if (tech.length) parts.push(tech.join(', '));
  }
  $('#material-hint').textContent = parts.join(' · ');
}
function renderOverrides() {
  var j = state.job, s = findShape(j.shape);
  var tb = clear($('#job-overrides'));
  if (!s) { tb.appendChild(h('tr', {}, h('td', { colspan: 4, class: 'muted', text: 'Форма не найдена' }))); return; }
  var preset = (j.preset && s.presets && s.presets[j.preset]) || {};
  (s.params || []).forEach(function (p) {
    var name = p.name;
    var presetVal = (name in preset) ? preset[name] : (p.default === undefined || p.default === null ? '' : String(p.default));
    var cur = j.overrides[name];
    var kind = paramKind(p);
    var input;
    if (kind.type === 'range') {
      input = h('input', { type: 'number', min: kind.min, max: kind.max, step: kind.step, value: cur === undefined ? '' : cur });
    } else if (kind.type === 'enum') {
      input = h('select', {}, [h('option', { value: '', text: '— из набора —' })].concat(kind.values.map(function (v) {
        return h('option', { value: v, text: v });
      })));
      if (cur !== undefined && kind.values.indexOf(String(cur)) >= 0) input.value = String(cur);
      else if (cur !== undefined) { input.appendChild(h('option', { value: String(cur), text: String(cur) + ' (?)' })); input.value = String(cur); }
    } else if (kind.type === 'number') {
      input = h('input', { type: 'number', step: 'any', value: cur === undefined ? '' : cur });
    } else {
      input = h('input', { type: 'text', value: cur === undefined ? '' : cur });
    }
    input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', function () { setOverride(name, input.value, kind); });
    var clearBtn = h('button', { type: 'button', class: 'btn small', title: 'Сбросить переопределение', text: '×', onclick: function () {
      input.value = ''; setOverride(name, '', kind);
    } });
    tb.appendChild(h('tr', {}, [
      h('td', { text: name, title: p.description || '' }),
      h('td', { class: 'preset-val', text: presetVal === '' ? '—' : presetVal }),
      h('td', {}, input),
      h('td', {}, clearBtn)
    ]));
  });
  if (!(s.params || []).length) tb.appendChild(h('tr', {}, h('td', { colspan: 4, class: 'muted', text: 'У формы нет параметров' })));
}
function setOverride(name, raw, kind) {
  var j = state.job;
  raw = String(raw).trim();
  if (raw === '') delete j.overrides[name];
  else if ((kind.type === 'range' || kind.type === 'number') && isFinite(Number(raw))) j.overrides[name] = Number(raw);
  else j.overrides[name] = raw;
  schedulePreview();
}
function renderToolSelects() {
  var j = state.job;
  var box = clear($('#job-tools'));
  ROLES.forEach(function (role) {
    var sel = h('select', {}, h('option', { value: '', text: 'автоматически' }));
    var cur = j.tools[role] || '';
    var found = false;
    state.library.tools.forEach(function (t) {
      if (!Array.isArray(t.roles) || t.roles.indexOf(role) < 0) return;
      if (t.id === cur) found = true;
      var label = (t.title || t.id) + (t.name ? ' — ' + t.name : '');
      sel.appendChild(h('option', { value: t.id, text: label }));
    });
    if (cur && !found) sel.appendChild(h('option', { value: cur, text: cur + ' (нет в библиотеке или без этой роли)' }));
    sel.value = cur;
    sel.addEventListener('change', function () {
      if (sel.value) j.tools[role] = sel.value; else delete j.tools[role];
    });
    box.appendChild(h('label', {}, [role + ' — ' + ROLE_LABELS[role], sel]));
  });
}

/* --- превью: debounce 400 мс, не больше одного запроса одновременно --- */
var preview = { timer: null, loading: false, queued: false, lastUrl: '' };
function previewUrl() {
  var j = state.job;
  if (!j || !j.shape) return '';
  var q = ['shape=' + enc(j.shape)];
  if (j.preset) q.push('preset=' + enc(j.preset));
  Object.keys(j.overrides).forEach(function (k) { q.push(enc(k) + '=' + enc(j.overrides[k])); });
  return '/api/preview.svg?' + q.join('&');
}
function schedulePreview() {
  if (preview.timer) clearTimeout(preview.timer);
  preview.timer = setTimeout(requestPreview, 400);
}
function requestPreview() {
  preview.timer = null;
  var url = previewUrl();
  var img = $('#job-preview');
  if (!url) { img.removeAttribute('src'); preview.lastUrl = ''; return; }
  if (preview.loading) { preview.queued = true; return; }
  if (url === preview.lastUrl) return;
  preview.loading = true;
  preview.lastUrl = url;
  $('#preview-spin').hidden = false;
  setErr($('#preview-error'), '');
  img.src = url;
}
function previewDone(ok) {
  preview.loading = false;
  $('#preview-spin').hidden = true;
  if (!ok) setErr($('#preview-error'), 'Превью не получено (' + preview.lastUrl + ')');
  if (preview.queued) { preview.queued = false; requestPreview(); }
}

/* --- кнопки задания --- */
function jobBusy(on, statusNode) {
  ['#job-save', '#job-delete', '#job-plan', '#job-generate'].forEach(function (s) { $(s).disabled = on; });
  if (!on && state.job) $('#job-delete').disabled = !state.job._saved;
  var st = clear($('#job-status'));
  if (statusNode) st.appendChild(statusNode);
}
function readJobFromForm() {
  var j = state.job;
  j.name = $('#job-name').value.trim();
  j.notes = $('#job-notes').value;
  j.options.flatten = $('#job-flatten').value;
  j.options.profile_mode = $('#job-profile').value;
}
async function saveJob() {
  var j = state.job; if (!j) return;
  readJobFromForm();
  var errNode = $('#job-error'); setErr(errNode, '');
  if (!NAME_RE.test(j.name)) { setErr(errNode, 'Имя задания: только латиница, цифры, «_», «.», «-»'); return; }
  if (!j.shape) { setErr(errNode, 'Не выбрана форма'); return; }
  jobBusy(true, spinner('Сохранение…'));
  var saved = false;
  try {
    var r = await api('POST', '/api/jobs', jobPayload());
    if (r && r.ok === false) throw new Error((r.errors || []).join('; ') || 'сервер отказал');
    j.name = (r && r.name) || j.name;
    j._saved = true;
    saved = true;
    await loadJobs();
    fillEditor();
  } catch (e) {
    setErr(errNode, e.message);
  } finally {
    jobBusy(false, null);
  }
  if (saved) $('#job-status').textContent = 'Сохранено';
}
function askDeleteJob() {
  var j = state.job; if (!j || !j._saved) return;
  var box = clear($('#job-confirm'));
  box.hidden = false;
  box.appendChild(document.createTextNode('Точно удалить задание «' + j.name + '»?'));
  box.appendChild(h('button', { type: 'button', class: 'btn small danger', text: 'Да', onclick: deleteJob }));
  box.appendChild(h('button', { type: 'button', class: 'btn small', text: 'Нет', onclick: function () { box.hidden = true; } }));
}
async function deleteJob() {
  var j = state.job;
  $('#job-confirm').hidden = true;
  jobBusy(true, spinner('Удаление…'));
  try {
    var r = await api('DELETE', '/api/jobs/' + enc(j.name));
    if (r && r.ok === false) throw new Error((r.errors || []).join('; ') || 'сервер отказал');
    state.job = null;
    hideResults();
    fillEditor();
    await loadJobs();
  } catch (e) {
    setErr($('#job-error'), e.message);
  } finally {
    jobBusy(false, null);
  }
}
async function planJob() {
  var j = state.job; if (!j) return;
  readJobFromForm();
  setErr($('#job-error'), '');
  var panel = $('#plan-panel'), body = clear($('#plan-body'));
  panel.hidden = false;
  body.appendChild(spinner('Считаем план…'));
  jobBusy(true, spinner('План…'));
  try {
    var res = await api('POST', '/api/plan', jobPayload());
    renderPlan(res);
  } catch (e) {
    clear(body).appendChild(h('div', { class: 'errline', text: e.message }));
  } finally {
    jobBusy(false, null);
  }
}
function renderDesign(body, d) {
  if (!d) return;
  var head = [];
  if (d.shape) head.push('Форма: ' + d.shape + (d.variant ? ' / ' + d.variant : ''));
  if (d.blank) {
    var o = d.blank.origin;
    head.push('Заготовка: ' + num(d.blank.size_x) + ' × ' + num(d.blank.size_y) + ' × ' + num(d.blank.thick) + ' мм' +
      (o !== undefined ? ', ноль: ' + (typeof o === 'object' ? JSON.stringify(o) : o) : ''));
  } else if (d.thick !== undefined) head.push('Толщина: ' + num(d.thick) + ' мм');
  if (head.length) body.appendChild(h('div', { class: 'kv', text: head.join(' · ') }));
  if (Array.isArray(d.pockets) && d.pockets.length) {
    body.appendChild(h('h3', { text: 'Карманы' }));
    body.appendChild(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, [
      h('thead', {}, h('tr', {}, [h('th', { text: 'id' }), h('th', { text: 'Площадь, см²' }), h('th', { text: 'Глубина, мм' }), h('th', { text: 'R дна, мм' }), h('th', { text: 'Частей' })])),
      h('tbody', {}, d.pockets.map(function (p) {
        return h('tr', {}, [h('td', { text: fmt(p.id) }), h('td', { text: num(p.area_cm2, 1) }), h('td', { text: num(p.depth) }),
          h('td', { text: num(p.floor_fillet_r) }), h('td', { text: Array.isArray(p.parts) ? String(p.parts.length) : fmt(p.parts) })]);
      }))
    ])));
  }
  if (Array.isArray(d.messages) && d.messages.length) {
    body.appendChild(h('h3', { text: 'Сообщения геометрии' }));
    d.messages.forEach(function (m) { body.appendChild(msgLine(m)); });
  }
}
function renderPlan(res) {
  var body = clear($('#plan-body'));
  var p = res.plan || {};
  if (p.ok) {
    body.appendChild(h('div', { class: 'okline', text: 'План готов' + (p.material && p.material.title ? ' · материал: ' + p.material.title : '') }));
    var tools = p.tools || {}, reasons = p.reasons || {};
    var roles = Object.keys(tools);
    if (roles.length) {
      body.appendChild(h('h3', { text: 'Фрезы' }));
      body.appendChild(h('div', { class: 'tbl-wrap' }, h('table', { class: 'tbl' }, [
        h('thead', {}, h('tr', {}, [h('th', { text: 'Роль' }), h('th', { text: 'Фреза' }), h('th', { text: 'Почему' })])),
        h('tbody', {}, roles.map(function (role) {
          var t = tools[role] || {};
          return h('tr', {}, [
            h('td', { text: role + (ROLE_LABELS[role] ? ' — ' + ROLE_LABELS[role] : '') }),
            h('td', {}, [t.color ? h('span', { class: 'swatch', style: 'background:' + t.color }) : null, (t.title || t.id || '—') + (t.name ? ' (' + t.name + ')' : '')]),
            h('td', { class: 'muted', style: 'white-space:normal', text: reasons[role] || '' })
          ]);
        }))
      ])));
    }
    if (Array.isArray(p.ops) && p.ops.length) {
      body.appendChild(h('h3', { text: 'Операции' }));
      body.appendChild(h('ul', { class: 'files' }, p.ops.map(function (o) {
        return h('li', {}, [h('span', { class: 'mono', text: o.filename || '' }), o.title ? ' — ' + o.title : '', o.role ? h('span', { class: 'muted', text: ' [' + o.role + ']' }) : null]);
      })));
    }
    (p.notes || []).forEach(function (n) { body.appendChild(msgLine(Object.assign({ level: 'note' }, n))); });
  } else {
    body.appendChild(h('div', { class: 'banner bad', text: 'План не составлен' }));
    (p.refusals || []).forEach(function (r) { body.appendChild(msgLine(Object.assign({}, r, { level: 'error' }))); });
    (p.notes || []).forEach(function (n) { body.appendChild(msgLine(Object.assign({ level: 'note' }, n))); });
  }
  renderDesign(body, res.design);
}
async function generateJob() {
  var j = state.job; if (!j) return;
  readJobFromForm();
  setErr($('#job-error'), '');
  var panel = $('#gen-panel'), body = clear($('#gen-body'));
  panel.hidden = false;
  var t0 = Date.now();
  var counter = h('span', { text: '0 с' });
  body.appendChild(h('div', { class: 'status' }, [h('span', { class: 'spin' }), 'Генерация G-code… ', counter]));
  var timer = setInterval(function () { counter.textContent = Math.round((Date.now() - t0) / 1000) + ' с'; }, 500);
  jobBusy(true, spinner('Генерация…'));
  try {
    var res;
    try {
      res = await api('POST', '/api/generate', jobPayload());
    } catch (e) {
      if (e.data && (e.data.refused || e.data.verdict !== undefined)) res = e.data; else throw e;
    }
    renderGenerate(res, Math.round((Date.now() - t0) / 1000));
  } catch (e) {
    clear(body).appendChild(h('div', { class: 'errline', text: e.message }));
  } finally {
    clearInterval(timer);
    jobBusy(false, null);
  }
}
function renderGenerate(res, seconds) {
  var body = clear($('#gen-body'));
  if (res.refused) {
    body.appendChild(h('div', { class: 'banner bad', text: 'НА СТАНОК НЕ НЕСТИ — генерация отклонена' }));
    ((res.plan && res.plan.refusals) || []).forEach(function (r) { body.appendChild(msgLine(Object.assign({}, r, { level: 'error' }))); });
    if (Array.isArray(res.design_messages) && res.design_messages.length) {
      body.appendChild(h('h3', { text: 'Сообщения геометрии' }));
      res.design_messages.forEach(function (m) { body.appendChild(msgLine(m)); });
    }
    return;
  }
  if (res.ok) body.appendChild(h('div', { class: 'banner ok', text: res.verdict || 'OK' }));
  else body.appendChild(h('div', { class: 'banner bad', text: 'НА СТАНОК НЕ НЕСТИ\n' + (res.verdict || '') }));
  var meta = [];
  if (res.run && res.run.stamp) meta.push('прогон ' + res.run.stamp);
  if (seconds !== undefined) meta.push(seconds + ' с');
  if (meta.length) body.appendChild(h('div', { class: 'muted', text: meta.join(' · ') }));
  if (Array.isArray(res.files) && res.files.length) {
    body.appendChild(h('h3', { text: 'Файлы G-code' }));
    body.appendChild(h('ul', { class: 'files' }, res.files.map(function (f) {
      return h('li', {}, [h('a', { href: f.url, download: f.name, text: f.name }), ' ', h('span', { class: 'muted', text: [kb(f.size), minutes(f.minutes)].filter(Boolean).join(', ') })]);
    })));
  }
  if (res.run && res.run.url) {
    body.appendChild(h('div', { class: 'kv' }, [
      h('a', { href: res.run.url + 'run.zip', text: 'run.zip' }), ' · ',
      h('a', { href: res.run.url + 'job_sheet.md', target: '_blank', text: 'job_sheet.md' }), ' · ',
      h('a', { href: res.run.url + 'report.txt', target: '_blank', text: 'report.txt' })
    ]));
  }
  if (res.report) body.appendChild(h('pre', { class: 'report', text: res.report }));
  if (res.plan && res.plan.refusals && res.plan.refusals.length) {
    res.plan.refusals.forEach(function (r) { body.appendChild(msgLine(Object.assign({}, r, { level: 'error' }))); });
  }
}

function initJobs() {
  $('#job-new').addEventListener('click', newJob);
  $('#job-name').addEventListener('input', function () { state.job.name = this.value.trim(); });
  $('#job-shape').addEventListener('change', function () {
    var j = state.job, s = findShape(this.value);
    j.shape = this.value;
    var presets = s && s.presets ? Object.keys(s.presets) : [];
    j.preset = presets[0] || '';
    j.overrides = {};
    renderPresetOptions(); renderOverrides(); schedulePreview();
  });
  $('#job-preset').addEventListener('change', function () { state.job.preset = this.value; renderOverrides(); schedulePreview(); });
  $('#job-material').addEventListener('change', function () { state.job.material = this.value; updateMaterialHint(); });
  $('#job-flatten').addEventListener('change', function () { state.job.options.flatten = this.value; });
  $('#job-profile').addEventListener('change', function () { state.job.options.profile_mode = this.value; });
  $('#job-notes').addEventListener('input', function () { state.job.notes = this.value; });
  $('#job-save').addEventListener('click', saveJob);
  $('#job-delete').addEventListener('click', askDeleteJob);
  $('#job-plan').addEventListener('click', planJob);
  $('#job-generate').addEventListener('click', generateJob);
  var img = $('#job-preview');
  img.addEventListener('load', function () { previewDone(true); });
  img.addEventListener('error', function () { previewDone(false); });
}

/* ================= БИБЛИОТЕКА ================= */
var TOOL_FIELDS = [
  { k: 'id', l: 'id', t: 'text' },
  { k: 'title', l: 'Название', t: 'text' },
  { k: 'name', l: 'Короткое имя', t: 'text' },
  { k: 'type', l: 'Тип', t: 'select', opts: TOOL_TYPES },
  { k: 'dia', l: 'Ø, мм (dia)', t: 'number', step: 0.001 },
  { k: 'corner_r', l: 'R угла, мм (corner_r)', t: 'number', step: 0.001 },
  { k: 'loc', l: 'Длина режущей части, мм (loc)', t: 'number', step: 0.1 },
  { k: 'shank', l: 'Хвостовик, мм (shank)', t: 'number', step: 0.001 },
  { k: 'rpm', l: 'Обороты (rpm)', t: 'number', step: 1 },
  { k: 'rpm_max', l: 'Обороты макс. (rpm_max)', t: 'number', step: 1 },
  { k: 'feed', l: 'Подача, мм/мин (feed)', t: 'number', step: 1 },
  { k: 'plunge', l: 'Врезание, мм/мин (plunge)', t: 'number', step: 1 },
  { k: 'ramp', l: 'Рампа, мм/мин (ramp)', t: 'number', step: 1 },
  { k: 'feed_contour', l: 'Подача по контуру, мм/мин (feed_contour, необяз.)', t: 'number', step: 1, opt: true },
  { k: 'stepover', l: 'Шаг между проходами (stepover)', t: 'number', step: 0.01 },
  { k: 'doc', l: 'Глубина за проход (doc)', t: 'number', step: 0.1 },
  { k: 'roles', l: 'Роли', t: 'checks', opts: ROLES, span: true },
  { k: 'num', l: 'Номер инструмента (num)', t: 'number', step: 1 },
  { k: 'color', l: 'Цвет (#rrggbb)', t: 'color' },
  { k: 'notes', l: 'Заметки', t: 'textarea', span: true },
  { k: 'hint', l: 'Подсказка в интерфейсе', t: 'textarea', span: true }
];
var MATERIAL_FIELDS = [
  { k: 'id', l: 'id', t: 'text' },
  { k: 'title', l: 'Название', t: 'text' },
  { k: 'janka', l: 'Твёрдость Янка (janka, пусто = нет)', t: 'number', step: 1, nullable: true },
  { k: 'feed_scale', l: 'Коэффициент подачи (feed_scale)', t: 'number', step: 0.01 },
  { k: 'rpm', l: 'Обороты (rpm)', t: 'number', step: 1 },
  { k: 'dial', l: 'Положение диска Makita (dial)', t: 'numtext' },
  { k: 'reference', l: 'Эталонный материал', t: 'bool' },
  { k: 'notes', l: 'Заметки', t: 'textarea', span: true },
  { k: 'hint', l: 'Подсказка в интерфейсе', t: 'textarea', span: true }
];

function buildForm(fields, rec) {
  var inputs = {};
  var grid = h('div', { class: 'form-grid' });
  fields.forEach(function (f) {
    var v = rec ? rec[f.k] : undefined, ctl;
    var str = (v === null || v === undefined) ? '' : String(v);
    switch (f.t) {
      case 'number': ctl = h('input', { type: 'number', step: f.step || 'any', value: str }); break;
      case 'select':
        ctl = h('select', {}, f.opts.map(function (o) { return h('option', { value: o, text: o }); }));
        if (str && f.opts.indexOf(str) < 0) ctl.appendChild(h('option', { value: str, text: str + ' (?)' }));
        ctl.value = str || f.opts[0];
        break;
      case 'checks':
        ctl = h('div', { class: 'checks' }, f.opts.map(function (o) {
          return h('label', { class: 'chk' }, [h('input', { type: 'checkbox', value: o, checked: Array.isArray(v) && v.indexOf(o) >= 0 }), o]);
        }));
        break;
      case 'bool': ctl = h('input', { type: 'checkbox', checked: !!v }); break;
      case 'textarea': ctl = h('textarea', { rows: 2, value: str }); break;
      case 'color': {
        var sw = h('span', { class: 'swatch', style: 'background:' + (str || 'transparent') });
        var inp = h('input', { type: 'text', value: str, placeholder: '#c08040', oninput: function () { sw.style.background = inp.value || 'transparent'; } });
        ctl = h('span', { class: 'color-wrap' }, [sw, inp]);
        ctl._input = inp;
        break;
      }
      default: ctl = h('input', { type: 'text', value: str });
    }
    inputs[f.k] = ctl;
    grid.appendChild(h('label', { class: f.span ? 'span2' : '' }, [h('span', { class: 'lbl', text: f.l }), ctl]));
  });
  function read() {
    var out = {};
    fields.forEach(function (f) {
      var c = inputs[f.k], s;
      switch (f.t) {
        case 'number':
          s = c.value.trim();
          if (s === '') { if (f.nullable) out[f.k] = null; else if (!f.opt) out[f.k] = null; }
          else out[f.k] = Number(s);
          break;
        case 'checks': out[f.k] = $all('input', c).filter(function (i) { return i.checked; }).map(function (i) { return i.value; }); break;
        case 'bool': out[f.k] = c.checked; break;
        case 'color': out[f.k] = c._input.value.trim(); break;
        case 'numtext': s = c.value.trim(); out[f.k] = (s !== '' && isFinite(Number(s))) ? Number(s) : s; break;
        default: out[f.k] = c.value.trim();
      }
    });
    return out;
  }
  return { el: grid, read: read };
}

/* Секция библиотеки: kind = 'tools' | 'materials' */
var LIB = {
  tools: { fields: TOOL_FIELDS, formId: '#tool-form', bodyId: '#tools-body', noun: 'фрезу', title: 'Фреза', endpoint: '/api/library/tools', editing: null },
  materials: { fields: MATERIAL_FIELDS, formId: '#material-form', bodyId: '#materials-body', noun: 'материал', title: 'Материал', endpoint: '/api/library/materials', editing: null }
};
function renderLibrary() {
  var tb = clear($('#tools-body'));
  state.library.tools.forEach(function (t) {
    tb.appendChild(h('tr', { class: 'click' + (LIB.tools.editing === t.id ? ' sel' : ''), onclick: function () { openLibForm('tools', t); } }, [
      h('td', {}, [h('span', { class: 'swatch', style: 'background:' + (t.color || 'transparent') }), t.id]),
      h('td', { text: fmt(t.title) }), h('td', { text: fmt(t.type) }), h('td', { text: num(t.dia) }), h('td', { text: num(t.corner_r) }),
      h('td', { text: num(t.loc) }), h('td', { text: Array.isArray(t.roles) ? t.roles.join(', ') : '' }), h('td', { text: num(t.rpm) }), h('td', { text: num(t.feed) })
    ]));
  });
  if (!state.library.tools.length) tb.appendChild(h('tr', {}, h('td', { colspan: 9, class: 'muted', text: 'Фрез нет' })));
  var mb = clear($('#materials-body'));
  state.library.materials.forEach(function (m) {
    mb.appendChild(h('tr', { class: 'click' + (LIB.materials.editing === m.id ? ' sel' : ''), onclick: function () { openLibForm('materials', m); } }, [
      h('td', { text: m.id }), h('td', { text: fmt(m.title) }), h('td', { text: num(m.janka) }), h('td', { text: num(m.feed_scale) }),
      h('td', { text: num(m.rpm) }), h('td', { text: fmt(m.dial) }),
      h('td', {}, h('input', { type: 'checkbox', checked: !!m.reference, disabled: true }))
    ]));
  });
  if (!state.library.materials.length) mb.appendChild(h('tr', {}, h('td', { colspan: 7, class: 'muted', text: 'Материалов нет' })));
  var ta = $('#machine-json');
  if (document.activeElement !== ta) ta.value = JSON.stringify(state.library.machine, null, 2);
}
function openLibForm(kind, rec) {
  var L = LIB[kind];
  L.editing = rec ? rec.id : null;
  var box = clear($(L.formId));
  box.hidden = false;
  var form = buildForm(L.fields, rec);
  var errNode = h('div', { class: 'errline', hidden: true });
  var confirmBox = h('div', { class: 'confirm', hidden: true });
  var status = h('span', { class: 'status' });
  box.appendChild(h('h3', { text: rec ? L.title + ' ' + rec.id : 'Новая запись' }));
  box.appendChild(form.el);
  var btnSave = h('button', { type: 'button', class: 'btn primary', text: 'Сохранить' });
  var btnDel = h('button', { type: 'button', class: 'btn danger', text: 'Удалить', disabled: !rec });
  var btnClose = h('button', { type: 'button', class: 'btn', text: 'Закрыть' });
  box.appendChild(h('div', { class: 'btns' }, [btnSave, btnDel, btnClose, status]));
  box.appendChild(confirmBox);
  box.appendChild(errNode);
  function busy(on, text) { btnSave.disabled = on; btnDel.disabled = on || !rec; btnClose.disabled = on; clear(status); if (text) status.appendChild(spinner(text)); }
  btnSave.addEventListener('click', async function () {
    setErr(errNode, '');
    var data = Object.assign({}, rec || {}, form.read());
    if (!data.id) { setErr(errNode, 'Нужен id'); return; }
    busy(true, 'Сохранение…');
    try {
      var r = await api('POST', L.endpoint, data);
      if (!r || r.ok === false) throw new Error((r && r.errors || []).join('\n') || 'сервер отказал');
      L.editing = data.id;
      await loadLibrary();
      var fresh = kind === 'tools' ? findTool(data.id) : findMaterial(data.id);
      openLibForm(kind, fresh || data);
    } catch (e) {
      setErr(errNode, e.message);
      busy(false);
    }
  });
  btnDel.addEventListener('click', function () {
    clear(confirmBox); confirmBox.hidden = false;
    confirmBox.appendChild(document.createTextNode('Точно удалить ' + L.noun + ' «' + rec.id + '»?'));
    confirmBox.appendChild(h('button', { type: 'button', class: 'btn small danger', text: 'Да', onclick: async function () {
      confirmBox.hidden = true; setErr(errNode, ''); busy(true, 'Удаление…');
      try {
        var r = await api('DELETE', L.endpoint + '/' + enc(rec.id));
        if (!r || r.ok === false) throw new Error((r && r.errors || []).join('\n') || 'сервер отказал');
        L.editing = null;
        box.hidden = true;
        await loadLibrary();
      } catch (e) {
        setErr(errNode, e.message);
        busy(false);
      }
    } }));
    confirmBox.appendChild(h('button', { type: 'button', class: 'btn small', text: 'Нет', onclick: function () { confirmBox.hidden = true; } }));
  });
  btnClose.addEventListener('click', function () { L.editing = null; box.hidden = true; renderLibrary(); });
  renderLibrary();
}
async function saveMachine() {
  var errNode = $('#machine-error'), status = clear($('#machine-status'));
  setErr(errNode, '');
  var obj;
  try { obj = JSON.parse($('#machine-json').value); } catch (e) { setErr(errNode, 'JSON не разбирается: ' + e.message); return; }
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) { setErr(errNode, 'Ожидается JSON-объект'); return; }
  $('#machine-save').disabled = true;
  status.appendChild(spinner('Сохранение…'));
  try {
    var r = await api('POST', '/api/library/machine', obj);
    if (!r || r.ok === false) throw new Error((r && r.errors || []).join('\n') || 'сервер отказал');
    state.library.machine = obj;
    clear(status).textContent = 'Сохранено';
  } catch (e) {
    setErr(errNode, e.message);
    clear(status);
  } finally {
    $('#machine-save').disabled = false;
  }
}
function initLibrary() {
  $('#tool-add').addEventListener('click', function () { openLibForm('tools', null); });
  $('#material-add').addEventListener('click', function () { openLibForm('materials', null); });
  $('#machine-save').addEventListener('click', saveMachine);
}

/* ================= ПРОГОНЫ ================= */
async function loadRuns() {
  try {
    state.runs = await api('GET', '/api/runs') || [];
    setErr($('#runs-error'), '');
  } catch (e) {
    setErr($('#runs-error'), 'Список прогонов не загружен: ' + e.message);
  }
  renderRuns();
}
function renderRuns() {
  var tb = clear($('#runs-body'));
  if (!state.runs.length) { tb.appendChild(h('tr', {}, h('td', { colspan: 5, class: 'muted', text: 'Прогонов нет' }))); return; }
  state.runs.forEach(function (r) {
    tb.appendChild(h('tr', { class: 'click', onclick: function () { openRun(r); } }, [
      h('td', { text: r.job }), h('td', { class: 'mono', text: r.stamp }),
      h('td', { text: [r.shape, r.preset].filter(Boolean).join(' / ') }),
      h('td', { class: r.ok ? 'verdict-ok' : 'verdict-bad', style: 'white-space:normal', text: r.verdict || (r.ok ? 'OK' : '—') }),
      h('td', { text: typeof r.seconds === 'number' ? Math.round(r.seconds) + ' с' : '' })
    ]));
  });
}
async function openRun(r) {
  var card = $('#run-detail'), body = clear($('#run-body'));
  card.hidden = false;
  setErr($('#run-error'), '');
  setErr($('#viewer-error'), '');
  $('#run-title').textContent = r.job + ' · ' + r.stamp;
  var url = r.url;
  body.appendChild(h('div', { class: 'banner ' + (r.ok ? 'ok' : 'bad'), text: r.ok ? (r.verdict || 'OK') : 'НА СТАНОК НЕ НЕСТИ\n' + (r.verdict || '') }));
  var meta = [[r.shape, r.preset].filter(Boolean).join(' / ')];
  if (typeof r.seconds === 'number') meta.push(Math.round(r.seconds) + ' с');
  body.appendChild(h('div', { class: 'muted', text: meta.filter(Boolean).join(' · ') }));
  if (Array.isArray(r.files) && r.files.length) {
    body.appendChild(h('h3', { text: 'Файлы G-code' }));
    body.appendChild(h('ul', { class: 'files' }, r.files.map(function (f) {
      return h('li', {}, [h('a', { href: url + 'nc/' + enc(f.name), download: f.name, text: f.name }), ' ',
        h('span', { class: 'muted', text: [kb(f.size), minutes(f.minutes)].filter(Boolean).join(', ') })]);
    })));
  }
  body.appendChild(h('div', { class: 'kv' }, [
    h('a', { href: url + 'run.zip', text: 'run.zip' }), ' · ',
    h('a', { href: url + 'job_sheet.md', target: '_blank', text: 'job_sheet.md' }), ' · ',
    h('a', { href: url + 'report.txt', target: '_blank', text: 'report.txt' })
  ]));
  body.appendChild(h('div', { class: 'preview' }, h('img', { src: url + 'preview.svg', alt: 'Вид сверху' })));
  var pre = h('pre', { class: 'report', text: 'Загрузка отчёта…' });
  body.appendChild(pre);
  fetchText(url + 'report.txt').then(function (t) { pre.textContent = t; }, function (e) { pre.textContent = ''; setErr($('#run-error'), 'Отчёт не загружен: ' + e.message); });

  var vw = $('#run-viewer');
  vw.hidden = !r.has_stl;
  if (r.has_stl) await showRunViewer(r);
}
async function showRunViewer(r) {
  var errNode = $('#viewer-error');
  var layersBox = clear($('#run-layers'));
  var canvas = $('#run-canvas');
  if (!state.viewer) {
    try { state.viewer = window.BoardcamViewer(canvas); }
    catch (e) { setErr(errNode, '3-D просмотр недоступен: ' + e.message); return; }
  }
  var v = state.viewer;
  v.clear();
  var layers = [['stl', 'Модель (STL)'], ['blank', 'Заготовка'], ['origin', 'Ноль X0Y0']];
  if (r.has_heightmap) layers.splice(1, 0, ['machined', 'Обработанная поверхность']);
  layers.forEach(function (l) {
    var cb = h('input', { type: 'checkbox', checked: true, onchange: function () { v.setLayerVisible(l[0], cb.checked); } });
    v.setLayerVisible(l[0], true);
    layersBox.appendChild(h('label', { class: 'chk' }, [cb, l[1]]));
  });
  var st = spinner('Загрузка модели…');
  layersBox.appendChild(st);
  var problems = [];
  try {
    var d = await api('GET', '/api/runs/' + enc(r.job) + '/' + enc(r.stamp));
    var blank = d && d.design && d.design.blank;
    if (blank && typeof blank.size_x === 'number') v.setBlank(blank.size_x, blank.size_y, blank.thick || (d.design && d.design.thick) || 0);
  } catch (e) { problems.push('design.json: ' + e.message); }
  try { v.loadStl(await fetchBuffer(r.url + 'model.stl')); }
  catch (e) { problems.push('model.stl: ' + e.message); }
  if (r.has_heightmap) {
    try { v.loadHeightmap(await fetchBuffer(r.url + 'machined.bin')); }
    catch (e) { problems.push('machined.bin: ' + e.message); }
  }
  st.remove();
  setErr(errNode, problems.join('\n'));
}
function initRuns() {
  $('#runs-refresh').addEventListener('click', loadRuns);
}

/* ---------- торцовка ---------- */
function loadSurfaceTools() {
  var sel = $('#surf-tool');
  if (!sel) return;
  clear(sel);
  var tools = (state.library && state.library.tools) || [];
  tools.forEach(function (t) {
    var isSurf = (t.roles || []).indexOf('surface') >= 0;
    var opt = h('option', { value: t.id }, t.name + ' (D' + t.dia + ' мм' + (isSurf ? ' — торцовочная' : '') + ')');
    if (isSurf) opt.selected = true;
    sel.appendChild(opt);
  });
}

function initSurface() {
  var btn = $('#surf-generate');
  if (!btn) return;
  btn.addEventListener('click', async function () {
    var err = $('#surf-error');
    var status = $('#surf-status');
    var resCard = $('#surf-result-card');
    setErr(err, '');
    status.textContent = 'Генерация траектории...';
    btn.disabled = true;
    try {
      var payload = {
        width: parseFloat($('#surf-width').value) || 200,
        height: parseFloat($('#surf-height').value) || 300,
        depth: parseFloat($('#surf-depth').value) || 1.5,
        step: parseFloat($('#surf-step').value) || 0.5,
        overlap: parseFloat($('#surf-overlap').value) || 0.4,
        tool: $('#surf-tool').value
      };
      var res = await api('POST', '/api/surface', payload);
      status.textContent = 'Готово!';
      resCard.hidden = false;
      $('#surf-summary').textContent = 'Фреза: ' + res.tool + ' | Строк G-code: ' + res.lines + ' (' + kb(res.size_bytes) + ')';
      $('#surf-preview').textContent = res.preview + '\n...';
      $('#surf-download').setAttribute('href', res.download_url);
    } catch (e) {
      setErr(err, 'Ошибка генерации: ' + e.message);
      status.textContent = '';
    } finally {
      btn.disabled = false;
    }
  });
}

/* ---------- старт ---------- */
async function init() {
  $all('.tab').forEach(function (b) { b.addEventListener('click', function () { showTab(b.getAttribute('data-tab')); }); });
  initJobs(); initLibrary(); initRuns(); initSurface();
  await Promise.all([loadDoctor(), loadShapes(), loadLibrary()]);
  loadSurfaceTools();
  await loadJobs();
}
document.addEventListener('DOMContentLoaded', function () {
  init().catch(function (e) { setErr($('#global-error'), 'Ошибка запуска: ' + e.message); });
});
})();
