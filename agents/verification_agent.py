import os
from typing import Dict, Any
from agents.base import BaseAgent
from engines.system import SystemCtrl

class VerificationAgent(BaseAgent):
    """Post-execution state assertion agent validating browser, file, and app outcomes."""
    def __init__(self):
        super().__init__("verification", "Execution Quality & State Verifier")

    def execute_task(self, payload: Dict[str, Any]) -> dict:
        expected_state = payload.get("expected_state", {})
        task_id = payload.get("task_id")
        
        self.logger.info(f"VerificationAgent running validation for task {task_id}")
        
        verification_results = {}
        all_passed = True
        
        # 1. File/Folder Verification
        if "file_path" in expected_state:
            path = expected_state["file_path"]
            exists = os.path.exists(path)
            size = os.path.getsize(path) if exists and os.path.isfile(path) else 0
            
            verification_results["file_exists"] = exists
            verification_results["file_size_bytes"] = size
            if not exists or (expected_state.get("non_empty", False) and size == 0):
                all_passed = False
                
        # 2. Window / App Focus Verification
        if "active_window" in expected_state:
            expected_title = expected_state["active_window"].lower()
            current_title = SystemCtrl.get_active_window_title().lower()
            
            focused = any(x in current_title for x in expected_title.split())
            verification_results["app_focused"] = focused
            verification_results["current_window_title"] = current_title
            if not focused:
                all_passed = False
                
        # 3. Clipboard Verification
        if "clipboard_contains" in expected_state:
            expected_text = expected_state["clipboard_contains"]
            current_clip = SystemCtrl.get_clipboard()
            
            match = expected_text in current_clip
            verification_results["clipboard_match"] = match
            if not match:
                all_passed = False

        status = "passed" if all_passed else "failed"
        self.logger.info(f"Verification completed. Outcome: {status.upper()}")
        
        return {
            "status": status,
            "results": verification_results
        }
