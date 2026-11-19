/* Flexie "Black Hole" orb - a spinning, gravitationally lensed black hole for the web dashboard.
 *
 * Opt-in drop-in for orb.js: same API (window.FlexieOrb = { mount, destroy, setState, setSpeech,
 * setConnected, setGestures, setStats }). The classic orb is untouched and stays the default.
 *   Use it:  open the dashboard with  ?orb=blackhole   (remembered), back to classic with  ?orb=classic
 *
 * One WebGL fragment shader draws everything (no libraries):
 *   - an event horizon (pure black) with a thin photon ring
 *   - a spinning accretion disk: inner gas orbits faster than the outer (Keplerian), turbulent swirls,
 *     one side brighter (relativistic beaming)
 *   - the disk's far side lensed into an arch over and under the hole (the "Interstellar" look)
 *   - a starfield bent around the hole
 * Flexie's state drives it: idle = slow blue drift, listening = green + ripples, thinking = amber and spinning
 * 4x faster, speaking = magenta with the disk pulsing to the voice, sleep = dim, error = red.
 */
(function () {
  'use strict';

  var VERT = 'attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }';
  var FRAG = [
    'precision highp float;',
    'uniform vec2 uRes; uniform float uT, uSpin, uPulse, uBright, uRipple; uniform vec3 uC1, uC2; uniform vec2 uM;',
    'float h(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }',
    'float n(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);',
    '  return mix(mix(h(i),h(i+vec2(1.0,0.0)),f.x), mix(h(i+vec2(0.0,1.0)),h(i+vec2(1.0,1.0)),f.x), f.y); }',
    'float fbm(vec2 p){ float a=0.5, s=0.0; for(int i=0;i<4;i++){ s+=a*n(p); p=p*2.03+vec2(1.7,9.2); a*=0.5; } return s; }',
    'vec3 ramp(float x){',                                  // x: 0 = cold outer edge .. 1 = white-hot inner edge
    '  vec3 cold = mix(uC2*0.25, uC2, smoothstep(0.0,0.4,x));',
    '  vec3 hot  = mix(uC1, vec3(1.0,0.97,0.92), smoothstep(0.62,1.0,x));',
    '  return mix(cold, hot, smoothstep(0.3,0.75,x)); }',
    'vec3 stars(vec2 p){ vec2 g=floor(p*70.0); float r=h(g); vec2 f=fract(p*70.0)-0.5;',
    '  float d=length(f-(vec2(h(g+3.0),h(g+7.0))-0.5)*0.6);',
    '  return vec3(step(0.985,r)*smoothstep(0.14,0.0,d)) * (0.5+0.5*h(g+11.0)) * vec3(0.8,0.9,1.0); }',
    // disk emission at disk-plane position q
    'float disk(vec2 q, float rin, float rout, out float temp){',
    '  float rr=length(q); float a=atan(q.y,q.x);',
    '  float ph = a - uT*uSpin*(0.22/(rr+0.04));',          // inner gas laps the outer: differential rotation
    '  float t = 0.6*fbm(vec2(cos(ph)*2.2 + rr*13.0, sin(ph)*2.2)) + 0.4*n(vec2(rr*38.0 - uT*0.15, 3.0));',   // cos/sin: no seam where the angle wraps
    '  float band = smoothstep(rin, rin+0.025, rr) * smoothstep(rout, rout-0.2, rr);',
    '  temp = clamp(1.0-(rr-rin)/(rout-rin), 0.0, 1.0);',
    '  float beam = 0.55 + 0.8*smoothstep(0.7,-0.7, q.x/max(rr,1e-3));',
    '  return band * (0.25 + 1.5*t) * (0.18/(rr+0.04)) * beam; }',
    'void main(){',
    '  vec2 uv = (gl_FragCoord.xy - 0.5*uRes)/uRes.y - uM*0.012;',
    '  float rs = 0.095; float r = length(uv); vec2 dir = uv/max(r,1e-4);',
    '  vec3 col = vec3(0.0);',
    // lensed stars, swallowed inside the horizon
    '  vec2 sp = uv - dir*(rs*rs*2.6/max(r, rs*0.8)) + vec2(uT*0.002, 0.0);',
    '  col += stars(sp) * smoothstep(rs*0.95, rs*1.6, r);',
    // ambient glow
    '  col += uC2 * exp(-max(r-rs,0.0)/(rs*2.6)) * 0.30 * uBright;',
    // the disk (seen almost edge-on) and its lensed arch
    '  float tmp; float rin=0.12, rout=0.46;',
    '  float Id = disk(vec2(uv.x, uv.y/0.26), rin, rout, tmp);',
    '  vec3 diskCol = ramp(tmp) * Id * (1.0 + 0.9*uPulse) * uBright;',
    '  float rr2 = rin + (r - rs*1.02)*1.7; float tmp2;',
    '  vec2 q2 = dir*rr2;',
    '  float Ia = disk(vec2(q2.x, q2.y), rin, rout, tmp2);',
    '  float arch = smoothstep(rs*1.0, rs*1.12, r) * smoothstep(rs*2.7, rs*1.5, r);',
    '  float top = smoothstep(-0.015, 0.05, uv.y);',
    '  vec3 archCol = ramp(tmp2*0.9+0.1) * Ia * arch * (top + 0.4*(1.0-top)) * (1.0+0.9*uPulse) * uBright;',
    '  float back = smoothstep(-0.004, 0.004, uv.y);',          // far half of the disk is hidden by the hole
    '  col += archCol + diskCol*back;',
    '  float ring = exp(-pow((r-rs*1.07)/(rs*(0.045+0.03*uPulse)), 2.0));',
    '  col += mix(uC1, vec3(1.0), 0.6) * ring * 1.5 * uBright;',
    '  float hole = 1.0 - smoothstep(rs*0.985, rs*1.0, r);',
    '  col = mix(col, vec3(0.0), hole);',
    '  col += diskCol*(1.0-back);',                             // near half passes in front of the hole
    // listening ripples
    '  for(int k=0;k<3;k++){ float f=fract(uT*0.45 + float(k)/3.0); float rk=rs*1.5+f*0.42;',
    '    col += uC1 * exp(-pow((r-rk)/0.004,2.0)) * (1.0-f) * uRipple * 0.9; }',
    '  col *= 1.0 - 0.55*smoothstep(0.35, 0.95, r);',            // vignette
    '  col = 1.0 - exp(-col*1.25);',
    '  gl_FragColor = vec4(pow(col, vec3(0.95)), 1.0); }'
  ].join('\n');

  var PRESETS = {
    IDLE:       { c1: [0.35, 0.72, 1.00], c2: [0.10, 0.28, 0.85], spin: 0.60, bright: 0.85, ripple: 0, label: 'STANDBY',    sub: 'FLEXIE IS READY' },
    LISTENING:  { c1: [0.30, 1.00, 0.78], c2: [0.05, 0.65, 0.55], spin: 1.00, bright: 1.00, ripple: 1, label: 'LISTENING',  sub: 'FLEXIE IS LISTENING' },
    PROCESSING: { c1: [1.00, 0.78, 0.25], c2: [0.95, 0.35, 0.05], spin: 3.50, bright: 1.10, ripple: 0, label: 'THINKING',   sub: 'FLEXIE IS THINKING' },
    SPEAKING:   { c1: [1.00, 0.25, 0.70], c2: [0.75, 0.05, 0.45], spin: 1.60, bright: 1.10, ripple: 0, label: 'SPEAKING',   sub: 'FLEXIE IS SPEAKING' },
    SLEEP:      { c1: [0.30, 0.45, 0.80], c2: [0.08, 0.14, 0.40], spin: 0.20, bright: 0.40, ripple: 0, label: 'ASLEEP',     sub: 'SAY "HEY FLEXIE" TO WAKE' },
    ERROR:      { c1: [1.00, 0.35, 0.30], c2: [0.70, 0.05, 0.05], spin: 0.80, bright: 0.95, ripple: 0, label: 'ERROR',      sub: 'SOMETHING WENT WRONG' }
  };
  PRESETS.WAKE = PRESETS.LISTENING; PRESETS.MINIMIZED = PRESETS.SLEEP; PRESETS.ALERT = PRESETS.ERROR;
  PRESETS.SUCCESS = PRESETS.IDLE; PRESETS.WARNING = PRESETS.PROCESSING;

  var root = null, canvas = null, gl = null, prog = null, loc = {}, raf = 0, el = {}, keyHandler = null, resizeHandler = null;
  var target = PRESETS.IDLE, stateName = 'IDLE';
  var cur = { c1: PRESETS.IDLE.c1.slice(), c2: PRESETS.IDLE.c2.slice(), spin: 0.6, bright: 0.85, ripple: 0, pulse: 0 };
  var mouse = [0, 0], opts = {}, t0 = 0, spinPhase = 0, lastFrame = 0;

  function make(tag, css, text) {
    var n = document.createElement(tag);
    if (css) n.style.cssText = css;
    if (text != null) n.textContent = text;
    return n;
  }

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader error');
    return s;
  }

  function resize() {
    if (!canvas || !root) return;
    var scale = Math.min(window.devicePixelRatio || 1, 1.5) * 0.85;   // a little under native: the picture is soft anyway
    var w = Math.max(2, Math.floor(root.clientWidth * scale)), h = Math.max(2, Math.floor(root.clientHeight * scale));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    if (gl) gl.viewport(0, 0, canvas.width, canvas.height);
  }

  // offsetParent is null for position:fixed overlays, so test the size instead (display:none gives 0)
  function visible() { return !!root && root.clientWidth > 0 && root.clientHeight > 0; }

  function lerp(a, b, k) { return a + (b - a) * k; }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (!root || !visible()) return;          // hidden (overlay closed): don't burn the GPU
    var dt = Math.min(0.05, (now - (lastFrame || now)) / 1000); lastFrame = now;
    var k = 1 - Math.pow(0.001, dt);                          // smooth approach to the target look
    for (var i = 0; i < 3; i++) { cur.c1[i] = lerp(cur.c1[i], target.c1[i], k); cur.c2[i] = lerp(cur.c2[i], target.c2[i], k); }
    cur.spin = lerp(cur.spin, target.spin, k); cur.bright = lerp(cur.bright, target.bright, k);
    cur.ripple = lerp(cur.ripple, target.ripple, k);
    var t = (now - t0) / 1000;
    var speaking = stateName === 'SPEAKING';
    var pulseTarget = speaking ? 0.5 + 0.5 * Math.sin(t * 9) * Math.sin(t * 2.7 + 1) : 0;
    cur.pulse = lerp(cur.pulse, Math.max(0, pulseTarget), 1 - Math.pow(0.0001, dt));
    spinPhase += dt * cur.spin;                               // integrate speed so changes never make the disk jump
    gl.uniform2f(loc.uRes, canvas.width, canvas.height);
    gl.uniform1f(loc.uT, spinPhase);
    gl.uniform1f(loc.uSpin, 1.0);
    gl.uniform1f(loc.uPulse, cur.pulse);
    gl.uniform1f(loc.uBright, cur.bright);
    gl.uniform1f(loc.uRipple, cur.ripple);
    gl.uniform3f(loc.uC1, cur.c1[0], cur.c1[1], cur.c1[2]);
    gl.uniform3f(loc.uC2, cur.c2[0], cur.c2[1], cur.c2[2]);
    gl.uniform2f(loc.uM, mouse[0], mouse[1]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  function hud(container) {
    var font = "font-family:'Segoe UI','Inter',system-ui,sans-serif;";
    el.title = make('div', font + 'position:absolute;left:0;right:0;bottom:15%;text-align:center;font-size:30px;font-weight:300;letter-spacing:8px;color:#fff;text-shadow:0 0 18px currentColor;pointer-events:none;', 'STANDBY');
    el.sub = make('div', font + 'position:absolute;left:0;right:0;bottom:11.5%;text-align:center;font-size:12px;letter-spacing:4px;color:rgba(255,255,255,.55);pointer-events:none;', 'FLEXIE IS READY');
    el.badge = make('div', font + 'position:absolute;top:18px;left:22px;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,.6);pointer-events:none;', 'CORE: OFFLINE');
    el.stats = make('div', font + 'position:absolute;top:18px;right:70px;font-size:11px;letter-spacing:3px;color:rgba(255,255,255,.5);pointer-events:none;', '');
    el.speech = make('div', font + 'position:absolute;left:50%;transform:translateX(-50%);bottom:21%;max-width:min(680px,86vw);max-height:22vh;overflow:auto;display:none;text-align:center;font-size:15px;line-height:1.5;color:rgba(255,255,255,.88);padding:10px 18px;border-radius:14px;background:rgba(0,0,0,.45);backdrop-filter:blur(6px);');
    var close = make('button', font + 'position:absolute;top:12px;right:16px;width:38px;height:38px;border-radius:50%;border:1px solid rgba(255,255,255,.25);background:rgba(0,0,0,.4);color:#fff;font-size:20px;cursor:pointer;', String.fromCharCode(215));
    close.setAttribute('aria-label', 'Close orb');
    close.addEventListener('click', function () { if (opts.onClose) opts.onClose(); });
    var form = make('form', 'position:absolute;left:50%;transform:translateX(-50%);bottom:3.5%;width:min(520px,86vw);');
    var input = make('input', font + 'width:100%;box-sizing:border-box;padding:11px 18px;border-radius:24px;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.5);color:#fff;font-size:14px;outline:none;');
    input.placeholder = 'Ask Flexie...'; input.autocomplete = 'off'; input.maxLength = 500;
    form.appendChild(input);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (text && opts.onCommand) opts.onCommand(text);
      input.value = '';
    });
    [el.title, el.sub, el.badge, el.stats, el.speech, close, form].forEach(function (n) { container.appendChild(n); });
  }

  function mount(container, options) {
    destroy();
    opts = options || {};
    root = container;
    root.style.position = root.style.position || 'relative';
    root.style.background = '#000';
    canvas = make('canvas', 'position:absolute;inset:0;width:100%;height:100%;display:block;');
    root.appendChild(canvas);
    gl = canvas.getContext('webgl', { antialias: false, alpha: false }) || canvas.getContext('experimental-webgl');
    hud(root);
    if (!gl) { el.sub.textContent = 'WEBGL IS NOT AVAILABLE IN THIS BROWSER'; return; }
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    } catch (err) { el.sub.textContent = 'ORB SHADER FAILED: ' + String(err.message || err).slice(0, 120); return; }
    gl.useProgram(prog);
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);   // one big triangle
    var pl = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(pl); gl.vertexAttribPointer(pl, 2, gl.FLOAT, false, 0, 0);
    ['uRes', 'uT', 'uSpin', 'uPulse', 'uBright', 'uRipple', 'uC1', 'uC2', 'uM'].forEach(function (u) { loc[u] = gl.getUniformLocation(prog, u); });
    resizeHandler = resize; window.addEventListener('resize', resizeHandler);
    root.addEventListener('mousemove', function (e) {
      var r = root.getBoundingClientRect();
      mouse = [(e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height * 2 - 1)];
    });
    keyHandler = function (e) { if (e.key === 'Escape' && opts.onClose && visible()) opts.onClose(); };
    window.addEventListener('keydown', keyHandler);
    resize();
    t0 = performance.now(); lastFrame = 0;
    raf = requestAnimationFrame(frame);
  }

  function destroy() {
    if (raf) cancelAnimationFrame(raf); raf = 0;
    if (resizeHandler) window.removeEventListener('resize', resizeHandler); resizeHandler = null;
    if (keyHandler) window.removeEventListener('keydown', keyHandler); keyHandler = null;
    if (root) { while (root.firstChild) root.removeChild(root.firstChild); }
    root = canvas = gl = prog = null; el = {};
  }

  window.FlexieOrb = {
    mount: mount,
    destroy: destroy,
    setGestures: function () { /* hand tracking is not part of this orb */ },
    setState: function (state) {
      stateName = String(state || 'IDLE').toUpperCase();
      target = PRESETS[stateName] || PRESETS.IDLE;
      if (el.title) {
        el.title.textContent = target.label; el.sub.textContent = target.sub;
        el.title.style.color = 'rgb(' + target.c1.map(function (v) { return Math.round(v * 255); }).join(',') + ')';
      }
    },
    setSpeech: function (text) {
      if (!el.speech) return;
      el.speech.textContent = String(text || '').slice(0, 1200);
      el.speech.style.display = text ? 'block' : 'none';
    },
    setConnected: function (online) {
      if (el.badge) el.badge.textContent = online ? 'CORE: ONLINE' : 'CORE: OFFLINE';
    },
    setStats: function (s) {                                  // optional {cpu, ram, net}
      if (!el.stats || !s) return;
      var parts = [];
      if (s.cpu != null) parts.push('CPU ' + Math.round(s.cpu) + '%');
      if (s.ram != null) parts.push('RAM ' + Math.round(s.ram) + '%');
      if (s.net != null) parts.push('NET ' + s.net);
      el.stats.textContent = parts.join('   ');
    },
    style: 'blackhole'
  };
})();
