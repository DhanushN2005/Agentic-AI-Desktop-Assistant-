/* Orb panel for the Flexie dashboard (served same-origin from /static/).
 *
 * Adds an "Orb" tab that opens a full-window overlay with the 3D hand-gesture orb.
 * The orb itself (orb.js, ~600 KB) is loaded lazily on first open; hand tracking
 * (orb-gestures.js + MediaPipe) is loaded only when gestures are switched on.
 *
 * It is driven by the dashboard's own authenticated WebSocket: the dashboard calls
 *   FlexieOrbPanel.onMessage(tag, value)  for every STATE:/SAY:/PANEL: message
 *   FlexieOrbPanel.onConnection(online)   when the socket goes up or down
 * and the orb's command bar reuses the dashboard's global send().
 */
(function () {
  'use strict';

  var stage = null;      // overlay element
  var loading = null;    // Promise while orb.js loads
  var mounted = false;
  var lastState = 'IDLE';
  var lastSpeech = '';
  var online = false;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('failed to load ' + src)); };
      document.head.appendChild(s);
    });
  }

  // Which orb to load: classic (default) or the black hole. ?orb=blackhole switches and is remembered; ?orb=classic goes back.
  function orbScript() {
    var style = '';
    try {
      var q = new URLSearchParams(location.search).get('orb');
      if (q === 'blackhole' || q === 'classic') localStorage.setItem('flexieOrbStyle', q);
      style = localStorage.getItem('flexieOrbStyle') || '';
    } catch (e) { /* storage blocked: stay on classic */ }
    return style === 'blackhole' ? '/static/orb-blackhole.js' : '/static/orb.js';
  }

  function ensureStage() {
    if (stage) return stage;
    stage = document.createElement('div');
    stage.id = 'orbStage';
    stage.setAttribute('role', 'dialog');
    stage.setAttribute('aria-label', 'Flexie orb');
    stage.style.cssText = 'position:fixed;inset:0;z-index:5000;display:none;background:#000;';
    document.body.appendChild(stage);
    return stage;
  }

  function ensureOrb() {
    if (mounted) return Promise.resolve();
    if (loading) return loading;
    loading = (window.FlexieOrb ? Promise.resolve() : loadScript(orbScript())).then(function () {
      window.FlexieOrb.mount(ensureStage(), {
        onCommand: function (text) { if (typeof window.send === 'function') window.send(text); },
        onClose: close
      });
      mounted = true;
      window.FlexieOrb.setConnected(online);
      window.FlexieOrb.setState(lastState);
      if (lastSpeech) window.FlexieOrb.setSpeech(lastSpeech);
    }).catch(function (err) {
      loading = null;
      if (typeof window.toast === 'function') window.toast('Orb', 'Could not load the orb: ' + err.message, 'error', 6000);
    });
    return loading;
  }

  function open() {
    ensureStage().style.display = 'block';
    if (location.hash !== '#orb') {
      try { history.replaceState(null, '', '#orb'); } catch (e) { /* ignore */ }
    }
    return ensureOrb();
  }

  function close() {
    if (stage) stage.style.display = 'none';
    if (window.FlexieOrb && mounted) window.FlexieOrb.setGestures(false);   // release the camera
    if (location.hash === '#orb') {
      try { history.replaceState(null, '', location.pathname); } catch (e) { /* ignore */ }
    }
  }

  window.FlexieOrbPanel = {
    open: open,
    close: close,
    onMessage: function (tag, value) {
      if (tag === 'STATE') {
        lastState = String(value || '').toUpperCase();
        if (mounted) window.FlexieOrb.setState(lastState);
      } else if (tag === 'SAY') {
        lastSpeech = String(value || '');
        if (mounted) window.FlexieOrb.setSpeech(lastSpeech);
      } else if (tag === 'PANEL') {
        var v = String(value || '').trim().toLowerCase();
        if (v === 'orb') open();
        else if (v === 'close') close();
      }
    },
    onConnection: function (isOnline) {
      online = !!isOnline;
      if (mounted) window.FlexieOrb.setConnected(online);
    }
  };

  function addTab() {
    var bar = document.querySelector('.tab-bar');
    if (!bar || document.getElementById('orbTab')) return;
    var btn = document.createElement('button');
    btn.className = 'tab';
    btn.id = 'orbTab';
    btn.type = 'button';
    var icon = document.createElement('i');
    icon.className = 'fa fa-circle-notch';
    btn.appendChild(icon);
    btn.appendChild(document.createTextNode(' Orb'));
    btn.addEventListener('click', function () { open(); });
    bar.appendChild(btn);
  }

  addTab();
  if (location.hash === '#orb') open();
  window.addEventListener('hashchange', function () {
    if (location.hash === '#orb') open();
  });
})();
