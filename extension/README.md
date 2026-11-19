# Flexie Chrome/Edge Browser Extension

A Manifest V3 browser extension integrating Flexie directly into Google Chrome, Microsoft Edge, Brave, and other Chromium browsers. (Tested in a real Chromium with the extension loaded unpacked: pairing, token, a command and page-assist. Not yet tested: the selection pill, context menus, the side panel in your own Chrome, voice dictation.)

## Capabilities

1. **Ask Flexie About This Page**: Summarize, extract takeaways, or answer questions with page context (page text is truncated to 4,000 characters on the client).
2. **Floating "Ask Flexie" Pill** (`content.js`): Appears on text selection to explain, rewrite, or debug.
3. **Context Menus** (`background.js`): Right-click on any webpage, image, or code snippet to analyze with Flexie; extracted data is merged into the stored context and shown in the sidebar.
4. **Voice Dictation** (`sidebar.js`): Uses the browser's built-in speech recognition in the sidebar for hands-free queries.
5. **Direct Backend Link**: Relays requests to the authenticated REST API at `http://127.0.0.1:8768` (`interface/api_server.py`).
6. **Permission Controls**: Sensitive actions are approved through `/api/flexie/approve` and `/reject`, which require the id of a pending approval request.

## How it talks to Flexie

- **Token and pairing:** Chrome sends **no `Origin` header** on requests from an extension's own pages, so Flexie cannot recognise the extension by origin. Instead Flexie writes a random per-install key to `extension/pairing.key` (git-ignored; created when the API starts). The service worker, sidebar and popup read their own copy (`chrome.runtime.getURL("pairing.key")`) and send it as `X-Flexie-Pairing` on `GET /health`; only then does the API return the bearer token. Web pages cannot send that header (it is not in the CORS allow-list) or read the file, and other extensions cannot read this extension's files. No environment variable is needed. The extension also has a fixed ID (`mhamnndilobijpbcpjfacaeiadnlffom`, derived from the `key` in `manifest.json`).
- **Status badge:** `ONLINE` means Flexie answered AND issued a token; `NOT PAIRED` means Flexie is running but did not accept the extension (restart Flexie once so it creates the key); `OFFLINE` means nothing answered on port 8768.
- **Endpoint allow-list:** `CALL_API` messages are validated before any request is made: the path must start with `/`, contain no `@`, backslash, `//`, `..` or encoded dots/slashes, and match the allow-list (`/health`, `/page-assist`, `/command`, `/api/flexie|jarvis/{status,usage,jobs,commands,events,page-assistant,approve,reject}`, `/api/flexie/mail/*`).
- **Privileged calls:** `/command`, `/commands`, `/approve`, `/reject` and the mail send/reply/delete/archive/move/draft endpoints are refused when they come from a content script; `sender.id` must equal the extension's own id.
- **Server limits:** request fields are length-limited (422 when exceeded), a full command queue returns 429, at most 8 SSE clients are served, and mail **send and reply wait for an explicit approval** (HTTP 403 if none arrives; wait set by `FLEXIE_MAIL_APPROVAL_WAIT`, default 60 s).
- **Host permissions** (`manifest.json`): `http://127.0.0.1:8768/*` and `http://localhost:8768/*`.

## Flexie reads and controls your current tab (polling channel)

Flexie cannot push into a browser extension, so the extension **polls** Flexie. `background.js` long-polls `GET /api/flexie/extension/poll?wait=20` (Bearer token), runs the task it receives, and answers with `POST /api/flexie/extension/result`. Flexie's side is `core/extension_bridge.py` (in-memory queue, 30 s task lifetime, 20 pending at most); `GET /api/flexie/extension/status` shows whether the extension is connected (it polled within 45 s). Tabs that were open before the extension was installed need a reload.

**Voice/text commands** (must name "this page", "this tab", "current tab" or "my tabs" so they never hit Flexie's own browser):

| Say | Task | Needs confirmation |
|---|---|---|
| "what tab am I on", "list my tabs" | `active_tab`, `list_tabs` | no |
| "read / summarize this page", "what is this page about" | `read_page` (text is wrapped as untrusted data before the model sees it) | no |
| "find pricing on this page", "extract tables / links from this page", "scroll down on this page" | `find_text`, `extract_tables`, `extract_links`, `scroll` | no |
| "click sign in on this page", "type hello in the search box on this page", "press enter on this page", "submit the form on this page", "go to github.com in this tab" | `click`, `fill`, `key`, `submit`, `navigate` | **yes** |

**Can it do DOM control? Yes.** Click, fill, key presses, scroll, submit, find and extraction run through the existing `content.js` toolkit. Safeguards: act-commands go through the permission system (USER_CONFIRMATION); password, card, code/OTP and similar fields are refused; navigation is http/https only; typed values are never spoken back; page text is untrusted and cannot trigger actions; tasks older than 28 s are dropped.

## Installation in Chrome / Edge

1. Open your browser and navigate to `chrome://extensions/` or `edge://extensions/`.
2. Toggle **Developer mode** (top right switch).
3. Click **Load unpacked**.
4. Select this directory:
   ```text
   e:\HACKATHON\flexiee\flexie_v2\extension
   ```
5. (Nothing to configure: the extension has a fixed ID and pairs itself with Flexie by the key file above.)
6. Start Flexie (`python main.py`). If port 8768 is taken, `main.py` logs an error and the REST API (and therefore the extension) stays disabled.
7. Pin the **Flexie** icon in your browser toolbar.
8. Click the icon and select **Open Flexie Sidebar**.

If the sidebar says `OFFLINE`, check that Flexie is running and port 8768 is free. If it says `NOT PAIRED`, restart Flexie once (it creates `extension/pairing.key`).
