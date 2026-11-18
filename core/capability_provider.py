import importlib.util
import logging
import os
import re
import sys

from core.capability_registry import CapabilityRegistry

PLUGIN_OPT_IN_ENV = "FLEXIE_ALLOW_PLUGINS"
PLUGIN_ALLOWLIST_FILE = "allowed_plugins.txt"
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class PluginDiscovery:
    """
    Scans the plugins directory and registers new capabilities into the CapabilityRegistry.

    A plugin is arbitrary code that runs inside Flexie, so loading is OPT-IN:
      * only top-level ``<plugins_dir>/<name>.py`` files are considered (no recursion, no
        packages, no symlinks) and they are loaded BY FILE PATH (never via ``sys.path``);
      * a plugin loads only if it is listed in ``<plugins_dir>/allowed_plugins.txt`` (one name
        per line), or ``FLEXIE_ALLOW_PLUGINS=1`` is set explicitly. With neither, nothing loads.
    """
    def __init__(self, registry: CapabilityRegistry, plugins_dir: str = "plugins"):
        self.registry = registry
        self.plugins_dir = plugins_dir
        self.logger = logging.getLogger("Flexie.PluginDiscovery")

    def _allowed_names(self) -> set[str] | None:
        """None => everything allowed (explicit env opt-in); set => only these names."""
        if os.getenv(PLUGIN_OPT_IN_ENV, "0") == "1":
            return None
        path = os.path.join(self.plugins_dir, PLUGIN_ALLOWLIST_FILE)
        names: set[str] = set()
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if line.endswith(".py"):
                        line = line[:-3]
                    if line and _PLUGIN_NAME_RE.match(line):
                        names.add(line)
        except OSError:
            pass
        return names

    def discover_and_register(self):
        """Load allowed top-level plugin files exposing ``register_capabilities(registry)``."""
        if not os.path.isdir(self.plugins_dir):
            self.logger.warning(f"[PLUGIN] Directory '{self.plugins_dir}' does not exist.")
            return

        allowed = self._allowed_names()
        if allowed is not None and not allowed:
            self.logger.info("[PLUGIN] No plugins enabled (add names to %s/%s or set %s=1)",
                             self.plugins_dir, PLUGIN_ALLOWLIST_FILE, PLUGIN_OPT_IN_ENV)
            return

        real_dir = os.path.realpath(self.plugins_dir)
        for entry in sorted(os.listdir(self.plugins_dir)):
            stem, ext = os.path.splitext(entry)
            if ext != ".py" or stem == "__init__" or not _PLUGIN_NAME_RE.match(stem):
                continue
            if allowed is not None and stem not in allowed:
                self.logger.info("[PLUGIN] Skipping '%s' (not in allowlist)", stem)
                continue
            full = os.path.join(self.plugins_dir, entry)
            real = os.path.realpath(full)
            if os.path.islink(full) or os.path.dirname(real) != real_dir or not os.path.isfile(real):
                self.logger.warning("[PLUGIN] Skipping '%s' (symlink or outside the plugins directory)", entry)
                continue
            module_name = f"flexie_plugin_{stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, real)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise
                if hasattr(module, 'register_capabilities'):
                    module.register_capabilities(self.registry)
                    self.logger.info(f"[PLUGIN] Successfully registered capabilities from '{stem}'")
            except Exception as e:
                self.logger.error(f"[PLUGIN] Error loading plugin '{stem}': {e}")
