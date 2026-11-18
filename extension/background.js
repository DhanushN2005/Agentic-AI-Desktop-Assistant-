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
  if (alarm.name === "flexie-token-refresh") fetchAndStoreToken();
});

/** Pull the session bearer token from the Flexie health endpoint. */
async function fetchAndStoreToken() {
  try {
    const res = await fetch(`${API_BASE}/health`, { method: "GET" });
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
