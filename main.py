import logging
import warnings

# SILENCE ALL DEPRECATION WARNINGS IMMEDIATELY
warnings.filterwarnings("ignore", category=FutureWarning)

import os
import subprocess
import sys

from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

MAIN_PATH = os.path.normcase(os.path.abspath(__file__))
API_HOST = "127.0.0.1"
API_PORT = 8768


def _cmdline_runs_main(cmdline, cwd=None) -> bool:
    """True when ``cmdline`` launches THIS main.py (full path match) or flexie.exe.

    A bare substring test on "main.py" matched any unrelated python process
    (some other project's main.py) and refused to start.
    """
    for arg in cmdline or []:
        base = os.path.basename(str(arg)).lower()
        if base == "flexie.exe":
            return True
        if base != "main.py":
            continue
        cand = str(arg)
        if not os.path.isabs(cand) and cwd:
            cand = os.path.join(cwd, cand)
        if os.path.normcase(os.path.abspath(cand)) == MAIN_PATH:
            return True
    return False


def _port_free(host: str, port: int) -> bool:
    """True when nothing is listening/bound on (host, port)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def check_single_instance():
    """Prevents multiple instances of Flexie from running and conflicting over hardware."""
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name']):
            pname = str(proc.info.get('name') or "").lower()
            if pname in ("python.exe", "python", "flexie.exe", "pythonw.exe"):
                try:
                    cmdline = proc.cmdline()
                    if any("--ui" in arg for arg in cmdline):
                        continue
                    if proc.info['pid'] != current_pid and _cmdline_runs_main(cmdline, proc.cwd()):
                        print(f"[Conflict]: Flexie is already running (PID: {proc.info['pid']}).")
                        print("Please close the other instance before starting a new one.")
                        sys.exit(1)
                except Exception as _e:
                    logging.debug("[main.py:39] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    continue
    except Exception as _e:
        logging.debug("[main.py:41] Swallowed exception: %s: %s", type(_e).__name__, _e)
        pass

def run_ui():
    """Lauches the UI as a separate process to ensure it doesn't block the AI."""
    if getattr(sys, "frozen", False):
        return subprocess.Popen([sys.executable, "--ui"], stderr=subprocess.DEVNULL)
    ui_path = os.path.join(os.path.dirname(__file__), "interface", "ui.py")
    # Redirect stderr to DEVNULL to hide Qt rendering warnings (UpdateLayeredWindowIndirect failed)
    return subprocess.Popen([sys.executable, ui_path], stderr=subprocess.DEVNULL)

def _shutdown(assistant, ui_proc):
    """Best-effort teardown that always runs (normal exit, Ctrl+C or a crash)."""
    print("\n[System]: Shutting down Flexie gracefully...")
    # 1. Graceful AI Cleanup
    try:
        if assistant is not None:
            assistant.cleanup()
    except Exception as _e:
        logging.debug("[main.py:shutdown] cleanup failed: %s: %s", type(_e).__name__, _e)

    # 2. Cleanup UI Process (never leave it orphaned)
    if ui_proc:
        try:
            ui_proc.terminate()
            ui_proc.wait(timeout=3)
        except Exception as _e:
            logging.debug("[main.py:shutdown] ui terminate failed: %s: %s", type(_e).__name__, _e)
            try:
                ui_proc.kill()
            except Exception as _e2:
                logging.debug("[main.py:shutdown] ui kill failed: %s", _e2)

    # 3. Final Hard Kill for any zombies (scoped to OUR child processes only)
    try:
        import psutil
        me = psutil.Process(os.getpid())
        child_pids = {c.pid for c in me.children(recursive=True)}
        for proc in psutil.process_iter(['name', 'pid']):
            n = (proc.info['name'] or "").lower()
            if ("playwright" in n or "chrome" in n) and proc.info['pid'] in child_pids:
                try:
                    proc.kill()
                except Exception as _e:
                    logging.debug("[main.py:shutdown] kill failed: %s: %s", type(_e).__name__, _e)
    except Exception as _e:
        logging.debug("[main.py:shutdown] zombie sweep failed: %s: %s", type(_e).__name__, _e)
    print("[System]: Cleanup complete.")


def main():
    # Heavy imports / dependency check happen here (not at import time) so the
    # helpers above are importable and testable.
    from utils.installer import install_missing
    install_missing()
    from core.orchestrator import FlexieOrchestrator

    check_single_instance()
    # Per-run UDP control-plane token shared with child UI/bridge processes
    # (they inherit os.environ) and published to .flexie_udp_token so a bridge
    # started by hand authenticates too. See utils/udp_auth.py.
    import secrets as _secrets
    os.environ.setdefault("FLEXIE_UDP_TOKEN", _secrets.token_urlsafe(24))
    try:
        from utils.udp_auth import publish_token as _publish_token
        _publish_token(os.environ["FLEXIE_UDP_TOKEN"])
    except Exception as _e:
        logging.debug("[main.py:61] Swallowed exception: %s: %s", type(_e).__name__, _e)
    try:
        from utils.udp_auth import reset_ui_ports
        reset_ui_ports()  # drop UI subscriber entries left by a crashed run
    except Exception as _e:
        logging.debug("[main.py] reset_ui_ports failed: %s: %s", type(_e).__name__, _e)
    print("\n" + "="*40)
    print("      F L E X I E   2 . 0   C O R E      ")
    print("="*40)

    # Start UI
    ui_proc = run_ui()
    try:
        _run(ui_proc, FlexieOrchestrator)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown(assistant_holder.get("assistant"), ui_proc)
    sys.exit(0)


assistant_holder: dict = {}


def _run(ui_proc, FlexieOrchestrator):
    # Start Orchestrator
    assistant = FlexieOrchestrator()
    assistant_holder["assistant"] = assistant

    # Start API server for browser extension and external integrations
    if not _port_free(API_HOST, API_PORT):
        logging.error("API server NOT started: %s:%s is already in use "
                      "(another Flexie instance?). The browser extension and REST API are unavailable.",
                      API_HOST, API_PORT)
        print(f"[ERROR] API port {API_PORT} is in use - REST API / extension disabled.")
    else:
        try:
            from interface.api_server import start_api_server_background
            start_api_server_background(host=API_HOST, port=API_PORT, orch=assistant)
        except Exception as _api_err:
            logging.error("API server failed to start: %s: %s", type(_api_err).__name__, _api_err)

    # --- PRODUCTION OVERLAY BRIDGE ---
    from core.controller import FlexieController

    # Store the original logic before wrapping
    original_handle = assistant.handle_command

    # Initialize the controller with the original logic
    controller = FlexieController(assistant, original_handle)

    # Non-destructive overlay: Intercept command calls
    def wrapped_handle(cmd, *args, **kwargs):
        return controller.execute(cmd, *args, **kwargs)

    assistant.handle_command = wrapped_handle
    # ---------------------------------

    assistant.run()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if "--ui" in sys.argv:
        from PyQt6.QtWidgets import QApplication

        from interface.ui import FlexieUI
        app = QApplication(sys.argv)
        ui = FlexieUI()
        ui.show()
        sys.exit(app.exec())
    main()
