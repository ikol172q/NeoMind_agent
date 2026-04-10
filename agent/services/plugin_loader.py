"""Plugin System — Load user plugins from ~/.neomind/plugins/.

Each plugin is a Python file (.py) in ~/.neomind/plugins/ that exposes a
`register(tool_registry)` function. The register function adds custom tools
to the tool registry so the agentic loop can use them.

Plugin file example (~/.neomind/plugins/my_tool.py):

    def register(tool_registry):
        from agent.coding.tool_schema import ToolDefinition, ToolParam, PermissionLevel
        tool_registry.register_tool(ToolDefinition(
            name="my_custom_tool",
            description="Does something useful",
            parameters=[ToolParam("input", "string", "The input text")],
            permission_level=PermissionLevel.READ,
            execute=lambda input: ToolResult(True, output=f"Got: {input}"),
        ))

Slash commands:
    /plugin list   — show loaded plugins
    /plugin reload — rescan and reload all plugins
"""

import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path.home() / ".neomind" / "plugins"


class PluginInfo:
    """Metadata about a loaded plugin."""

    __slots__ = ("name", "path", "module", "loaded", "error")

    def __init__(self, name: str, path: Path, module: Any = None,
                 loaded: bool = False, error: str = ""):
        self.name = name
        self.path = path
        self.module = module
        self.loaded = loaded
        self.error = error

    def __repr__(self):
        status = "loaded" if self.loaded else f"error: {self.error}"
        return f"PluginInfo({self.name}, {status})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "loaded": self.loaded,
            "error": self.error,
        }


class PluginLoader:
    """Discovers and loads plugins from the plugins directory.

    Usage:
        loader = PluginLoader()
        loader.load_all(tool_registry)  # on startup
        loader.reload_all(tool_registry)  # on /plugin reload

        for info in loader.list_plugins():
            print(info)
    """

    def __init__(self, plugins_dir: Optional[Path] = None):
        self._plugins_dir = plugins_dir or PLUGINS_DIR
        self._plugins: Dict[str, PluginInfo] = {}

    @property
    def plugins_dir(self) -> Path:
        return self._plugins_dir

    def _discover(self) -> List[Path]:
        """Find all .py files in the plugins directory."""
        if not self._plugins_dir.exists():
            return []

        result = []
        for entry in sorted(self._plugins_dir.iterdir()):
            if entry.suffix == ".py" and entry.is_file() and not entry.name.startswith("_"):
                result.append(entry)
        return result

    def _load_plugin(self, path: Path, tool_registry: Any = None) -> PluginInfo:
        """Load a single plugin file and call its register() function."""
        name = path.stem
        info = PluginInfo(name=name, path=path)

        try:
            # Load module from file path
            spec = importlib.util.spec_from_file_location(
                f"neomind_plugin_{name}", str(path)
            )
            if spec is None or spec.loader is None:
                info.error = "Failed to create module spec"
                return info

            module = importlib.util.module_from_spec(spec)
            # Add to sys.modules so imports inside plugin work
            sys.modules[f"neomind_plugin_{name}"] = module

            try:
                spec.loader.exec_module(module)
            except Exception as e:
                info.error = f"Import error: {e}"
                logger.error(f"Plugin '{name}' import failed: {e}")
                return info

            # Check for register function
            if not hasattr(module, "register"):
                info.error = "Missing register(tool_registry) function"
                logger.warning(f"Plugin '{name}' has no register() function")
                return info

            # Call register if we have a tool_registry
            if tool_registry is not None:
                try:
                    module.register(tool_registry)
                except Exception as e:
                    info.error = f"register() failed: {e}"
                    logger.error(f"Plugin '{name}' register() failed: {e}")
                    return info

            info.module = module
            info.loaded = True
            logger.info(f"Plugin '{name}' loaded successfully from {path}")

        except Exception as e:
            info.error = str(e)
            logger.error(f"Plugin '{name}' load failed: {e}")

        return info

    def load_all(self, tool_registry: Any = None) -> List[PluginInfo]:
        """Discover and load all plugins.

        Args:
            tool_registry: The tool registry to pass to each plugin's register().
                          If None, plugins are loaded but register() is not called.

        Returns:
            List of PluginInfo objects.
        """
        self._plugins.clear()
        paths = self._discover()

        for path in paths:
            info = self._load_plugin(path, tool_registry)
            self._plugins[info.name] = info

        loaded = sum(1 for p in self._plugins.values() if p.loaded)
        total = len(self._plugins)
        if total > 0:
            logger.info(f"Loaded {loaded}/{total} plugins from {self._plugins_dir}")

        return list(self._plugins.values())

    def reload_all(self, tool_registry: Any = None) -> List[PluginInfo]:
        """Unload all plugins and reload from disk.

        Removes old plugin modules from sys.modules before reloading.
        """
        # Clean up old modules
        for name in list(self._plugins.keys()):
            mod_name = f"neomind_plugin_{name}"
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        return self.load_all(tool_registry)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Return plugin info as list of dicts (for /plugin list)."""
        return [info.to_dict() for info in self._plugins.values()]

    def get_plugin(self, name: str) -> Optional[PluginInfo]:
        """Get a specific plugin by name."""
        return self._plugins.get(name)

    def format_plugin_list(self) -> str:
        """Format plugin list for display."""
        if not self._plugins:
            plugins = self._discover()
            if not plugins:
                return f"No plugins found in {self._plugins_dir}"
            return f"Found {len(plugins)} plugin(s) but none loaded yet. Use /plugin reload."

        lines = [f"Plugins ({self._plugins_dir}):"]
        for info in self._plugins.values():
            status = "OK" if info.loaded else f"FAILED: {info.error}"
            lines.append(f"  {info.name}: {status}")

        loaded = sum(1 for p in self._plugins.values() if p.loaded)
        lines.append(f"\n{loaded}/{len(self._plugins)} loaded")
        return "\n".join(lines)
