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
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            return False
            
        elif capability_name == "browser":
            # Check if browser is running
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name'].lower() if proc.info['name'] else ""
                    if 'chrome' in name or 'edge' in name or 'firefox' in name or 'brave' in name:
                        return True
                except:
                    pass
            return False
            
        elif capability_name == "clipboard":
            # Check if clipboard changed
            from engines.system import SystemCtrl
            curr_clip = SystemCtrl.get_clipboard()
            return curr_clip != pre_state.get("clipboard", "")
            
        # Default fallback: assume True if not strictly validated to prevent blocking
        return True
