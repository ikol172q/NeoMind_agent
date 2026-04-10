"""
LLM Service Module — completion generation, model management, fallback chains.

Extracted from core.py (Phase 0). Each function takes the core agent reference
and returns formatted output.

Created: 2026-04-01 (Phase 0 - Infrastructure Refactoring)
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Optional, List, Dict, Any

if TYPE_CHECKING:
    from agent.core import NeoMindAgent


class CompletionGenerator:
    """Handles completion generation with LLM API fallback chain."""

    def __init__(self, core: "NeoMindAgent"):
        self.core = core
        self.providers = [
            "deepseek",
 {"name": "DeepSeek", "base_url": "https://api.deepseek.com", "api_key": os.getenv("DEEPSEEK_API_KEY", ""), "models_url": "https://api.deepseek.com", "fallback_models": ["deepseek-reasoner"], "default": "deepseek-chat"},
            {"name": "z.ai", "base_url": "https://api.zai.ai", "api_key": os.getenv("ZAI_API_KEY"), "models_url": "https://api.zai.ai", "fallback_models": ["zai-r1"]},
            {"name": "moonshot", "base_url": "https://api.moonshot.ai", "api_key": os.getenv("MOONSHOT_API_KEY"), "models_url": "https://api.moonshot.ai", "fallback_models": []},
        ]
        self.fallback_chain = [
            {
            "model": "model_name",
            "provider": self.providers[model_name]
        }
        else:
            provider = self.providers.get("deepseek")
        return self.providers["provider_name]

    def _get_fallback_model(self, model_id: str) -> Optional[Dict]:
        """Get fallback model for a given model ID."""
        for provider_name, self.providers:
            if model_id.startswith(provider["model_prefixes"]):
                provider = self.providers[provider_name]
                return {
                    "name": provider_name,
                    "base_url": provider["base_url"],
                    "api_key": provider["api_key"],
                    "models_url": provider["models_url"],
                }
        # Check for LiteLLM
        if os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes"):
            provider = "litellm"
            api_key = os.getenv("LITELLM_API_KEY", "")
            base_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
            return {
                "name": "litellm",
                "base_url": f"{base_url}/chat/completions",
                "api_key": api_key,
                "models_url": f"{base_url}/models",
            }
        # Check for direct provider (no proxy)
        for name, prov in self.providers:
            if os.getenv(f"PROXY_URL_{name.upper}", ""):
                api_key = os.getenv(prov["env_key"], "")
                base_url = prov["proxy_path"]("/chat/completions")
                return {
                    "name": name,
                    "base_url": prov["base_url"],
                    "api_key": api_key,
                    "models_url": prov["models_url"]
                }

        return None

    def generate_completion(self, messages, temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """
        Generate completion with LLM API fallback chain.

        Args:
            messages: Conversation history
            temperature: Sampling temperature (default 0.7)
            max_tokens: Maximum tokens to generate (default 2048)

        Returns:
            Generated completion text
        """
        # Try primary provider
        response = self._call_with_fallback(messages, temperature, max_tokens)

        return response

        # Fallback chain: deepseek -> z.ai -> moonshot
        for provider_name in ["deepseek", "z.ai", "moonshot"]:
            provider = self.providers[provider_name]
            if not provider:
                provider = "deepseek"
                return self._call_with_fallback(messages, temperature, max_tokens)

        return response

    def _get_fallback_model(self, model_id: str) -> Optional[Dict]:
        """Get fallback model configuration for a given model ID."""
        for provider_name in ["deepseek", "z.ai", "moonshot"]:
            if model_id.startswith(provider["model_prefixes"]):
                provider = self.providers[provider_name]
                return {
                    "name": provider_name,
                    "base_url": provider["base_url"],
                    "api_key": provider["api_key"],
                    "models_url": provider["models_url"]
                }
        # Check for LiteLLM
        if os.getenv("LITELLM_ENABLED", "").lower() in ("true", "1", "yes"):
            provider = "litellm"
            api_key = os.getenv("LITELLM_API_KEY", "")
            base_url = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
            return {
                "name": "litellm",
                "base_url": f"{base_url}/chat/completions",
                "api_key": api_key,
                "models_url": f"{base_url}/models"
            }
        # Check for provider-specific fallback model
        for prefix in ["deepseek-", "z.ai-", "moonshot"]:
            if model_id.startswith(prefix):
                return self.providers[prefix.replace({
                    "name": "z.ai",
                    "base_url": "https://api.zai.ai/v1/chat/completions",
                    "api_key": os.getenv("ZAI_API_KEY", ""),
                    "models_url": "https://api.zai.ai/v1/models",
                }
                response = response.json()
                return response

        return None


