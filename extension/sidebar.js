// Flexiee Sidebar Logic
let activeTab = null;
let pageData = { title: "", url: "", pageText: "", selectedText: "", codeBlocks: [] };

const chatFeed = document.getElementById("chatFeed");
const userInput = document.getElementById("userInput");
const btnSend = document.getElementById("btnSend");
const btnVoice = document.getElementById("btnVoice");
const statusBadge = document.getElementById("connectionStatus");

const pageTitle = document.getElementById("pageTitle");
const pageUrl = document.getElementById("pageUrl");

// Check connection to Flexiee Backend
function checkConnection() {
  chrome.runtime.sendMessage({ type: "CALL_API", endpoint: "/health", method: "GET" }, (res) => {
    if (res && res.ok) {
      statusBadge.textContent = "ONLINE";
      statusBadge.className = "status-badge online";
    } else {
      statusBadge.textContent = "OFFLINE";
      statusBadge.className = "status-badge";
    }
  });
}

// Fetch active tab and its extracted content
async function refreshPageData() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs.length === 0) return;
  activeTab = tabs[0];

  pageTitle.textContent = activeTab.title || "Untitled Tab";
  pageUrl.textContent = activeTab.url || "";

  chrome.tabs.sendMessage(activeTab.id, { type: "GET_PAGE_DATA" }, (res) => {
    if (chrome.runtime.lastError || !res) {
      return;
    }
    pageData = res;
    pageTitle.textContent = pageData.title;
    pageUrl.textContent = pageData.url;
  });
}

function addMessage(sender, text) {
  const msg = document.createElement("div");
  msg.className = `msg ${sender}`;
  msg.textContent = text;
  chatFeed.appendChild(msg);
  chatFeed.scrollTop = chatFeed.scrollHeight;
  return msg;
}

async function askFlexie(query, action = "ask") {
  addMessage("user", query);
  const loadingMsg = addMessage("flexie", "Analyzing...");

  chrome.runtime.sendMessage({
    type: "CALL_API",
    endpoint: "/api/flexie/page-assistant",
    method: "POST",
    body: {
      query,
      url: pageData.url,
      title: pageData.title,
      page_content: pageData.pageText,
      selected_text: pageData.selectedText,
      action,
    }
  }, (res) => {
    if (res && res.ok && res.data && res.data.answer) {
      loadingMsg.textContent = res.data.answer;
    } else {
      loadingMsg.textContent = res && res.error
        ? `Error connecting to Flexie backend: ${res.error}. Make sure Flexie API is running on port 8768.`
        : "No response received from Flexie.";
    }
    chatFeed.scrollTop = chatFeed.scrollHeight;
  });
}

// Event Listeners
btnSend.addEventListener("click", () => {
  const q = userInput.value.trim();
  if (!q) return;
  userInput.value = "";
  askFlexie(q);
});

userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const q = userInput.value.trim();
    if (!q) return;
    userInput.value = "";
    askFlexie(q);
  }
});

// Quick action chips
document.getElementById("btnSummarize").addEventListener("click", () => {
  askFlexie("Summarize the content of this webpage into 3 concise paragraphs.", "summarize");
});

document.getElementById("btnKeyPoints").addEventListener("click", () => {
  askFlexie("Extract the key takeaways, main ideas, and crucial action points from this page as a bulleted list.", "extract");
});

document.getElementById("btnDebugCode").addEventListener("click", () => {
  const codeContext = pageData.codeBlocks.length > 0 ? pageData.codeBlocks.join("\n\n") : pageData.selectedText;
  if (!codeContext) {
    askFlexie("Inspect this page for any errors, stack traces, or technical anomalies.", "explain_code");
  } else {
    askFlexie(`Analyze this code from the page for potential bugs and explain how to fix them:\n${codeContext}`, "explain_code");
  }
});

document.getElementById("btnResearch").addEventListener("click", () => {
  askFlexie(`Perform research across related topics for '${pageData.title}' and compile a technical synthesis.`, "research");
});

// Voice Input support via SpeechRecognition
let recognition = null;
if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    btnVoice.classList.add("recording");
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    userInput.value = transcript;
    btnVoice.classList.remove("recording");
    askFlexie(transcript);
  };

  recognition.onerror = () => {
    btnVoice.classList.remove("recording");
  };

  recognition.onend = () => {
    btnVoice.classList.remove("recording");
  };

  btnVoice.addEventListener("click", () => {
    if (btnVoice.classList.contains("recording")) {
      recognition.stop();
    } else {
      recognition.start();
    }
  });
} else {
  btnVoice.style.display = "none";
}

// Initial boot
checkConnection();
refreshPageData();
setInterval(refreshPageData, 3000);
