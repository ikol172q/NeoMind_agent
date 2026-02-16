import os
from pathlib import Path
from typing import Any, Optional
import hydra
from omegaconf import DictConfig, OmegaConf
from hydra.core.global_hydra import GlobalHydra
import importlib.resources


class AgentConfigManager:
    """Manages agent configuration using Hydra"""

    def __init__(self, config_name: str = "config"):
        # Determine the directory where config.yaml is located
        # It should be in the 'agent' subdirectory relative to this file
        self.base_dir = Path(__file__).parent
        config_dir = "agent"  # config.yaml is in agent/ subdirectory

        # Hydra initialization - config_path is relative to the location of this file
        # We do NOT change the working directory
        if not GlobalHydra.instance().is_initialized():
            hydra.initialize(config_path=config_dir, version_base="1.3")

        # Load configuration
        self._cfg = hydra.compose(config_name=config_name)

        # Apply environment overrides
        self._apply_env_overrides()

        # Extract agent config
        self._agent_config = OmegaConf.to_container(
            self._cfg.get("agent", {}),
            resolve=True
        )
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides to config"""
        env_mappings = {
            "DEEPSEEK_MODEL": "agent.model",
            "DEEPSEEK_TEMPERATURE": "agent.temperature",
        }

        for env_var, config_path in env_mappings.items():
            if env_val := os.getenv(env_var):
                if env_var == "DEEPSEEK_TEMPERATURE":
                    env_val = float(env_val)
                OmegaConf.update(self._cfg, config_path, env_val)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get agent config value"""
        if "." in key:
            # Handle "agent.model" format
            parts = key.split(".", 1)
            if len(parts) > 1:
                key = parts[1]

        return self._agent_config.get(key, default)

    @property
    def model(self) -> str:
        return self.get("model", "deepseek-chat")

    @property
    def temperature(self) -> float:
        return self.get("temperature", 0.7)
    
    @property
    def max_tokens(self) -> int:
        return self.get("max_tokens", 8192)
    
    @property
    def thinking_enabled(self) -> bool:
        return self.get("thinking_enabled", False)
    
    @property
    def system_prompt(self) -> str:
        return self.get("system_prompt", "")


# Global instance - single point of access
agent_config = AgentConfigManager()