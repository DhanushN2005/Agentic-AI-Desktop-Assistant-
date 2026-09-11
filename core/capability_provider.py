import importlib
import pkgutil
import logging
import os
from core.capability_registry import CapabilityRegistry, Capability

class PluginDiscovery:
    """
    Scans the plugins directory and dynamically discovers and registers
    new capabilities into the CapabilityRegistry without requiring manual
    router updates.
    """
    def __init__(self, registry: CapabilityRegistry, plugins_dir: str = "plugins"):
        self.registry = registry
        self.plugins_dir = plugins_dir
        self.logger = logging.getLogger("Flexie.PluginDiscovery")
        
    def discover_and_register(self):
        """
        Looks for Python modules inside the plugins directory that expose a
        `register_capabilities(registry)` function.
        """
        if not os.path.exists(self.plugins_dir):
            self.logger.warning(f"[PLUGIN] Directory '{self.plugins_dir}' does not exist.")
            return
            
        for root, dirs, files in os.walk(self.plugins_dir):
            for file in files:
                if file.endswith(".py") and file != "__init__.py":
                    module_name = f"{self.plugins_dir}.{file[:-3]}"
                    try:
                        module = importlib.import_module(module_name)
                        if hasattr(module, 'register_capabilities'):
                            module.register_capabilities(self.registry)
                            self.logger.info(f"[PLUGIN] Successfully registered capabilities from '{module_name}'")
                    except Exception as e:
                        self.logger.error(f"[PLUGIN] Error loading plugin '{module_name}': {e}")
