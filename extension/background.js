// Flexiee Background Service Worker — MV3
const API_BASE = "http://127.0.0.1:8768";

// ── Startup ─────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  // Context menus
  const menus = [
    { id: "flexie-summarize-page",     title: "⚡ Summarize page with Flexie",        contexts: ["page"] },
    { id: "flexie-explain-selection",  title: "⚡ Explain selection with Flexie",      contexts: ["selection"] },
    { id: "flexie-debug-code",         title: "⚡ Debug code with Flexie",             contexts: ["selection"] },
    { id: "flexie-research-selection", title: "⚡ Research this with Flexie",          contexts: ["selection"] },
    { id: "flexie-translate",          title: "⚡ Translate selection with Flexie",    contexts: ["selection"] },
    { id: "flexie-extract-tables",     title: "⚡ Extract tables from this page",      contexts: ["page"] },
    { id: "flexie-extract-links",      title: "⚡ Extract all links from this page",   contexts: ["page"] },
    { id: "flexie-fill-form",          title: "⚡ Fill form with Flexie AI",           contexts: ["editable"] },
    { id: "flexie-screenshot",         title: "⚡ Analyze visible page with Flexie",   contexts: ["page"] },
  ];
  menus.forEach(m => chrome.contextMenus.create(m));

  // Open sidebar on toolbar icon click
  if (chrome.sidePanel?.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }

  // Auto-fetch token on install/update
  fetchAndStoreToken();
});

// Refresh token every 30 s while extension is alive
chrome.alarms.create("flexie-token-refresh", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "flexie-token-refresh") { fetchAndStoreToken(); startPolling(); }
});

/** The pairing key Flexie wrote into this extension's own folder (extension/pairing.key). Chrome sends no
 *  Origin header for an extension's own requests, so this key is how Flexie recognises the extension.
 *  Web pages and other extensions cannot read it. Re-read each time: it may be created after install. */
async function pairingHeaders() {
  try {
    const r = await fetch(chrome.runtime.getURL("pairing.key"), { cache: "no-store" });
    if (!r.ok) return {};
    const key = (await r.text()).trim();
    return key ? { "X-Flexie-Pairing": key } : {};
  } catch {
    return {};
  }
}

/** Pull the session bearer token from the Flexie health endpoint. */
async function fetchAndStoreToken() {
  try {
    const res = await fetch(`${API_BASE}/health`, { method: "GET", headers: await pairingHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    if (data.token) {
      await chrome.storage.local.set({ flexie_token: data.token, flexie_online: true });
    } else {
      await chrome.storage.local.set({ flexie_online: true });
    }
  } catch {
    await chrome.storage.local.set({ flexie_online: false });
  }
}

// ── Context Menu Clicks ──────────────────────────────────────────────
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!tab?.id) return;

  const actionMap = {
    "flexie-summarize-page":     { action: "summarize" },
    "flexie-explain-selection":  { action: "explain",   text: info.selectionText },
    "flexie-debug-code":         { action: "debug",     text: info.selectionText },
    "flexie-research-selection": { action: "research",  text: info.selectionText },
    "flexie-translate":          { action: "translate", text: info.selectionText },
    "flexie-extract-tables":     { action: "extract_tables" },
    "flexie-extract-links":      { action: "extract_links" },
    "flexie-fill-form":          { action: "fill_form" },
    "flexie-screenshot":         { action: "screenshot" },
  };

  const ctx = actionMap[info.menuItemId];
  if (!ctx) return;

  // DOM-only actions handled via content script; keep the extracted data
  // (merged into the context) and tell the user when the page is restricted.
  let payload = ctx;
  if (ctx.action === "extract_tables" || ctx.action === "extract_links") {
    const isTables = ctx.action === "extract_tables";
    try {
      const res = await chrome.tabs.sendMessage(tab.id, { type: isTables ? "DOM_EXTRACT_TABLES" : "DOM_EXTRACT_LINKS" });
      if (res?.ok) payload = { ...ctx, data: isTables ? res.tables : res.links };
      else payload = { action: "notice", text: "Flexie could not extract data from this page." };
    } catch (e) {
      payload = { action: "notice", text: "Flexie cannot read this page (restricted or not loaded). Try a normal web page." };
    }
  }

  openSidePanel(tab.id, payload);
});

function openSidePanel(tabId, contextData) {
  // Store first (sidebar reads it once on load and via onChanged), then open.
  chrome.storage.local.set({ flexie_active_context: contextData }).catch?.(() => {});
  if (chrome.sidePanel?.open) {
    chrome.sidePanel.open({ tabId }).catch(() => {});
  }
}

// ── CALL_API hardening ───────────────────────────────────────────────
const ALLOWED_ENDPOINTS = [
  /^\/health$/, /^\/page-assist$/, /^\/command$/,
  /^\/api\/(flexie|jarvis)\/(status|usage|jobs|commands|events|page-assistant|approve|reject)$/,
  /^\/api\/flexie\/mail\/[a-z-]+$/,
];
const PRIVILEGED_ENDPOINTS = [/^\/command$/, /^\/api\/(flexie|jarvis)\/(commands|approve|reject)$/, /^\/api\/flexie\/mail\/(send|reply|delete|archive|move|draft)$/];

function validateEndpoint(endpoint) {
  if (typeof endpoint !== "string" || endpoint.length > 200) return null;
  if (!endpoint.startsWith("/")) return null;
  if (/[@\\]|\/\/|\.\.|%2e|%2f|%5c|[\s\u0000-\u001f]/i.test(endpoint)) return null;
  const [path, query = ""] = endpoint.split("?", 2);
  if (!ALLOWED_ENDPOINTS.some((re) => re.test(path))) return null;
  return { path, query };
}

// ── Message Router ───────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

  // Sidebar → content script DOM task relay
  if (sender.id !== chrome.runtime.id) return false;

  if (request.type === "DOM_TASK") {
    if (sender.tab) return sendResponse({ ok: false, error: "Not allowed from content scripts" }), true;
    const { tabId, domType, payload } = request;
    const targetTab = tabId || sender.tab?.id;
    if (!targetTab) return sendResponse({ ok: false, error: "No tab id" }), true;
    chrome.tabs.sendMessage(targetTab, { type: domType, ...payload }, (res) => {
      sendResponse(res ?? { ok: false, error: "No response from content script" });
    });
    return true;
  }

  // Content script → open sidebar for selected text
  if (request.type === "OPEN_ASSISTANT_FOR_SELECTION") {
    if (sender.tab?.id) {
      openSidePanel(sender.tab.id, { action: "explain", text: request.text, url: request.url, title: request.title });
      sendResponse({ ok: true });
    }
    return true;
  }

  // Generic API proxy (with auth token injected automatically)
  if (request.type === "CALL_API") {
    const { method: rawMethod = "POST", body } = request;
    const method = String(rawMethod).toUpperCase();
    const ep = validateEndpoint(request.endpoint);
    if (!ep || !["GET", "POST"].includes(method)) {
      return sendResponse({ ok: false, error: "Endpoint not allowed" }), true;
    }
    if (sender.tab && PRIVILEGED_ENDPOINTS.some((re) => re.test(ep.path))) {
      return sendResponse({ ok: false, error: "Endpoint not allowed from content scripts" }), true;
    }
    const endpoint = ep.path + (ep.query ? "?" + ep.query : "");
    chrome.storage.local.get(["flexie_token"], (stored) => {
      const token = stored.flexie_token || "";
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      fetch(`${API_BASE}${endpoint}`, {
        method,
        headers,
        body: body && method !== "GET" ? JSON.stringify(body) : undefined,
      })
        .then(async (r) => {
          const data = await r.json().catch(() => ({}));
          sendResponse({ ok: r.ok, status: r.status, data });
        })
        .catch((err) => {
          sendResponse({ ok: false, error: err.message });
        });
    });
    return true;
  }

  // Token refresh on demand
  if (request.type === "REFRESH_TOKEN") {
    fetchAndStoreToken().then(() => sendResponse({ ok: true }));
    return true;
  }

  // Get current online status
  if (request.type === "GET_STATUS") {
    chrome.storage.local.get(["flexie_token", "flexie_online"], (data) => {
      sendResponse({ online: data.flexie_online ?? false, hasToken: !!data.flexie_token });
    });
    return true;
  }
});

// ══ Flexie -> browser tasks ═══════════════════════════════════════════════════
// Flexie cannot call into the extension, so the background worker long-polls Flexie for tasks ("read my
// current tab", "scroll down", ...) and posts each result back. The worker is restarted by the alarm above
// if Chrome stopped it; every poll returns within ~20 s, which keeps it under the 30 s idle limit.
// Page text read this way is returned only to Flexie, only because the user asked for it.
let flexiePolling = false;
const TASK_MAX_AGE_S = 28;               // ignore a task that waited longer (Flexie has given up on it)
const POLLABLE_SCHEMES = /^https?:\/\//i; // pages we may read or act on (no chrome://, no extension pages)
const ACT_KINDS = new Set(["click", "fill", "key", "navigate", "submit"]);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function startPolling() {
  if (flexiePolling) return;
  flexiePolling = true;
  try {
    while (true) {
      const { flexie_token: token } = await chrome.storage.local.get(["flexie_token"]);
      if (!token) { await fetchAndStoreToken(); await sleep(3000); continue; }
      let task = null;
      try {
        const res = await fetch(`${API_BASE}/api/flexie/extension/poll?wait=20`, {
          method: "GET", headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 401) { await fetchAndStoreToken(); await sleep(3000); continue; }
        if (!res.ok) { await sleep(5000); continue; }
        task = (await res.json().catch(() => ({}))).task || null;
      } catch {
        await sleep(5000);       // Flexie is not running: try again shortly
        continue;
      }
      if (task) await runTask(task, token);
    }
  } finally {
    flexiePolling = false;      // the alarm / next event restarts the loop
  }
}

async function postResult(token, id, ok, data, error) {
  try {
    await fetch(`${API_BASE}/api/flexie/extension/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ id, ok, data: data ?? null, error: error ?? null }),
    });
  } catch { /* Flexie went away: nothing to do */ }
}

/** The tab the user is looking at (last focused normal window). */
async function currentTab() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tabs.find((t) => t.url && POLLABLE_SCHEMES.test(t.url)) || tabs[0] || null;
}

function toContent(tab, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tab.id, message, (res) => {
      if (chrome.runtime.lastError) {
        reject(new Error("The page is not ready for Flexie. Reload the tab once, then ask again."));
      } else {
        resolve(res);
      }
    });
  });
}

/** Ask the page to do something; a page-side {ok:false,error} becomes a real error for Flexie. */
async function dom(tab, message) {
  const res = await toContent(tab, message);
  if (res && res.ok === false) throw new Error(res.error || "The page could not do that.");
  return res;
}

async function runTask(task, token) {
  const { id, kind, payload = {}, age = 0 } = task;
  if (age > TASK_MAX_AGE_S) return postResult(token, id, false, null, "task was too old");
  chrome.action.setBadgeText({ text: ACT_KINDS.has(kind) ? "▶" : "…" }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ color: ACT_KINDS.has(kind) ? "#ff8800" : "#00c8ff" }).catch(() => {});
  try {
    const data = await executeTask(kind, payload);
    await postResult(token, id, true, data, null);
  } catch (e) {
    await postResult(token, id, false, null, e.message || String(e));
  } finally {
    setTimeout(() => chrome.action.setBadgeText({ text: "" }).catch(() => {}), 1500);
  }
}

async function executeTask(kind, p) {
  if (kind === "list_tabs") {
    const tabs = await chrome.tabs.query({});
    return tabs.slice(0, 60).map((t) => ({ title: t.title || "", url: t.url || "", active: !!t.active, windowId: t.windowId }));
  }
  const tab = await currentTab();
  if (!tab) throw new Error("No browser tab is active.");
  if (kind === "active_tab") return { title: tab.title || "", url: tab.url || "", id: tab.id };
  if (kind === "navigate") {
    if (!POLLABLE_SCHEMES.test(p.url || "")) throw new Error("Flexie can only open http or https addresses.");
    await chrome.tabs.update(tab.id, { url: p.url });
    return { navigated: p.url };
  }
  if (!POLLABLE_SCHEMES.test(tab.url || "")) {
    throw new Error("This kind of page (browser settings, new tab, extension page) cannot be read.");
  }
  const via = { viaFlexie: true };    // content.js refuses password / card fields for these requests
  switch (kind) {
    case "read_page": {
      const d = await toContent(tab, { type: "GET_PAGE_DATA" });
      return { title: d.title, url: d.url, selectedText: (d.selectedText || "").slice(0, 2000),
               text: (d.pageText || "").slice(0, 12000), codeBlocks: (d.codeBlocks || []).slice(0, 5), meta: d.meta };
    }
    case "extract_tables": return dom(tab, { type: "DOM_EXTRACT_TABLES" });
    case "extract_links": return dom(tab, { type: "DOM_EXTRACT_LINKS" });
    case "find_text": return dom(tab, { type: "DOM_FIND_TEXT", text: p.text });
    case "scroll": return dom(tab, { type: "DOM_SCROLL", target: p.target, direction: p.direction, top: p.top });
    case "click": return dom(tab, { type: "DOM_CLICK", target: p.target, ...via });
    case "fill": return dom(tab, { type: "DOM_FILL", selector: p.selector, label: p.label, value: p.value, ...via });
    case "key": return dom(tab, { type: "DOM_KEY", key: p.key, selector: p.selector, ...via });
    case "submit": return dom(tab, { type: "DOM_SUBMIT", selector: p.selector, ...via });
    default: throw new Error("Unknown task kind: " + kind);
  }
}

chrome.runtime.onStartup.addListener(() => { startPolling(); });
startPolling();      // service worker start (install, browser start, or woken by the alarm)
