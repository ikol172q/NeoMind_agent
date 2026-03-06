"""
Base classes for skills in ikol1729_agent.

Skills are knowledge sources that can be loaded dynamically to provide
contextual information to tools and the LLM.
"""

import abc
import json
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum


class SkillType(Enum):
    """Types of skills based on knowledge source."""
    DOCUMENTATION = "documentation"      # API docs, manuals
    SCHEMA = "schema"                    # JSON schemas, API specs
    CODEBASE = "codebase"                # Project-specific knowledge
    EXTERNAL_API = "external_api"        # External API documentation
    INTERNAL_API = "internal_api"        # Internal API documentation
    TOOL_KNOWLEDGE = "tool_knowledge"    # Tool-specific knowledge
    GENERAL = "general"                  # General knowledge


@dataclass
class SkillMetadata:
    """Metadata for a skill."""
    name: str
    description: str
    skill_type: SkillType
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    size_estimate: Optional[int] = None  # Estimated tokens when loaded
    cache_ttl: int = 3600  # Time-to-live in seconds for cache
    dependencies: List[str] = field(default_factory=list)  # Other skill names


class SkillError(Exception):
    """Base exception for skill errors."""
    pass


class SkillLoadError(SkillError):
    """Raised when skill loading fails."""
    pass


class SkillValidationError(SkillError):
    """Raised when skill validation fails."""
    pass


class Skill(abc.ABC):
    """Abstract base class for all skills."""

    def __init__(self, metadata: Optional[SkillMetadata] = None):
        self.metadata = metadata or self._default_metadata()
        self._loaded_content: Optional[str] = None
        self._load_time: Optional[float] = None
        self._validate_metadata()

    @classmethod
    @abc.abstractmethod
    def _default_metadata(cls) -> SkillMetadata:
        """Return default metadata for this skill."""
        pass

    def _validate_metadata(self) -> None:
        """Validate that metadata has required fields."""
        if not self.metadata.name:
            raise SkillValidationError("Skill metadata missing required field: name")
        if not self.metadata.description:
            raise SkillValidationError("Skill metadata missing required field: description")
        if not self.metadata.skill_type:
            raise SkillValidationError("Skill metadata missing required field: skill_type")

    @abc.abstractmethod
    def load_content(self) -> str:
        """
        Load the skill's content.

        Returns:
            String containing the skill's knowledge content.

        Raises:
            SkillLoadError: If loading fails.
        """
        pass

    def get_content(self, force_reload: bool = False) -> str:
        """
        Get skill content, loading if necessary.

        Args:
            force_reload: If True, force reload even if cached.

        Returns:
            Skill content as string.
        """
        if force_reload or self._loaded_content is None or self._is_cache_expired():
            try:
                self._loaded_content = self.load_content()
                self._load_time = time.time()
            except Exception as e:
                raise SkillLoadError(f"Failed to load skill '{self.metadata.name}': {e}") from e

        return self._loaded_content

    def _is_cache_expired(self) -> bool:
        """Check if cached content has expired."""
        if self._load_time is None:
            return True
        if self.metadata.cache_ttl <= 0:
            return False  # No expiration
        return (time.time() - self._load_time) > self.metadata.cache_ttl

    def clear_cache(self) -> None:
        """Clear cached content."""
        self._loaded_content = None
        self._load_time = None

    def estimate_tokens(self, content: Optional[str] = None) -> int:
        """
        Estimate token count for skill content.

        Args:
            content: Optional content to estimate. If None, uses cached content.

        Returns:
            Estimated token count.
        """
        if content is None:
            content = self._loaded_content or ""
        # Rough estimate: 4 characters per token
        return max(1, len(content) // 4)

    def to_dict(self) -> Dict[str, Any]:
        """Convert skill to dictionary representation."""
        return {
            "name": self.metadata.name,
            "description": self.metadata.description,
            "skill_type": self.metadata.skill_type.value,
            "version": self.metadata.version,
            "tags": self.metadata.tags,
            "size_estimate": self.estimate_tokens(),
            "cache_ttl": self.metadata.cache_ttl,
            "dependencies": self.metadata.dependencies,
            "is_loaded": self._loaded_content is not None,
            "loaded_at": self._load_time,
        }


class FileBasedSkill(Skill):
    """Base class for skills that load content from files."""

    def __init__(self, file_path: str, metadata: Optional[SkillMetadata] = None):
        self.file_path = file_path
        super().__init__(metadata)

    def load_content(self) -> str:
        """Load content from file."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise SkillLoadError(f"Failed to read skill file '{self.file_path}': {e}") from e

    @classmethod
    def _default_metadata(cls) -> SkillMetadata:
        """Return default metadata for file-based skills."""
        return SkillMetadata(
            name="file_based_skill",
            description="Skill that loads content from a file",
            skill_type=SkillType.GENERAL,
            version="1.0.0",
            cache_ttl=3600,
        )


class URLBasedSkill(Skill):
    """Base class for skills that load content from URLs."""

    def __init__(self, url: str, metadata: Optional[SkillMetadata] = None):
        self.url = url
        super().__init__(metadata)

    def load_content(self) -> str:
        """Load content from URL."""
        try:
            import requests
            response = requests.get(self.url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            raise SkillLoadError(f"Failed to fetch skill URL '{self.url}': {e}") from e

    @classmethod
    def _default_metadata(cls) -> SkillMetadata:
        """Return default metadata for URL-based skills."""
        return SkillMetadata(
            name="url_based_skill",
            description="Skill that loads content from a URL",
            skill_type=SkillType.GENERAL,
            version="1.0.0",
            cache_ttl=3600,
        )


class StaticSkill(Skill):
    """Skill with static content."""

    def __init__(self, content: str, metadata: Optional[SkillMetadata] = None):
        self._static_content = content
        super().__init__(metadata)

    def load_content(self) -> str:
        """Return static content."""
        return self._static_content

    @classmethod
    def _default_metadata(cls) -> SkillMetadata:
        """Return default metadata for static skills."""
        return SkillMetadata(
            name="static_skill",
            description="Static skill with predefined content",
            skill_type=SkillType.GENERAL,
            version="1.0.0",
            cache_ttl=3600,
        )