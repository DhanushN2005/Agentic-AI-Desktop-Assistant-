"""
web_ui_bridge.py  –  Flexie 2.0 Web UI Bridge
Relays UDP messages from the Orchestrator  →  WebSocket  →  Browser UI
and browser commands  →  UDP  →  Orchestrator.

Security model:
  - A random auth token is generated per bridge run.
  - The token is ONLY served to localhost via the bridge's own HTTP page
    (embedded into web_ui.html). Cross-origin pages cannot read it because
    the HTTP server sends no CORS headers (browser same-origin policy).
  - Every WebSocket client must send AUTH:<token> as its FIRST message
    before any other traffic is relayed to the Orchestrator.
  - Both HTTP and WebSocket servers bind to 127.0.0.1 only.

Start this INSTEAD of (or alongside) ui.py when you want the HTML/JS UI.
Usage:  python interface/web_ui_bridge.py
"""

import asyncio
import socket
import threading
import os
import secrets
import webbrowser
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging

try:
    import websockets
except ImportError as _e:
    logging.debug("[interface/web_ui_bridge.py:30] Swallowed exception: %s: %s", type(_e).__name__, _e)
    print("[Bridge] Installing websockets...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

# ── Config ─────────────────────────────────────────────────────────────────
ORCHESTRATOR_UDP_IN  = 9887   # bridge sends commands TO orchestrator here
ORCHESTRATOR_UDP_OUT = 9886   # orchestrator sends STATE updates here
WS_PORT              = 8765   # WebSocket port the browser connects to
HTTP_PORT            = 8766   # localhost HTTP port serving the auth'd UI page
HTML_FILE = os.path.join(os.path.dirname(__file__), "web_ui.html")
TOKEN_PLACEHOLDER = "{{AUTH_TOKEN}}"

# ── Shared state ────────────────────────────────────────────────────────────
connected_clients: set = set()   # only AUTHENTICATED clients live here
_loop: asyncio.AbstractEventLoop = None
AUTH_TOKEN: str = secrets.token_urlsafe(24)


# ── HTTP server: serves the UI page with the token injected ────────────────
def _render_html() -> bytes:
    """Read web_ui.html and inject the per-run auth token."""
    try:
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        logging.debug("[interface/web_ui_bridge.py:55] Swallowed exception: %s: %s", type(e).__name__, e)
        html = f"<h1>Bridge error</h1><pre>Cannot read {HTML_FILE}: {e}</pre>"
    return html.replace(TOKEN_PLACEHOLDER, AUTH_TOKEN).encode("utf-8")


class _AuthedUIHandler(BaseHTTPRequestHandler):
    """Serves the token-injected UI page on localhost only. No CORS headers
    are ever sent, so cross-origin pages can fetch but cannot READ the body."""

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        body = _render_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Deliberately NO Access-Control-Allow-Origin header.
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quiet default request logging
        pass


def start_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), _AuthedUIHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[Bridge] UI page served at http://localhost:{HTTP_PORT}/ (token embedded)")


# ── UDP → WebSocket relay ────────────────────────────────────────────────────
def udp_listener():
    """Listen for state updates from the Orchestrator and forward to all WS clients."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", ORCHESTRATOR_UDP_OUT))
    print(f"[Bridge] Listening for Orchestrator UDP on :{ORCHESTRATOR_UDP_OUT}")

    while True:
        try:
            data, _ = sock.recvfrom(65535)
            msg = data.decode("utf-8")
            asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)
        except Exception as e:
            logging.debug("[interface/web_ui_bridge.py:99] Swallowed exception: %s: %s", type(e).__name__, e)
            print(f"[Bridge] UDP recv error: {e}")


async def _broadcast(msg: str):
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send(msg)
        except Exception as _e:
            logging.debug("[interface/web_ui_bridge.py:108] Swallowed exception: %s: %s", type(_e).__name__, _e)
            dead.add(ws)
    connected_clients.difference_update(dead)


# ── WebSocket → UDP relay (with auth handshake) ─────────────────────────────
MAX_AUTH_ATTEMPTS = 3


async def _authenticate(websocket) -> bool:
    """Require AUTH:<token> as the first message(s). Closes socket on failure."""
    for attempt in range(MAX_AUTH_ATTEMPTS):
        try:
            first = await asyncio.wait_for(websocket.recv(), timeout=10)
        except (asyncio.TimeoutError, Exception) as _e:
            logging.debug("[interface/web_ui_bridge.py:122] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return False
        if first == f"AUTH:{AUTH_TOKEN}":
            return True
        print(f"[Bridge] Rejected bad auth attempt #{attempt + 1}")
    return False


async def ws_handler(websocket):
    """Handle messages from the browser and forward to the Orchestrator.

    Until the client authenticates, NOTHING is relayed and nothing is
    broadcast to it — unauthenticated peers are invisible.
    """
    if not await _authenticate(websocket):
        try:
            await websocket.close(code=4001, reason="auth failed")
        except Exception as _e:
            logging.debug("[interface/web_ui_bridge.py:139] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass
        return

    await websocket.send("AUTH_OK")
    connected_clients.add(websocket)
    print(f"[Bridge] Authenticated browser connected. Total clients: {len(connected_clients)}")
    try:
        async for message in websocket:
            _send_udp(message)
    except Exception as _e:
        logging.debug("[interface/web_ui_bridge.py:149] Swallowed exception: %s: %s", type(_e).__name__, _e)
        pass
    finally:
        connected_clients.discard(websocket)
        print(f"[Bridge] Browser disconnected. Total clients: {len(connected_clients)}")


def _send_udp(msg: str):
    # Authenticate on the orchestrator control plane. The token is shared
    # via FLEXIE_UDP_TOKEN (set by main.py); without it the orchestrator
    # rejects the datagram. See utils/udp_auth.py.
    try:
        from utils.udp_auth import pack as _udp_pack
        msg = _udp_pack(msg)
    except Exception as _e:
        logging.debug("[interface/web_ui_bridge.py:_send_udp] Swallowed exception: %s: %s", type(_e).__name__, _e)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(msg.encode("utf-8"), ("127.0.0.1", ORCHESTRATOR_UDP_IN))
    finally:
        sock.close()


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    global _loop
    _loop = asyncio.get_event_loop()

    threading.Thread(target=udp_listener, daemon=True).start()
    start_http_server()

    if not os.getenv("FLEXIE_UDP_TOKEN"):
        print("[Bridge] WARNING: FLEXIE_UDP_TOKEN not set — start the bridge from "
              "main.py, or orchestrator UDP commands will be rejected.")

    webbrowser.open(f"http://localhost:{HTTP_PORT}/")
    print(f"[Bridge] Opened browser at: http://localhost:{HTTP_PORT}/")

    print(f"[Bridge] WebSocket server running on ws://localhost:{WS_PORT}")
    async with websockets.serve(ws_handler, "127.0.0.1", WS_PORT):
        await asyncio.Future()   # run forever


if __name__ == "__main__":
    asyncio.run(main())
