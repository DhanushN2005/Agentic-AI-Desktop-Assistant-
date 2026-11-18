# Flexie Chrome/Edge Browser Extension

A Manifest V3 browser extension integrating Flexie directly into Google Chrome, Microsoft Edge, Brave, and other Chromium browsers. (Written against the code; it has not been exercised in a live browser install as part of the latest documentation update.)

## Capabilities

1. **Ask Flexie About This Page**: Summarize, extract takeaways, or answer questions with page context (page text is truncated to 4,000 characters on the client).
2. **Floating "Ask Flexie" Pill** (`content.js`): Appears on text selection to explain, rewrite, or debug.
3. **Context Menus** (`background.js`): Right-click on any webpage, image, or code snippet to analyze with Flexie; extracted data is merged into the stored context and shown in the sidebar.
4. **Voice Dictation** (`sidebar.js`): Uses the browser's built-in speech recognition in the sidebar for hands-free queries.
5. **Direct Backend Link**: Relays requests to the authenticated REST API at `http://127.0.0.1:8768` (`interface/api_server.py`).
6. **Permission Controls**: Sensitive actions are approved through `/api/flexie/approve` and `/reject`, which require the id of a pending approval request.

## How it talks to Flexie

- **Token:** the background service worker fetches `GET /health` every 30 seconds. The API returns a bearer token **only** when the request's `Origin` is trusted: the dashboard origins, `chrome-extension://<id>` for each ID in `FLEXIE_EXTENSION_IDS`, and any `http(s)` origin listed in `FLEXIE_EXTRA_ORIGINS`. Without your extension ID in `FLEXIE_EXTENSION_IDS` the extension stays offline.
- **Endpoint allow-list:** `CALL_API` messages are validated before any request is made: the path must start with `/`, contain no `@`, backslash, `//`, `..` or encoded dots/slashes, and match the allow-list (`/health`, `/page-assist`, `/command`, `/api/flexie|jarvis/{status,usage,jobs,commands,events,page-assistant,approve,reject}`, `/api/flexie/mail/*`).
- **Privileged calls:** `/command`, `/commands`, `/approve`, `/reject` and the mail send/reply/delete/archive/move/draft endpoints are refused when they come from a content script; `sender.id` must equal the extension's own id.
- **Server limits:** request fields are length-limited (422 when exceeded), a full command queue returns 429, at most 8 SSE clients are served, and mail **send and reply wait for an explicit approval** (HTTP 403 if none arrives; wait set by `FLEXIE_MAIL_APPROVAL_WAIT`, default 60 s).
- **Host permissions** (`manifest.json`): `http://127.0.0.1:8768/*` and `http://localhost:8768/*`.

## Installation in Chrome / Edge

1. Open your browser and navigate to `chrome://extensions/` or `edge://extensions/`.
2. Toggle **Developer mode** (top right switch).
3. Click **Load unpacked**.
4. Select this directory:
   ```text
   e:\HACKATHON\flexiee\flexie_v2\extension
   ```
5. Copy the extension ID shown on `chrome://extensions/` and set it before starting Flexie, so the backend trusts it (the API token is only issued to trusted origins):
   ```text
   set FLEXIE_EXTENSION_IDS=<your-extension-id>
   ```
6. Start Flexie (`python main.py`). If port 8768 is taken, `main.py` logs an error and the REST API (and therefore the extension) stays disabled.
7. Pin the **Flexie** icon in your browser toolbar.
8. Click the icon and select **Open Flexie Sidebar**.

If the sidebar says it cannot reach Flexie, check that Flexie is running, that port 8768 is free, and that `FLEXIE_EXTENSION_IDS` contains your extension's ID.
