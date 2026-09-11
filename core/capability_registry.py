from typing import List, Dict, Callable, Any

class Capability:
    def __init__(self, name: str, intents: List[str]):
        self.name = name
        self.intents = intents
        
    def get_intents(self) -> List[str]:
        return self.intents

class CapabilityRegistry:
    """
    Replaces ATOMIC_ACTIONS with a structured scalable registry of capabilities.
    Each capability groups related intents.
    """
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}
        self._intent_to_capability: Dict[str, str] = {}
        self._register_defaults()
        
    def _register_defaults(self):
        self.register(Capability("camera", ["camera_capture", "take_picture", "open_camera", "save_picture"]))
        self.register(Capability("browser", ["browser_op", "browser_navigate", "browser_control", "multi_tab_research"]))
        self.register(Capability("clipboard", ["copy", "paste"]))
        self.register(Capability("window", ["app_op"]))
        self.register(Capability("volume", ["volume_up", "volume_down"]))
        self.register(Capability("brightness", ["brightness_up", "brightness_down"]))
        self.register(Capability("filesystem", ["file_save", "file_delete", "file_rename", "file_op", "repo_analyzer", "project_explainer", "bug_hunter", "test_generator"]))
        self.register(Capability("network", ["network_check"]))
        self.register(Capability("media", ["media"]))
        self.register(Capability("application", ["click_element", "type_text"]))
        self.register(Capability("sdd", ["sdd_build", "dev_explain"]))
        
    def register(self, capability: Capability):
        self._capabilities[capability.name] = capability
        for intent in capability.get_intents():
            self._intent_to_capability[intent] = capability.name
            
    def get_all_atomic_intents(self) -> set:
        """Returns all atomic intents across all registered capabilities."""
        return set(self._intent_to_capability.keys())

    def get_capability_for_intent(self, intent: str) -> str:
        return self._intent_to_capability.get(intent)
