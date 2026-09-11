import warnings

# SILENCE ALL DEPRECATION WARNINGS IMMEDIATELY
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", module="google.generativeai")

import os
import subprocess
import sys
import time

from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

from utils.installer import install_missing  # noqa: E402

# Run dependency check
install_missing()

from core.orchestrator import FlexieOrchestrator  # noqa: E402


def check_single_instance():
    """Prevents multiple instances of Flexie from running and conflicting over hardware."""
    try:
        import psutil
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] == "python.exe" or proc.info['name'] == "python":
                # Check command line to see if it's main.py
                try:
                    cmdline = proc.cmdline()
                    if any("main.py" in arg for arg in cmdline) and proc.info['pid'] != current_pid:
                        print(f"[Conflict]: Flexie is already running (PID: {proc.info['pid']}).")
                        print("Please close the other instance before starting a new one.")
                        sys.exit(1)
                except Exception:
                    continue
    except Exception:
        pass

def run_ui():
    """Lauches the UI as a separate process to ensure it doesn't block the AI."""
    ui_path = os.path.join(os.path.dirname(__file__), "interface", "ui.py")
    # Redirect stderr to DEVNULL to hide Qt rendering warnings (UpdateLayeredWindowIndirect failed)
    return subprocess.Popen([sys.executable, ui_path], stderr=subprocess.DEVNULL)

def main():
    check_single_instance()
    print("\n" + "="*40)
    print("      F L E X I E   2 . 0   C O R E      ")
    print("="*40)

    # Start UI
    ui_proc = run_ui()

    # Start Orchestrator
    assistant = FlexieOrchestrator()

    # --- PRODUCTION OVERLAY BRIDGE ---
    from core.controller import FlexieController

    # Store the original logic before wrapping
    original_handle = assistant.handle_command

    # Initialize the controller with the original logic
    controller = FlexieController(assistant, original_handle)

    # Non-destructive overlay: Intercept command calls
    def wrapped_handle(cmd, *args, **kwargs):
        return controller.execute(cmd)

    assistant.handle_command = wrapped_handle
    # ---------------------------------

    try:
        assistant.run()
    except KeyboardInterrupt:
        print("\n[System]: Shutting down Flexie gracefully...")
        # 1. Graceful AI Cleanup
        try:
            assistant.cleanup()
        except Exception:
            pass

        # 2. Cleanup UI Process
        if ui_proc:
            try:
                ui_proc.terminate()
            except Exception:
                pass

        # 3. Final Hard Kill for any zombies (scoped to OUR child processes only)
        time.sleep(0.5)  # Give grace period
        try:
            import psutil
            me = psutil.Process(os.getpid())
            child_pids = {c.pid for c in me.children(recursive=True)}
            for proc in psutil.process_iter(['name', 'pid']):
                n = proc.info['name'].lower()
                if ("playwright" in n or "chrome" in n) and proc.info['pid'] in child_pids:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
        print("[System]: Cleanup complete.")
        sys.exit(0)

if __name__ == "__main__":
    main()
