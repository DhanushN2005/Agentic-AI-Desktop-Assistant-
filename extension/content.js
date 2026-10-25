// Flexiee Content Script - Page Extraction & In-Page Assistant
(function () {
  if (window.__flexie_injected) return;
  window.__flexie_injected = true;

  function extractPageText() {
    // Clone body to strip script/style tags
    const clone = document.body.cloneNode(true);
    const removeSelectors = ["script", "style", "noscript", "iframe", "svg"];
    removeSelectors.forEach(sel => {
      clone.querySelectorAll(sel).forEach(el => el.remove());
    });
    return (clone.innerText || clone.textContent || "").replace(/\s+/g, " ").trim();
  }

  function extractCodeBlocks() {
    const blocks = [];
    document.querySelectorAll("pre, code, .highlight, .snippet").forEach(el => {
      const code = el.innerText.trim();
      if (code && code.length > 20) {
        blocks.push(code.slice(0, 1000));
      }
    });
    return blocks.slice(0, 5);
  }

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "GET_PAGE_DATA") {
      sendResponse({
        title: document.title,
        url: window.location.href,
        selectedText: window.getSelection() ? window.getSelection().toString().trim() : "",
        pageText: extractPageText().slice(0, 8000),
        codeBlocks: extractCodeBlocks(),
      });
      return true;
    }

    if (request.type === "HIGHLIGHT_TEXT") {
      const selection = window.getSelection();
      if (selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        const span = document.createElement("mark");
        span.style.backgroundColor = "rgba(0, 242, 255, 0.4)";
        span.style.color = "inherit";
        span.appendChild(range.extractContents());
        range.insertNode(span);
      }
      sendResponse({ success: true });
      return true;
    }

    if (request.type === "FILL_INPUT") {
      const { selector, value } = request;
      const el = document.querySelector(selector);
      if (el) {
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        sendResponse({ success: true });
      } else {
        sendResponse({ success: false, error: "Element not found" });
      }
      return true;
    }
  });

  // Floating Action Pill on text selection
  let floatingPill = null;

  document.addEventListener("mouseup", (e) => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 3) {
      if (!floatingPill) {
        floatingPill = document.createElement("div");
        floatingPill.id = "flexie-selection-pill";
        floatingPill.innerText = "⚡ Ask Flexie";
        Object.assign(floatingPill.style, {
          position: "fixed",
          zIndex: "2147483647",
          backgroundColor: "#030d1a",
          color: "#00f2ff",
          border: "1px solid #00f2ff",
          borderRadius: "6px",
          padding: "5px 12px",
          fontSize: "12px",
          fontWeight: "bold",
          fontFamily: "monospace",
          cursor: "pointer",
          boxShadow: "0 0 12px rgba(0, 242, 255, 0.5)",
          backdropFilter: "blur(8px)",
          userSelect: "none",
        });

        floatingPill.addEventListener("click", () => {
          chrome.runtime.sendMessage({
            type: "OPEN_ASSISTANT_FOR_SELECTION",
            text: sel,
            url: window.location.href,
            title: document.title,
          });
          if (floatingPill) floatingPill.remove();
          floatingPill = null;
        });
        document.body.appendChild(floatingPill);
      }

      floatingPill.style.top = `${Math.min(window.innerHeight - 40, e.clientY + 12)}px`;
      floatingPill.style.left = `${Math.min(window.innerWidth - 120, e.clientX + 10)}px`;
    } else {
      if (floatingPill) {
        floatingPill.remove();
        floatingPill = null;
      }
    }
  });
})();
