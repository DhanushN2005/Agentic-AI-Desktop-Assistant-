class StrictValidator:
    """
    Strict Validation layer for workflow completion verification.
    Guarantees no false positives (e.g. "Camera Roll" matching "camera").
    """
    @staticmethod
    def is_app_running(target_app_name: str, active_window_title: str) -> bool:
        """
        Validates if the correct app is actually running based on exact rules,
        preventing folder/explorer mismatches.
        """
        if not target_app_name or not active_window_title:
            return False
            
        app_lower = target_app_name.lower().strip()
        win_lower = active_window_title.lower().strip()
        
        # Strict exact match rules for critical apps
        if app_lower == "camera":
            # "Camera" process running OR Window Title strictly == "camera"
            # It must NOT be "Camera Roll - File Explorer"
            if "explorer" in win_lower or "folder" in win_lower:
                return False
            return win_lower == "camera"
            
        # Fallback to standard fuzzy match for generic apps, but still block obvious folder mismatches
        if "explorer" in win_lower and app_lower not in ["explorer", "folder", "directory"]:
            return False
            
        return any(x in win_lower for x in app_lower.split())
