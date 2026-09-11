"""
web_ui_bridge.py  –  Flexie 2.0 Web UI Bridge
Relays UDP messages from the Orchestrator  →  WebSocket  →  Browser UI
and browser commands  →  UDP  →  Orchestrator.

Start this INSTEAD of (or alongside) ui.py when you want the HTML/JS UI.
Usage:  python interface/web_ui_bridge.py
"""

import asyncio
import socket
import threading
import json
import os
import webbrowser
import sys

try:
    import websockets
except ImportError:
    print("[Bridge] Installing websockets...")
    os.system(f"{sys.executable} -m pip install websockets")
    import websockets

# ── Config ─────────────────────────────────────────────────────────────────
ORCHESTRATOR_UDP_IN  = 9887   # bridge sends commands TO orchestrator here
ORCHESTRATOR_UDP_OUT = 9886   # orchestrator sends STATE updates here
WS_PORT              = 8765   # WebSocket port the browser connects to
HTML_FILE = os.path.join(os.path.dirname(__file__), "web_ui.html")

# ── Shared state ────────────────────────────────────────────────────────────
connected_clients: set = set()
_loop: asyncio.AbstractEventLoop = None


# ── UDP → WebSocket relay ────────────────────────────────────────────────────
def udp_listener():
    """Listen for state updates from the Orchestrator and forward to all WS clients."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", ORCHESTRATOR_UDP_OUT))
    print(f"[Bridge] Listening for Orchestrator UDP on :{ORCHESTRATOR_UDP_OUT}")

    while True:
        try:
            data, _ = sock.recvfrom(4096)
            msg = data.decode("utf-8")
            # Forward to all connected browser clients
            asyncio.run_coroutine_threadsafe(_broadcast(msg), _loop)
        except Exception as e:
            print(f"[Bridge] UDP recv error: {e}")


async def _broadcast(msg: str):
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send(msg)
        except Exception:
            dead.add(ws)
    connected_clients.difference_update(dead)


# ── WebSocket → UDP relay ────────────────────────────────────────────────────
async def ws_handler(websocket):
    """Handle messages from the browser and forward to the Orchestrator."""
    connected_clients.add(websocket)
    print(f"[Bridge] Browser connected. Total clients: {len(connected_clients)}")
    try:
        async for message in websocket:
            _send_udp(message)
    except Exception:
        pass
    finally:
        connected_clients.discard(websocket)
        print(f"[Bridge] Browser disconnected. Total clients: {len(connected_clients)}")


def _send_udp(msg: str):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(msg.encode("utf-8"), ("127.0.0.1", ORCHESTRATOR_UDP_IN))
    sock.close()


# ── Main ─────────────────────────────────────────────────────────────────────
async def main():
    global _loop
    _loop = asyncio.get_event_loop()

    # Start UDP listener in background thread
    t = threading.Thread(target=udp_listener, daemon=True)
    t.start()

    # Open browser
    webbrowser.open(f"file:///{HTML_FILE.replace(os.sep, '/')}")
    print(f"[Bridge] Opened browser at: {HTML_FILE}")

    # Start WebSocket server
    print(f"[Bridge] WebSocket server running on ws://localhost:{WS_PORT}")
    async with websockets.serve(ws_handler, "localhost", WS_PORT):
        await asyncio.Future()   # run forever


if __name__ == "__main__":
    asyncio.run(main())
