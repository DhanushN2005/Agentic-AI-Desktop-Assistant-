// Flexie Background Service Worker
const API_BASE = "http://127.0.0.1:8768";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "flexie-summarize-page",
    title: "⚡ Summarize page with Flexie",
    contexts: ["page"]
  });

  chrome.contextMenus.create({
    id: "flexie-explain-selection",
    title: "⚡ Explain selection with Flexie",
    contexts: ["selection"]
  });

  chrome.contextMenus.create({
    id: "flexie-debug-code",
    title: "⚡ Debug code with Flexie",
    contexts: ["selection", "page"]
  });

  // Enable side panel on click if supported
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || !tab.id) return;

  if (info.menuItemId === "flexie-summarize-page") {
    openSidePanel(tab.id, { action: "summarize" });
  } else if (info.menuItemId === "flexie-explain-selection") {
    openSidePanel(tab.id, { action: "explain", text: info.selectionText });
  } else if (info.menuItemId === "flexie-debug-code") {
    openSidePanel(tab.id, { action: "debug", text: info.selectionText });
  }
});

function openSidePanel(tabId, contextData) {
  if (chrome.sidePanel && chrome.sidePanel.open) {
    chrome.sidePanel.open({ tabId }).then(() => {
      chrome.storage.local.set({ flexie_active_context: contextData });
    }).catch(() => {});
  }
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "OPEN_ASSISTANT_FOR_SELECTION") {
    if (sender.tab && sender.tab.id) {
      openSidePanel(sender.tab.id, { action: "explain", text: request.text });
      sendResponse({ success: true });
    }
    return true;
  }

  if (request.type === "CALL_API") {
    const { endpoint, method = "POST", body } = request;
    chrome.storage.local.get(["flexie_token"], (res) => {
      const token = res.flexie_token || "";
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      fetch(`${API_BASE}${endpoint}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined
      })
        .then(async (r) => {
          const data = await r.json().catch(() => ({}));
          sendResponse({ ok: r.ok, status: r.status, data });
        })
        .catch((err) => {
          sendResponse({ ok: false, error: err.message });
        });
    });
    return true; // async response
  }
});
