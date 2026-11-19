// Flexie orb panel: exposes window.FlexieOrb = { mount, setState, setSpeech, setConnected, setGestures, destroy }.
// Vanilla DOM (no React). Hand tracking (MediaPipe) is a separate bundle loaded only when gestures are enabled.
import { createOrbScene, type OrbSceneApi } from "./orbScene";
import type { HandTracker as HandTrackerType, TrackerStatus } from "./handTracker";

interface MountOptions {
  /** Called with text typed into the orb's command bar (the dashboard passes its own send()). */
  onCommand?: (text: string) => void;
  /** Called when the user presses the close button / Escape. */
  onClose?: () => void;
}

const MODE_LABEL: Record<string, string> = { idle: "STANDBY", spin: "SPIN", zoom: "ZOOM" };
const GESTURE_BUNDLE = "/static/orb-gestures.js";

let root: HTMLElement | null = null;
let scene: OrbSceneApi | null = null;
let tracker: HandTrackerType | null = null;
let opts: MountOptions = {};
let el: Record<string, HTMLElement> = {};
let gestureLoad: Promise<{ HandTracker: new (...a: any[]) => HandTrackerType }> | null = null;
let keyHandler: ((e: KeyboardEvent) => void) | null = null;
let starting = false;

function make<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = cls;
  if (text !== undefined) node.textContent = text; // textContent only: assistant text is never parsed as HTML
  return node;
}

function loadGestureBundle() {
  if (!gestureLoad) {
    gestureLoad = new Promise((resolve, reject) => {
      const w = window as unknown as { FlexieOrbGestures?: { HandTracker: any } };
      if (w.FlexieOrbGestures) return resolve(w.FlexieOrbGestures);
      const s = document.createElement("script");
      s.src = GESTURE_BUNDLE;
      s.onload = () => (w.FlexieOrbGestures ? resolve(w.FlexieOrbGestures) : reject(new Error("gesture bundle empty")));
      s.onerror = () => reject(new Error("gesture bundle failed to load"));
      document.head.appendChild(s);
    });
    gestureLoad.catch(() => { gestureLoad = null; }); // allow a retry
  }
  return gestureLoad;
}

function showError(msg: string | null) {
  el.error.textContent = msg || "";
  el.error.style.display = msg ? "block" : "none";
}

function setCameraUI(on: boolean, label?: string) {
  el.camera.classList.toggle("forb-visible", on);
  el.gestureBtn.setAttribute("aria-pressed", String(on));
  el.gestureBtn.textContent = label || (on ? "GESTURES ON" : "GESTURES OFF");
  el.hint.textContent = on
    ? "PINCH + MOVE: spin    PINCH BOTH HANDS and SPREAD: zoom"
    : "G: hand gestures    R: reset    + / -: zoom    DRAG: spin    SCROLL: zoom";
}

async function setGestures(on: boolean): Promise<void> {
  if (!root || !scene) return;
  if (!on) {
    tracker?.stop();
    tracker = null;
    setCameraUI(false);
    el.camStatus.textContent = "SHOW HANDS";
    return;
  }
  if (tracker || starting) return;
  starting = true;
  showError(null);
  setCameraUI(false, "INITIALIZING…");
  try {
    const lib = await loadGestureBundle();
    const video = el.video as HTMLVideoElement;
    const overlay = el.overlay as HTMLCanvasElement;
    const t = new lib.HandTracker(video, overlay, {
      onRotate: (dt: number, dp: number) => scene?.rotateBy(dt, dp),
      onZoom: (f: number) => scene?.zoomBy(f),
      onStatus: (s: TrackerStatus) => {
        el.camStatus.textContent = s.hands > 0
          ? `${s.hands} HAND${s.hands > 1 ? "S" : ""} · ${MODE_LABEL[s.mode] || "ACTIVE"}`
          : "SHOW HANDS";
      },
    });
    tracker = t;
    setCameraUI(true);          // the camera permission prompt appears now, never before
    await t.start();
  } catch (err) {
    tracker?.stop();
    tracker = null;
    setCameraUI(false);
    showError(err instanceof DOMException && err.name === "NotAllowedError" ? "CAMERA ACCESS DENIED" : "TRACKING INIT FAILED");
  } finally {
    starting = false;
  }
}

function isVisible(): boolean {
  return !!root && root.offsetParent !== null;
}

function mount(container: HTMLElement, options: MountOptions = {}) {
  if (root) destroy();
  opts = options;
  root = make("div", "forb-root");
  const stage = make("div", "forb-stage");
  root.appendChild(stage);
  root.appendChild(make("div", "forb-vignette"));

  const title = make("div", "forb-title");
  title.appendChild(make("span", "forb-name", "F.L.E.X.I.E. 2.0"));
  el.badge = make("span", "forb-badge forb-offline", "OFFLINE");
  title.appendChild(el.badge);
  const close = make("button", "forb-btn forb-close", "CLOSE");
  close.type = "button";
  close.setAttribute("aria-label", "Close orb");
  close.onclick = () => opts.onClose?.();
  title.appendChild(close);
  root.appendChild(title);

  el.speech = make("div", "forb-speech");
  el.speech.style.display = "none";
  el.speech.appendChild(make("div", "forb-speech-label", "FLEXIE RESPONSE"));
  el.speechText = make("div", "forb-speech-text");
  el.speech.appendChild(el.speechText);
  root.appendChild(el.speech);

  const bar = make("div", "forb-cmdbar");
  const input = make("input", "forb-input");
  input.type = "text";
  input.placeholder = "Speak or type a command for Flexie…";
  input.maxLength = 500;
  const send = () => {
    const text = input.value.trim();
    if (text) opts.onCommand?.(text);
    input.value = "";
  };
  input.onkeydown = (e) => { if (e.key === "Enter") send(); };
  const sendBtn = make("button", "forb-btn", "EXECUTE");
  sendBtn.type = "button";
  sendBtn.onclick = send;
  bar.append(input, sendBtn);
  root.appendChild(bar);

  el.hint = make("div", "forb-hint");
  root.appendChild(el.hint);

  const controls = make("div", "forb-controls");
  el.camera = make("div", "forb-camera");
  const video = make("video", "forb-video");
  video.muted = true;
  video.setAttribute("playsinline", "");
  el.video = video;
  const overlay = make("canvas", "forb-overlay");
  overlay.width = 208;
  overlay.height = 156;
  el.overlay = overlay;
  el.camStatus = make("div", "forb-camstatus", "SHOW HANDS");
  el.camera.append(video, overlay, el.camStatus);
  el.error = make("div", "forb-error");
  el.error.style.display = "none";
  const gbtn = make("button", "forb-btn", "GESTURES OFF");
  gbtn.type = "button";
  gbtn.onclick = () => void setGestures(!tracker);
  el.gestureBtn = gbtn;
  const row = make("div", "forb-row");
  const buttons: Array<[string, () => void]> = [
    ["+", () => scene?.zoomIn()],
    ["−", () => scene?.zoomOut()],
    ["RESET", () => scene?.resetView()],
  ];
  for (const [label, fn] of buttons) {
    const b = make("button", "forb-btn", label);
    b.type = "button";
    b.onclick = fn;
    row.appendChild(b);
  }
  controls.append(el.camera, el.error, gbtn, row);
  root.appendChild(controls);

  container.appendChild(root);
  scene = createOrbScene(stage);
  setCameraUI(false);

  keyHandler = (e: KeyboardEvent) => {
    if (!isVisible()) return;
    const target = e.target as HTMLElement | null;
    const tag = target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) return;
    switch (e.key) {
      case "+": case "=": scene?.zoomIn(); break;
      case "-": case "_": scene?.zoomOut(); break;
      case "r": case "R": scene?.resetView(); break;
      case "g": case "G": void setGestures(!tracker); break;
      case "Escape": opts.onClose?.(); break;
    }
  };
  window.addEventListener("keydown", keyHandler);
}

function destroy() {
  tracker?.stop();
  tracker = null;
  if (keyHandler) window.removeEventListener("keydown", keyHandler);
  keyHandler = null;
  scene?.dispose();
  scene = null;
  root?.remove();
  root = null;
  el = {};
}

(window as unknown as { FlexieOrb: unknown }).FlexieOrb = {
  mount,
  destroy,
  setGestures,
  setState(state: string) {
    scene?.setState(state);
    if (el.badge && !el.badge.classList.contains("forb-offline")) {
      el.badge.textContent = `CORE: ${String(state || "").toUpperCase().slice(0, 16)}`;
    }
  },
  setSpeech(text: string) {
    if (!el.speech) return;
    el.speechText.textContent = String(text || "").slice(0, 1200);
    el.speech.style.display = text ? "block" : "none";
  },
  setConnected(online: boolean) {
    if (!el.badge) return;
    el.badge.classList.toggle("forb-offline", !online);
    el.badge.classList.toggle("forb-online", online);
    el.badge.textContent = online ? "CORE: ONLINE" : "OFFLINE";
  },
};
