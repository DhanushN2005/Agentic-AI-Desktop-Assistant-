// Flexiee Sidebar — v2.1
// Fixes: endpoint /api/flexie/page-assistant → /page-assist
// Adds:  DOM task panel, SSE stream tab, token polling, connection badge

const API_BASE = "http://127.0.0.1:8768";

let activeTab = null;
let pageData = { title: "", url: "", pageText: "", selectedText: "", codeBlocks: [], meta: {} };
let isOnline = false;
let sseSource = null;

// ── DOM refs ─────────────────────────────────────────────────────────
const chatFeed      = document.getElementById("chatFeed");
const userInput     = document.getElementById("userInput");
const btnSend       = document.getElementById("btnSend");
const btnVoice      = document.getElementById("btnVoice");
const statusBadge   = document.getElementById("connectionStatus");
const pageTitle     = document.getElementById("pageTitle");
const pageUrl       = document.getElementById("pageUrl");

// ── Connection ───────────────────────────────────────────────────────
function setOnlineState(online) {
  isOnline = online;
  statusBadge.textContent = online ? "ONLINE" : "OFFLINE";
  statusBadge.className   = "status-badge " + (online ? "online" : "");
}

async function checkConnection() {
  try {
    const res = await fetch(`${API_BASE}/health`, { method: "GET", signal: AbortSignal.timeout(2500) });
    setOnlineState(res.ok);
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      // Cache token for background worker
      if (data.token) chrome.storage.local.set({ flexie_token: data.token });
    }
  } catch {
    setOnlineState(false);
  }
}

// Check every 5 s
checkConnection();
setInterval(checkConnection, 5000);

// ── Page data ─────────────────────────────────────────────────────────
async function refreshPageData() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length) return;
  activeTab = tabs[0];

  pageTitle.textContent = activeTab.title   || "Untitled";
  pageUrl.textContent   = activeTab.url     || "";

  chrome.tabs.sendMessage(activeTab.id, { type: "GET_PAGE_DATA" }, (res) => {
    if (chrome.runtime.lastError || !res) return;
    pageData = res;
    pageTitle.textContent = pageData.title || activeTab.title;
    pageUrl.textContent   = pageData.url   || activeTab.url;
  });
}

refreshPageData();
setInterval(refreshPageData, 4000);

// ── Chat helpers ──────────────────────────────────────────────────────
function addMessage(sender, html, isHtml = false) {
  const el = document.createElement("div");
  el.className = `msg ${sender}`;
  if (isHtml) el.innerHTML = html; else el.textContent = html;
  chatFeed.appendChild(el);
  chatFeed.scrollTop = chatFeed.scrollHeight;
  return el;
}

function addSystemMsg(text) {
  const el = document.createElement("div");
  el.className = "msg system";
  el.textContent = `⚡ ${text}`;
  chatFeed.appendChild(el);
  chatFeed.scrollTop = chatFeed.scrollHeight;
  return el;
}

// ── Ask Flexie (page-assist endpoint) ────────────────────────────────
async function askFlexie(query, action = "ask") {
  addMessage("user", query);
  const loadEl = addMessage("flexie", "Thinking…");

  // Pull current token
  const stored = await chrome.storage.local.get(["flexie_token"]);
  const token  = stored.flexie_token || "";
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    const res = await fetch(`${API_BASE}/page-assist`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        query,
        url:           pageData.url,
        title:         pageData.title,
        page_content:  pageData.pageText,
        selected_text: pageData.selectedText,
        action,
      }),
    });

    if (!res.ok) {
      loadEl.textContent = `Error ${res.status}: Flexie backend returned an error. Is it running?`;
      return;
    }
    const data = await res.json().catch(() => ({}));
    loadEl.textContent = data.answer || data.result || data.message || JSON.stringify(data);
  } catch (err) {
    loadEl.textContent = `Cannot reach Flexie (${err.message}). Make sure api_server.py is running on port 8768.`;
  }
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

// ── Send raw command to orchestrator ─────────────────────────────────
async function sendCommand(command) {
  addMessage("user", `CMD: ${command}`);
  const loadEl = addMessage("flexie", "Executing…");

  const stored = await chrome.storage.local.get(["flexie_token"]);
  const token  = stored.flexie_token || "";
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  try {
    const res = await fetch(`${API_BASE}/command`, {
      method: "POST", headers,
      body: JSON.stringify({ command }),
    });
    const data = await res.json().catch(() => ({}));
    loadEl.textContent = data.result || data.answer || data.message || "Done.";
  } catch (err) {
    loadEl.textContent = `Error: ${err.message}`;
  }
}

// ── DOM Task Executor ─────────────────────────────────────────────────
async function runDomTask(domType, payload = {}) {
  if (!activeTab) await refreshPageData();
  if (!activeTab) return addSystemMsg("No active tab found.");

  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { type: "DOM_TASK", tabId: activeTab.id, domType, payload },
      (res) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
        } else {
          resolve(res ?? { ok: false, error: "No response" });
        }
      }
    );
  });
}

// Helper: run a DOM task and show result in chat
async function domTaskWithFeedback(label, domType, payload) {
  addSystemMsg(`${label}…`);
  const res = await runDomTask(domType, payload);
  if (!res.ok) {
    addMessage("flexie", `⚠ ${label} failed: ${res.error || "unknown"}`);
  } else {
    // Pretty-print result
    let text = `✓ ${label}`;
    if (res.tables)      text += `\n${res.tables.length} table(s) extracted.`;
    if (res.links)       text += `\n${res.links.length} links found.`;
    if (res.matchCount !== undefined) text += `\n${res.matchCount} match(es) highlighted.`;
    if (res.tag)         text += ` — clicked <${res.tag}>${res.text ? ' "' + res.text + '"' : ""}`;
    addMessage("flexie", text);
  }
  return res;
}

// ── DOM Command Parser (natural language in the input bar) ────────────
async function handleDomCommand(raw) {
  const cmd = raw.trim().toLowerCase();

  // Click
  const clickMatch = raw.match(/^(?:click|press|tap)\s+(.+)/i);
  if (clickMatch) {
    await domTaskWithFeedback(`Click "${clickMatch[1]}"`, "DOM_CLICK", { target: clickMatch[1].trim() });
    return true;
  }
  // Scroll top / bottom
  if (/scroll\s+(?:to\s+)?top/i.test(cmd)) {
    await domTaskWithFeedback("Scroll to top", "DOM_SCROLL", { top: 0 }); return true;
  }
  if (/scroll\s+(?:to\s+)?bottom/i.test(cmd)) {
    await domTaskWithFeedback("Scroll to bottom", "DOM_SCROLL", { direction: "bottom" }); return true;
  }
  // Scroll to element
  const scrollMatch = raw.match(/^scroll\s+to\s+(.+)/i);
  if (scrollMatch) {
    await domTaskWithFeedback(`Scroll to "${scrollMatch[1]}"`, "DOM_SCROLL", { target: scrollMatch[1].trim() }); return true;
  }
  // Extract tables
  if (/extract\s+tables?/i.test(cmd)) {
    const res = await domTaskWithFeedback("Extract tables", "DOM_EXTRACT_TABLES", {});
    if (res.ok && res.tables?.length) {
      res.tables.forEach((t, i) => {
        addMessage("flexie",
          `Table ${i + 1}${t.caption ? ` (${t.caption})` : ""}:\n` +
          t.rows.slice(0, 5).map(r => r.join(" | ")).join("\n") +
          (t.rows.length > 5 ? `\n…${t.rows.length - 5} more rows` : ""),
          false);
      });
    }
    return true;
  }
  // Extract links
  if (/extract\s+links?/i.test(cmd)) {
    const res = await domTaskWithFeedback("Extract links", "DOM_EXTRACT_LINKS", {});
    if (res.ok && res.links?.length) {
      const preview = res.links.slice(0, 8).map(l => `• ${l.text || "(no text)"} → ${l.href}`).join("\n");
      addMessage("flexie", preview + (res.links.length > 8 ? `\n…${res.links.length - 8} more` : ""));
    }
    return true;
  }
  // Find text
  const findMatch = raw.match(/^(?:find|highlight|search for)\s+(.+)/i);
  if (findMatch) {
    await domTaskWithFeedback(`Find "${findMatch[1]}"`, "DOM_FIND_TEXT", { text: findMatch[1].trim() }); return true;
  }
  // Fill input
  const fillMatch = raw.match(/^fill\s+(.+?)\s+with\s+(.+)/i);
  if (fillMatch) {
    await domTaskWithFeedback(`Fill "${fillMatch[1]}"`, "DOM_FILL", { label: fillMatch[1].trim(), value: fillMatch[2].trim() }); return true;
  }
  // Submit form
  if (/^submit\s*(?:form|the form)?$/i.test(cmd)) {
    await domTaskWithFeedback("Submit form", "DOM_SUBMIT", {}); return true;
  }
  // Inject banner
  const bannerMatch = raw.match(/^(?:banner|notify|show)\s+(.+)/i);
  if (bannerMatch) {
    await domTaskWithFeedback("Inject banner", "DOM_INJECT_BANNER", { message: bannerMatch[1].trim(), autoDismissMs: 5000 }); return true;
  }
  // Get element info
  const infoMatch = raw.match(/^(?:info|inspect|get)\s+(.+)/i);
  if (infoMatch) {
    const res = await runDomTask("DOM_GET_ELEMENT", { target: infoMatch[1].trim() });
    if (res.ok) {
      addMessage("flexie",
        `<${res.tag}> id="${res.id}" class="${res.classes}"\n` +
        `Text: ${res.text?.slice(0,100)}\n` +
        `Size: ${Math.round(res.rect?.width)}×${Math.round(res.rect?.height)}`
      );
    } else {
      addMessage("flexie", `⚠ ${res.error}`);
    }
    return true;
  }

  return false; // not a DOM command
}

// ── Send handler ──────────────────────────────────────────────────────
btnSend.addEventListener("click", handleSend);
userInput.addEventListener("keydown", e => { if (e.key === "Enter") handleSend(); });

async function handleSend() {
  const q = userInput.value.trim();
  if (!q) return;
  userInput.value = "";

  // Try DOM command first; fall back to page-assist
  const handled = await handleDomCommand(q);
  if (!handled) await askFlexie(q);
}

// ── Quick action chips ────────────────────────────────────────────────
document.getElementById("btnSummarize")?.addEventListener("click", () =>
  askFlexie("Summarize this webpage into 3 concise paragraphs.", "summarize"));

document.getElementById("btnKeyPoints")?.addEventListener("click", () =>
  askFlexie("Extract the key takeaways and action points as a bulleted list.", "extract"));

document.getElementById("btnDebugCode")?.addEventListener("click", () => {
  const code = pageData.codeBlocks.join("\n\n") || pageData.selectedText;
  code
    ? askFlexie(`Analyze this code for bugs and explain fixes:\n${code}`, "explain_code")
    : askFlexie("Inspect this page for errors, stack traces, or anomalies.", "explain_code");
});

document.getElementById("btnResearch")?.addEventListener("click", () =>
  askFlexie(`Research related topics for "${pageData.title}" and compile a synthesis.`, "research"));

// ── Context from background (right-click menu) ────────────────────────
chrome.storage.onChanged.addListener((changes) => {
  if (changes.flexie_active_context) {
    const ctx = changes.flexie_active_context.newValue;
    if (!ctx) return;
    if      (ctx.action === "summarize")    askFlexie("Summarize this page.", "summarize");
    else if (ctx.action === "explain")      askFlexie(`Explain: ${ctx.text || ""}`, "explain");
    else if (ctx.action === "debug")        askFlexie(`Debug this:\n${ctx.text || ""}`, "explain_code");
    else if (ctx.action === "research")     askFlexie(`Research: ${ctx.text || ""}`, "research");
    else if (ctx.action === "translate")    askFlexie(`Translate: ${ctx.text || ""}`, "translate");
    else if (ctx.action === "extract_tables") {
      const tables = ctx.data || [];
      addSystemMsg(`Extracted ${tables.length} table(s) from context menu`);
      tables.slice(0, 3).forEach((t, i) => {
        addMessage("flexie",
          `Table ${i+1}: ${t.rows.slice(0,5).map(r => r.join(" | ")).join("\n")}`);
      });
    }
    else if (ctx.action === "extract_links") {
      const links = ctx.data || [];
      addSystemMsg(`${links.length} links extracted`);
      addMessage("flexie", links.slice(0,8).map(l => `• ${l.text || "(no text)"} → ${l.href}`).join("\n"));
    }
    chrome.storage.local.remove("flexie_active_context");
  }
});

// ── Voice Input ───────────────────────────────────────────────────────
if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.onstart  = () => btnVoice.classList.add("recording");
  recognition.onend    = () => btnVoice.classList.remove("recording");
  recognition.onerror  = () => btnVoice.classList.remove("recording");
  recognition.onresult = (e) => {
    const t = e.results[0][0].transcript;
    userInput.value = t;
    btnVoice.classList.remove("recording");
    handleSend();
  };
  btnVoice.addEventListener("click", () =>
    btnVoice.classList.contains("recording") ? recognition.stop() : recognition.start()
  );
} else {
  if (btnVoice) btnVoice.style.display = "none";
}

// ── Init ──────────────────────────────────────────────────────────────
addSystemMsg("Flexie ready — ask a question or type a DOM command (click, scroll, fill, extract tables…)");

// Consume any pending DOM command injected by popup quick chips
chrome.storage.local.get(["flexie_pending_dom_cmd"], (data) => {
  if (data.flexie_pending_dom_cmd) {
    chrome.storage.local.remove("flexie_pending_dom_cmd");
    const cmd = data.flexie_pending_dom_cmd;
    userInput.value = cmd;
    setTimeout(handleSend, 600); // short delay so tab is ready
  }
});
