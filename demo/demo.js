/* Demo behaviour for the static build. Loaded AFTER the dashboard script; it replaces the few parts that would talk to a
   real Flexie with scripted, clearly-labelled sample behaviour. Nothing in this file makes a network request. */
(function () {
  'use strict';

  var tools = document.querySelector('.tools');
  if (tools) {
    var pill = document.createElement('div');
    pill.className = 'demo-pill';
    pill.textContent = 'Demo with sample data';
    pill.title = 'Nothing on this page comes from a real computer';
    tools.insertBefore(pill, tools.firstChild);
  }

  var side = document.querySelector('.sidebar'), status = document.querySelector('.sysok');
  if (side && status) {
    var back = document.createElement('a');
    back.className = 'demo-back';
    back.href = 'index.html';
    back.textContent = '\u2190 About Flexie';
    side.insertBefore(back, status);
  }

  // "Check connection" must not try to reach a local server that does not exist here.
  window.pollApi = function () { apiOk = true; apiMs = 12; renderServices(); renderHealth(); return Promise.resolve(); };

  var lastReply = '';

  function learn(text) {
    var t = text.trim(), m;
    var fact = null;
    if ((m = /\bcall me ([A-Za-z][A-Za-z.' -]{0,24})/i.exec(t)) || (m = /\bmy name is ([A-Za-z][A-Za-z.' -]{0,24})/i.exec(t))) fact = 'Name is ' + m[1].trim();
    else if ((m = /\bi prefer ([^.,;!?]{3,60})/i.exec(t))) fact = 'Prefers ' + m[1].trim();
    else if ((m = /\bfrom now on[, ]+([^.;!?]{3,70})/i.exec(t))) fact = 'Standing instruction: ' + m[1].trim();
    else if ((m = /\bi (?:like|love) ([^.,;!?]{3,50})/i.exec(t))) fact = 'Likes ' + m[1].trim();
    if (!fact) return null;
    prefs = prefs.filter(function (p) { return p.text.toLowerCase() !== fact.toLowerCase(); });
    prefs.unshift({ id: Date.now(), text: fact, updated: Date.now() / 1000 });
    renderPrefs();
    return "Got it. I'll remember: " + fact.charAt(0).toLowerCase() + fact.slice(1) + '. (Demo: kept only in this tab.)';
  }

  function reply(text) {
    var t = text.toLowerCase(), now = new Date(), got = learn(text);
    if (got) return got;
    if (/say that again|repeat that|what did you say/.test(t)) return lastReply || 'I have not said anything yet.';
    if (/\btime\b/.test(t) && /what|tell/.test(t)) return "It's " + now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) + '.';
    if (/\bdate\b|what day/.test(t)) return 'Today is ' + now.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }) + '.';
    if (/weather/.test(t)) return 'In this demo it is 31 degrees and humid, with a chance of evening showers. The real Flexie looks it up live.';
    if (/volume|louder|quieter/.test(t)) return 'Volume is 60 percent. (Demo: nothing on your computer was changed.)';
    if (/(take|capture).*(screenshot|screen shot)|^screenshot$/.test(t)) {
      onContext([{ kind: 'screenshot', label: 'screenshot_1195.png', age: 0 }, { kind: 'project', label: 'calendar-app', age: 600 }]);
      return 'I took a screenshot and saved it as screenshot_1195.png. Say "open that screenshot" to see it.';
    }
    if (/open (that|it|the) screenshot|^open it$/.test(t)) return 'Opened screenshot_1195.png. (Demo)';
    if (/undo|take that back/.test(t)) return 'Undid the last change. (Demo)';
    if (/what can you do|^help$|capabilit/.test(t)) return 'I can control a Windows PC by voice or text: volume, apps, files, screenshots, mail, browser tabs and reminders. I also learn your preferences. Look through Settings to see the options.';
    if (/preferences|what do you (know|remember)/.test(t)) return prefs.length ? 'I remember: ' + prefs.slice(0, 4).map(function (p) { return p.text; }).join('; ') + '.' : 'I have not learned any preferences yet. Try "I prefer short answers".';
    return 'This is a demo, so I can only give sample replies. The real Flexie answers with your own AI provider.';
  }

  window.sendRaw = function (message) {
    if (/^(mode |SAVE_SETTINGS:|DELETE_PREF:|CLEAR_PREFS|SET_|GET_)/.test(message)) return true;     // handled on the page itself
    if (message === 'wake up') {
      setState('LISTENING');
      setTimeout(function () { setState('IDLE'); }, 1600);
      return true;
    }
    setState('PROCESSING');
    setTimeout(function () {
      lastReply = reply(message);
      setState('SPEAKING');
      onSay(lastReply);
      setTimeout(function () { setState('IDLE'); }, 2600);
    }, 800);
    return true;
  };
})();
