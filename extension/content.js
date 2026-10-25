// Flexiee Content Script — Page Extraction & Full DOM Task Executor
// Injected into every page at document_idle.
(function () {
  if (window.__flexie_injected) return;
  window.__flexie_injected = true;

  // ── Helpers ─────────────────────────────────────────────────────────

  /** Strip scripts/styles and return clean inner text (max 8000 chars). */
  function extractPageText() {
    const clone = document.body.cloneNode(true);
    ["script", "style", "noscript", "iframe", "svg"].forEach(sel =>
      clone.querySelectorAll(sel).forEach(el => el.remove())
    );
    return (clone.innerText || clone.textContent || "").replace(/\s+/g, " ").trim().slice(0, 8000);
  }

  /** Collect <pre>/<code> blocks (up to 5, max 1000 chars each). */
  function extractCodeBlocks() {
    const blocks = [];
    document.querySelectorAll("pre, code, .highlight, .snippet").forEach(el => {
      const code = el.innerText.trim();
      if (code && code.length > 20) blocks.push(code.slice(0, 1000));
    });
    return blocks.slice(0, 5);
  }

  /** Serialize a <table> element to a 2-D array of strings. */
  function tableToArray(table) {
    return Array.from(table.rows).map(row =>
      Array.from(row.cells).map(cell => cell.innerText.trim())
    );
  }

  /** Find an element by CSS selector OR visible text content (case-insensitive). */
  function findElement(selectorOrText) {
    // Try as CSS selector first
    try {
      const bySelector = document.querySelector(selectorOrText);
      if (bySelector) return bySelector;
    } catch (_) {}

    // Fall back to visible text match
    const text = selectorOrText.toLowerCase().trim();
    const candidates = document.querySelectorAll(
      "a, button, input, label, [role='button'], [role='link'], [role='menuitem'], summary, [tabindex]"
    );
    for (const el of candidates) {
      if ((el.innerText || el.value || el.getAttribute("aria-label") || "")
            .toLowerCase().trim() === text) return el;
    }
    // Partial match fallback
    for (const el of candidates) {
      if ((el.innerText || "").toLowerCase().includes(text)) return el;
    }
    return null;
  }

  /** Scroll an element into view and click it. */
  function clickElement(el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.focus?.();
    el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("mouseup",   { bubbles: true }));
    el.click();
    el.dispatchEvent(new MouseEvent("click",     { bubbles: true }));
  }

  /** Set an input's value and fire both React and native events. */
  function fillInput(el, value) {
    el.focus?.();
    // React synthetic event support
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement?.prototype || {}, "value"
    )?.set;
    if (nativeInputValueSetter) nativeInputValueSetter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event("input",  { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** Highlight a DOM element with a glowing cyan outline. */
  function highlightElement(el, durationMs = 2500) {
    const prev = el.style.outline;
    el.style.outline = "2px solid #00f2ff";
    el.style.boxShadow = "0 0 12px rgba(0,242,255,0.6)";
    setTimeout(() => { el.style.outline = prev; el.style.boxShadow = ""; }, durationMs);
  }

  // ── Message Handler ──────────────────────────────────────────────────
  chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
    const { type } = request;

    // ── Page data ──
    if (type === "GET_PAGE_DATA") {
      sendResponse({
        title: document.title,
        url: window.location.href,
        selectedText: window.getSelection()?.toString().trim() ?? "",
        pageText: extractPageText(),
        codeBlocks: extractCodeBlocks(),
        meta: {
          description: document.querySelector('meta[name="description"]')?.content ?? "",
          canonical: document.querySelector('link[rel="canonical"]')?.href ?? "",
        },
      });
      return true;
    }

    // ── Click element ──
    if (type === "DOM_CLICK") {
      const el = findElement(request.target);
      if (!el) return sendResponse({ ok: false, error: `Element not found: "${request.target}"` }), true;
      highlightElement(el, 1200);
      try { clickElement(el); } catch (e) { return sendResponse({ ok: false, error: e.message }), true; }
      sendResponse({ ok: true, tag: el.tagName, text: el.innerText?.slice(0, 80) });
      return true;
    }

    // ── Fill a single input ──
    if (type === "DOM_FILL") {
      const el = document.querySelector(request.selector) ||
                 Array.from(document.querySelectorAll("input,textarea")).find(i =>
                   (i.placeholder || i.name || i.id || "").toLowerCase().includes(
                     (request.label || "").toLowerCase()
                   )
                 );
      if (!el) return sendResponse({ ok: false, error: "Input not found" }), true;
      fillInput(el, request.value);
      highlightElement(el, 1500);
      sendResponse({ ok: true });
      return true;
    }

    // ── Fill multiple fields at once ──
    if (type === "DOM_FILL_FORM") {
      // request.fields = [{ selector, value }, …]
      const results = (request.fields || []).map(({ selector, value }) => {
        const el = document.querySelector(selector);
        if (!el) return { selector, ok: false, error: "not found" };
        fillInput(el, value);
        return { selector, ok: true };
      });
      sendResponse({ ok: true, results });
      return true;
    }

    // ── Submit a form ──
    if (type === "DOM_SUBMIT") {
      const form = request.selector
        ? document.querySelector(request.selector)
        : document.querySelector("form");
      if (!form) return sendResponse({ ok: false, error: "Form not found" }), true;
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      const submitBtn = form.querySelector('[type="submit"], button:not([type="button"])');
      if (submitBtn) clickElement(submitBtn);
      sendResponse({ ok: true });
      return true;
    }

    // ── Scroll ──
    if (type === "DOM_SCROLL") {
      if (request.target) {
        const el = findElement(request.target);
        if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); }
        else return sendResponse({ ok: false, error: "Scroll target not found" }), true;
      } else {
        const top = request.top ?? (request.direction === "bottom" ? document.body.scrollHeight : 0);
        window.scrollTo({ top, behavior: "smooth" });
      }
      sendResponse({ ok: true });
      return true;
    }

    // ── Extract all tables ──
    if (type === "DOM_EXTRACT_TABLES") {
      const tables = Array.from(document.querySelectorAll("table")).map((t, i) => ({
        index: i,
        headers: Array.from(t.querySelectorAll("th")).map(th => th.innerText.trim()),
        rows: tableToArray(t),
        caption: t.caption?.innerText?.trim() ?? "",
      }));
      sendResponse({ ok: true, tables });
      return true;
    }

    // ── Extract all links ──
    if (type === "DOM_EXTRACT_LINKS") {
      const links = Array.from(document.querySelectorAll("a[href]")).map(a => ({
        text: a.innerText.trim().slice(0, 100),
        href: a.href,
        title: a.title,
      })).filter(l => l.href && !l.href.startsWith("javascript:"));
      sendResponse({ ok: true, links: links.slice(0, 200) });
      return true;
    }

    // ── Extract structured page metadata ──
    if (type === "DOM_EXTRACT_META") {
      const metas = {};
      document.querySelectorAll("meta").forEach(m => {
        const key = m.name || m.property || m.getAttribute("http-equiv");
        if (key) metas[key] = m.content;
      });
      sendResponse({
        ok: true,
        title: document.title,
        url: window.location.href,
        metas,
        h1s: Array.from(document.querySelectorAll("h1")).map(h => h.innerText.trim()),
        h2s: Array.from(document.querySelectorAll("h2")).map(h => h.innerText.trim()).slice(0, 10),
        images: Array.from(document.querySelectorAll("img[src]")).map(i => ({
          src: i.src, alt: i.alt
        })).slice(0, 20),
      });
      return true;
    }

    // ── Find and highlight text on page ──
    if (type === "DOM_FIND_TEXT") {
      const query = (request.text || "").toLowerCase();
      if (!query) return sendResponse({ ok: false, error: "No text provided" }), true;

      // Use browser built-in if available
      if (window.find) {
        window.find(request.text, false, false, true, false, false, false);
      }
      // Also highlight every matching text node
      let count = 0;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const matches = [];
      let node;
      while ((node = walker.nextNode()) && count < 30) {
        if (node.nodeValue.toLowerCase().includes(query)) {
          const span = document.createElement("mark");
          span.style.backgroundColor = "rgba(0, 242, 255, 0.35)";
          span.style.color = "inherit";
          span.style.borderRadius = "2px";
          const range = document.createRange();
          range.selectNodeContents(node);
          try { range.surroundContents(span); matches.push(node.nodeValue.slice(0, 60)); count++; }
          catch (_) {}
        }
      }
      sendResponse({ ok: true, matchCount: count, previews: matches.slice(0, 5) });
      return true;
    }

    // ── Get element info ──
    if (type === "DOM_GET_ELEMENT") {
      const el = findElement(request.target);
      if (!el) return sendResponse({ ok: false, error: "Element not found" }), true;
      const rect = el.getBoundingClientRect();
      sendResponse({
        ok: true,
        tag: el.tagName,
        id: el.id,
        classes: el.className,
        text: el.innerText?.slice(0, 300),
        value: el.value,
        href: el.href,
        type: el.type,
        disabled: el.disabled,
        rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
        attributes: Object.fromEntries(
          Array.from(el.attributes).map(a => [a.name, a.value])
        ),
      });
      return true;
    }

    // ── Remove element from DOM ──
    if (type === "DOM_REMOVE") {
      const el = findElement(request.target);
      if (!el) return sendResponse({ ok: false, error: "Element not found" }), true;
      el.remove();
      sendResponse({ ok: true });
      return true;
    }

    // ── Inject & show a banner/overlay on the page ──
    if (type === "DOM_INJECT_BANNER") {
      const existing = document.getElementById("flexie-injected-banner");
      if (existing) existing.remove();
      const banner = document.createElement("div");
      banner.id = "flexie-injected-banner";
      Object.assign(banner.style, {
        position: "fixed", top: "0", left: "0", right: "0",
        zIndex: "2147483640",
        background: "rgba(0,10,20,0.92)",
        backdropFilter: "blur(12px)",
        color: "#00f2ff",
        fontFamily: "monospace",
        fontSize: "13px",
        padding: "10px 20px",
        borderBottom: "1px solid rgba(0,242,255,0.3)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      });
      banner.innerHTML = `
        <span>⚡ <strong>Flexie:</strong> ${request.message || ""}</span>
        <button onclick="this.parentElement.remove()" style="
          background:none;border:1px solid #00f2ff;color:#00f2ff;
          cursor:pointer;padding:3px 10px;border-radius:4px;font-size:11px;">✕</button>
      `;
      document.body.prepend(banner);
      if (request.autoDismissMs) setTimeout(() => banner.remove(), request.autoDismissMs);
      sendResponse({ ok: true });
      return true;
    }

    // ── Select all text in an input / contenteditable ──
    if (type === "DOM_SELECT_ALL_IN") {
      const el = document.querySelector(request.selector);
      if (!el) return sendResponse({ ok: false, error: "Element not found" }), true;
      el.focus?.();
      if (el.select) el.select();
      else {
        const r = document.createRange();
        r.selectNodeContents(el);
        const s = window.getSelection();
        s.removeAllRanges(); s.addRange(r);
      }
      sendResponse({ ok: true });
      return true;
    }

    // ── Highlight text (original) ──
    if (type === "HIGHLIGHT_TEXT") {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        const mark = document.createElement("mark");
        mark.style.backgroundColor = "rgba(0, 242, 255, 0.4)";
        mark.style.color = "inherit";
        mark.style.borderRadius = "2px";
        try { mark.appendChild(range.extractContents()); range.insertNode(mark); }
        catch (_) {}
      }
      sendResponse({ ok: true });
      return true;
    }

    // ── Legacy FILL_INPUT ──
    if (type === "FILL_INPUT") {
      const el = document.querySelector(request.selector);
      if (!el) return sendResponse({ ok: false, error: "Element not found" }), true;
      fillInput(el, request.value);
      sendResponse({ ok: true });
      return true;
    }

    // ── Keyboard event injection ──
    if (type === "DOM_KEY") {
      const el = request.selector ? document.querySelector(request.selector) : document.activeElement;
      if (el) {
        el.dispatchEvent(new KeyboardEvent("keydown", { key: request.key, bubbles: true, cancelable: true }));
        el.dispatchEvent(new KeyboardEvent("keyup",   { key: request.key, bubbles: true }));
      }
      sendResponse({ ok: true });
      return true;
    }
  });

  // ── Floating Pill on Text Selection ──────────────────────────────────
  let floatingPill = null;

  document.addEventListener("mouseup", (e) => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 3) {
      if (!floatingPill) {
        floatingPill = document.createElement("div");
        floatingPill.id = "flexie-selection-pill";
        Object.assign(floatingPill.style, {
          position: "fixed", zIndex: "2147483647",
          background: "rgba(3,13,26,0.95)",
          color: "#00f2ff", border: "1px solid rgba(0,242,255,0.5)",
          borderRadius: "8px", padding: "6px 14px 6px 10px",
          fontSize: "12px", fontWeight: "700",
          fontFamily: "'JetBrains Mono', monospace",
          cursor: "pointer",
          boxShadow: "0 0 16px rgba(0,242,255,0.35), 0 4px 20px rgba(0,0,0,0.5)",
          backdropFilter: "blur(10px)",
          display: "flex", alignItems: "center", gap: "6px",
          userSelect: "none", transition: "opacity 0.15s",
        });
        floatingPill.innerHTML = `<span style="font-size:14px">⚡</span> Ask Flexie`;

        floatingPill.addEventListener("click", () => {
          chrome.runtime.sendMessage({
            type: "OPEN_ASSISTANT_FOR_SELECTION",
            text: sel,
            url: window.location.href,
            title: document.title,
          });
          floatingPill?.remove();
          floatingPill = null;
        });
        document.body.appendChild(floatingPill);
      }
      const top  = Math.min(window.innerHeight - 44, e.clientY + 14);
      const left = Math.min(window.innerWidth  - 150, e.clientX + 8);
      floatingPill.style.top  = `${top}px`;
      floatingPill.style.left = `${left}px`;
    } else {
      floatingPill?.remove();
      floatingPill = null;
    }
  });

  // Dismiss pill on Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && floatingPill) { floatingPill.remove(); floatingPill = null; }
  });
})();
