// Flexie popup logic. Lives in its own file because Manifest V3 extension pages cannot run inline <script> blocks.
const API_BASE = "http://127.0.0.1:8768";

const statusDot  = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const tokenDot   = document.getElementById("tokenDot");
const tokenText  = document.getElementById("tokenText");
const footer     = document.getElementById("footer");

/** The pairing key Flexie wrote into this extension's folder: Chrome sends no Origin for extension pages,
 *  so this is how Flexie recognises the extension. */
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

async function checkHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`, {
      method: "GET",
      headers: await pairingHeaders(),
      signal: AbortSignal.timeout(2500),
    });
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      const paired = !!data.token;
      statusDot.className  = "dot " + (paired ? "online" : "offline");
      statusText.className = "status-text " + (paired ? "online" : "offline");
      statusText.textContent = paired ? "ONLINE" : "NOT PAIRED";
      if (data.token) {
        chrome.storage.local.set({ flexie_token: data.token });
        tokenDot.className = "token-dot ok";
        tokenText.textContent = "token ✓";
      } else {
        // Check cached token
        const cached = await chrome.storage.local.get(["flexie_token"]);
        if (cached.flexie_token) {
          tokenDot.className = "token-dot ok";
          tokenText.textContent = "token cached";
        } else {
          tokenText.textContent = "no token";
          footer.textContent = "Flexie is running but this extension is not paired: restart Flexie once";
        }
      }
      if (paired) footer.textContent = `Connected · ${data.version || "2.0"}`;
    } else {
      throw new Error(res.status);
    }
  } catch (e) {
    statusDot.className  = "dot offline";
    statusText.className = "status-text offline";
    statusText.textContent = "OFFLINE";
    tokenText.textContent = "no token";
    footer.textContent = "Flexie is not running: start it with python main.py (API on port 8768)";
  }
}

checkHealth();
setInterval(checkHealth, 6000);

// Open sidebar
document.getElementById("btnOpenSidebar").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && chrome.sidePanel?.open) {
    chrome.sidePanel.open({ tabId: tab.id });
    window.close();
  }
});

// Open dashboard
document.getElementById("btnOpenDashboard").addEventListener("click", () => {
  chrome.tabs.create({ url: "http://localhost:8766/" });
  window.close();
});

// Mail chips — stash a mail action key and open sidebar
document.querySelectorAll(".chip[data-mail]").forEach(chip => {
  chip.addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      await chrome.storage.local.set({ flexie_pending_mail_cmd: chip.dataset.mail });
      if (chrome.sidePanel?.open) chrome.sidePanel.open({ tabId: tab.id });
      window.close();
    }
  });
});

// DOM quick chips — open sidebar with pre-typed command
document.querySelectorAll(".chip[data-dom]").forEach(chip => {
  chip.addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      // Stash command; sidebar.js picks it up on load via storage
      await chrome.storage.local.set({ flexie_pending_dom_cmd: chip.dataset.dom });
      if (chrome.sidePanel?.open) {
        chrome.sidePanel.open({ tabId: tab.id });
      }
      window.close();
    }
  });
});
