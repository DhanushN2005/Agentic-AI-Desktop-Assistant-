import logging


class CapabilityValidator:
    """
    Validates if a Capability execution was successful based on outcomes rather than generic window names.
    """
    def __init__(self):
        pass

    def validate(self, capability_name: str, step_lower: str, pre_state: dict) -> bool:
        """
        Outcome-based validation for capabilities.
        Returns True if successful, False if failed.
        """
        import psutil

        if capability_name == "camera":
            # Check if camera process is running or API is active
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and 'camera' in proc.info['name'].lower():
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as _e:
                    logging.debug("[verification/capability_validator.py:24] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass
            return False

        elif capability_name == "browser":
            # Check if browser is running
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name'].lower() if proc.info['name'] else ""
                    if 'chrome' in name or 'edge' in name or 'firefox' in name or 'brave' in name:
                        return True
                except Exception as _e:
                    logging.debug("[verification/capability_validator.py:32] Swallowed exception: %s: %s", type(_e).__name__, _e)
            return False

        elif capability_name == "clipboard":
            # Check if clipboard changed
            try:
                from engines.system import SystemCtrl
                curr_clip = SystemCtrl.get_clipboard()
            except Exception as _e:
                logging.debug("[verification/capability_validator.py] Swallowed exception: %s: %s", type(_e).__name__, _e)
                return False  # no signal -> fail closed, do not assume success
            return curr_clip != pre_state.get("clipboard", "")

        elif capability_name in ("filesystem", "file", "file_op"):
            import os
            for key in ("last_path", "path", "file", "active_document"):
                p = pre_state.get(key)
                if p and isinstance(p, str) and os.path.exists(p):
                    return True
            # Fall back to step text: extract quoted path and check existence
            import re as _re
            m = _re.search(r'["\']([A-Z]:\\\\[^"\']+|/[^"\']+|[\w\-./\\]+\.\w+)["\']', step_lower)
            if m and os.path.exists(m.group(1)):
                return True
            return False  # fail closed: unverified file claims must not pass

        elif capability_name in ("application", "app_op", "window"):
            # Generic app check: any non-explorer window title token match
            title = str(pre_state.get("window_title", "") or pre_state.get("active_window", "")).lower()
            if not title:
                return False  # no signal -> fail closed, do not assume success
            if "explorer" in title:
                return False
            return True

        # Default fallback: fail closed unless a branch above explicitly passed.
        return False
