/* Flexie dashboard: panels that replace what the old desktop (Qt) HUD offered.
 *
 *   - approval modal   (server: APPROVAL_REQUEST / APPROVAL_RESOLVED)
 *   - API keys + models modal  (client: GET_SETTINGS, SAVE_SETTINGS; server: SETTINGS, SETTINGS_SAVED)
 *   - mail badge       (server: MAIL_COUNT / MAIL_INBOX)
 *   - QUIT notice
 *
 * Loaded by web_ui.html after its own script. It uses that page's sendRaw() (authenticated
 * WebSocket) and toast(). Everything is built with textContent, never innerHTML, so server text
 * can never inject markup. API keys are only ever typed into password inputs, sent once over the
 * authenticated socket, cleared immediately, and are never logged or shown again.
 */
(function () {
  'use strict';

  var MAIL_POLL_MS = 120000;
  var mailTimer = null;
  var api = {};

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function send(msg) {
    return typeof window.sendRaw === 'function' ? window.sendRaw(msg) : false;
  }
  function note(title, msg, type) {
    if (typeof window.toast === 'function') window.toast(title, msg || '', type || 'info', 4500);
  }
  function overlay(onBackdrop) {
    var o = el('div', 'fx-overlay');
    o.addEventListener('mousedown', function (e) { if (e.target === o && onBackdrop) onBackdrop(); });
    document.body.appendChild(o);
    return o;
  }

  /* ---------------------------------------------------------------- approvals */
  var approval = { open: false, id: null, overlay: null, levelEl: null, status: null, onKey: null };

  function parseApproval(value) {
    try {
      var d = JSON.parse(value);
      if (d && typeof d === 'object') {
        return { id: d.id ? String(d.id) : null, action: String(d.action || value), level: d.level ? String(d.level) : '' };
      }
    } catch (e) { /* the controller sends the plain command text */ }
    return { id: null, action: String(value), level: '' };
  }

  function closeApproval() {
    if (approval.overlay && approval.overlay.parentNode) approval.overlay.parentNode.removeChild(approval.overlay);
    if (approval.onKey) document.removeEventListener('keydown', approval.onKey, true);
    approval = { open: false, id: null, overlay: null, levelEl: null, status: null, onKey: null };
  }

  function answerApproval(ok) {
    var id = approval.id;
    var cmd = ok ? (id ? 'APPROVE:' + id : 'APPROVE') : (id ? 'REJECT:' + id : 'CANCEL');
    if (!send(cmd)) {
      if (approval.status) approval.status.textContent = 'Not connected: the answer was not sent. Try again.';
      return;
    }
    closeApproval();
  }

  function showApproval(value) {
    var info = parseApproval(value);
    if (approval.open) {
      // The controller and the permission system each announce the same request: keep one modal,
      // and adopt the request id as soon as the JSON form arrives.
      if (info.id && !approval.id) approval.id = info.id;
      if (info.level && approval.levelEl) approval.levelEl.textContent = info.level;
      return;
    }
    var o = overlay(null);
    var box = el('div', 'fx-modal fx-approval');
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-modal', 'true');
    box.appendChild(el('h2', 'fx-title', 'Permission required'));
    box.appendChild(el('p', 'fx-sub', 'Flexie wants to:'));
    box.appendChild(el('pre', 'fx-action', info.action));
    var level = el('div', 'fx-level', info.level);
    box.appendChild(level);
    var status = el('div', 'fx-status', '');
    box.appendChild(status);
    var row = el('div', 'fx-row');
    var reject = el('button', 'fx-btn', 'Reject');
    var approve = el('button', 'fx-btn fx-primary', 'Approve');
    reject.type = approve.type = 'button';
    reject.addEventListener('click', function () { answerApproval(false); });
    approve.addEventListener('click', function () { answerApproval(true); });
    row.appendChild(reject);
    row.appendChild(approve);
    box.appendChild(row);
    o.appendChild(box);
    approval = { open: true, id: info.id, overlay: o, levelEl: level, status: status, onKey: null };
    // Esc means "no": the safe default. Focus starts on Reject for the same reason.
    approval.onKey = function (e) { if (e.key === 'Escape') { e.preventDefault(); answerApproval(false); } };
    document.addEventListener('keydown', approval.onKey, true);
    reject.focus();
  }

  /* ----------------------------------------------------------------- settings */
  var settings = { overlay: null, body: null, status: null, inputs: null, snapshot: null };

  function closeSettings() {
    if (settings.overlay && settings.overlay.parentNode) settings.overlay.parentNode.removeChild(settings.overlay);
    settings = { overlay: null, body: null, status: null, inputs: null, snapshot: null };
  }

  function openSettings() {
    if (settings.overlay) return;
    var o = overlay(closeSettings);
    var box = el('div', 'fx-modal fx-settings');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.appendChild(el('h2', 'fx-title', 'AI provider keys and models'));
    box.appendChild(el('p', 'fx-sub', 'Leave a key empty to keep the saved one. Keys are sent once and never shown again.'));
    var body = el('div', 'fx-body', 'Loading...');
    box.appendChild(body);
    var status = el('div', 'fx-status', '');
    box.appendChild(status);
    var row = el('div', 'fx-row');
    var close = el('button', 'fx-btn', 'Close');
    var save = el('button', 'fx-btn fx-primary', 'Save');
    close.type = save.type = 'button';
    close.addEventListener('click', closeSettings);
    save.addEventListener('click', saveSettings);
    row.appendChild(close);
    row.appendChild(save);
    box.appendChild(row);
    o.appendChild(box);
    settings = { overlay: o, body: body, status: status, inputs: null, snapshot: null };
    if (!send('GET_SETTINGS')) body.textContent = 'Not connected to Flexie.';
  }

  function field(label, input) {
    var wrap = el('label', 'fx-field');
    wrap.appendChild(el('span', 'fx-label', label));
    wrap.appendChild(input);
    return wrap;
  }

  function renderSettings(data) {
    if (!settings.overlay || !data || !Array.isArray(data.providers)) return;
    settings.snapshot = data;
    var body = settings.body;
    body.textContent = '';
    var inputs = { keys: {}, models: {}, active: null, ollamaUrl: null, ollamaModel: null };

    var active = el('select', 'fx-input');
    (data.active_choices || ['auto']).forEach(function (c) {
      var opt = el('option', null, c === 'auto' ? 'auto (fallback chain)' : c);
      opt.value = c;
      if (c === data.active) opt.selected = true;
      active.appendChild(opt);
    });
    inputs.active = active;
    body.appendChild(field('Active provider', active));

    data.providers.forEach(function (p) {
      var card = el('div', 'fx-card');
      card.appendChild(el('div', 'fx-card-title', p.label + (p.has_key ? '  (key saved)' : '  (no key)')));
      var key = el('input', 'fx-input');
      key.type = 'password';
      key.autocomplete = 'new-password';
      key.spellcheck = false;
      key.placeholder = (p.has_key && p.hint ? p.hint + ' (saved). ' : '') + (p.placeholder || '') + ' - leave empty to keep';
      inputs.keys[p.id] = key;
      card.appendChild(field('API key (' + p.env + ')', key));
      var listId = 'fx-models-' + p.id;
      var model = el('input', 'fx-input');
      model.setAttribute('list', listId);
      model.value = p.model || '';
      model.spellcheck = false;
      var dl = el('datalist');
      dl.id = listId;
      (p.models || []).forEach(function (m) { var op = el('option'); op.value = m; dl.appendChild(op); });
      inputs.models[p.id] = model;
      card.appendChild(field('Model', model));
      card.appendChild(dl);
      if (p.help) card.appendChild(el('div', 'fx-help', 'Get a key: ' + p.help));
      body.appendChild(card);
    });

    var oc = el('div', 'fx-card');
    oc.appendChild(el('div', 'fx-card-title', 'Ollama (local)'));
    inputs.ollamaUrl = el('input', 'fx-input');
    inputs.ollamaUrl.value = (data.ollama && data.ollama.url) || '';
    inputs.ollamaModel = el('input', 'fx-input');
    inputs.ollamaModel.value = (data.ollama && data.ollama.model) || '';
    oc.appendChild(field('URL', inputs.ollamaUrl));
    oc.appendChild(field('Model', inputs.ollamaModel));
    body.appendChild(oc);
    settings.inputs = inputs;
  }

  function saveSettings() {
    var i = settings.inputs;
    if (!i) return;
    var payload = { keys: {}, models: {}, active: i.active.value,
                    ollama_url: i.ollamaUrl.value.trim(), ollama_model: i.ollamaModel.value.trim() };
    Object.keys(i.keys).forEach(function (id) {
      var v = i.keys[id].value.trim();
      if (v) payload.keys[id] = v;
      i.keys[id].value = '';            // never keep a key in the page after sending
    });
    Object.keys(i.models).forEach(function (id) { payload.models[id] = i.models[id].value.trim(); });
    if (send('SAVE_SETTINGS:' + JSON.stringify(payload))) {
      settings.status.textContent = 'Saving...';
    } else {
      settings.status.textContent = 'Not connected: nothing was saved.';
    }
  }

  function settingsSaved(value) {
    var r = {};
    try { r = JSON.parse(value) || {}; } catch (e) { /* ignore */ }
    var changed = Number(r.changed) || 0;
    var problems = Array.isArray(r.problems) ? r.problems.slice(0, 5).join('; ') : '';
    if (settings.status) {
      settings.status.textContent = (changed ? 'Saved ' + changed + ' setting(s); brain reloaded.' : 'Nothing was changed.') +
        (problems ? ' Problems: ' + problems : '');
    }
    note('Settings', changed ? 'Saved ' + changed + ' change(s)' : 'No changes saved', problems ? 'warn' : (changed ? 'success' : 'info'));
    if (changed && settings.overlay) send('GET_SETTINGS');   // refresh the "key saved" hints
  }

  /* --------------------------------------------------------------------- mail */
  function setMailBadge(n) {
    var badge = document.getElementById('mailUnreadBadge');
    if (!badge) return;
    n = Number(n);
    if (!isFinite(n) || n < 0) return;
    badge.textContent = String(n);
    badge.style.display = n > 0 ? '' : 'none';
  }
  function mailInbox(value) {
    try {
      var items = JSON.parse(value);
      if (Array.isArray(items)) { setMailBadge(items.length); return; }
    } catch (e) { /* the backend sends a Python list repr: fall back to counting records */ }
    var m = String(value).match(/\{/g);
    if (m) setMailBadge(m.length);
  }

  /* ------------------------------------------------------------------ plumbing */
  function addSettingsButton() {
    if (document.getElementById('fxKeysBtn')) return;
    var chips = document.querySelector('.status-chips');
    if (!chips) return;
    var chip = el('button', 'chip fx-keys-btn', 'Keys');
    chip.id = 'fxKeysBtn';
    chip.type = 'button';
    chip.title = 'AI provider keys and models';
    chip.addEventListener('click', openSettings);
    chips.appendChild(chip);
  }

  api.handle = function (tag, val) {
    switch (tag) {
      case 'APPROVAL_REQUEST': showApproval(val); return true;
      case 'APPROVAL_RESOLVED':
        closeApproval();
        note('Approval', String(val), String(val) === 'approved' ? 'success' : 'info');
        return true;
      case 'SETTINGS':
        try { renderSettings(JSON.parse(val)); } catch (e) { note('Settings', 'Could not read the settings reply', 'error'); }
        return true;
      case 'SETTINGS_SAVED': settingsSaved(val); return true;
      case 'MAIL_COUNT': setMailBadge(String(val).trim()); return true;
      case 'MAIL_INBOX': mailInbox(val); return true;
      case 'QUIT': note('Flexie', 'Flexie is shutting down.', 'warn'); return true;
      default: return false;
    }
  };

  api.onConnected = function () {
    send('MAIL_COUNT');
    if (!mailTimer) {
      mailTimer = setInterval(function () { if (document.visibilityState === 'visible') send('MAIL_COUNT'); }, MAIL_POLL_MS);
    }
  };

  // exposed for tests and for the page itself
  api._parseApproval = parseApproval;
  api.openSettings = openSettings;
  window.FlexiePanels = api;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addSettingsButton);
  else addSettingsButton();
})();
