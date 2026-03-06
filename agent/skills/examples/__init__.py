"""
Example skills for ikol1729_agent.

Provides ready-to-use skills for common knowledge domains.
"""

from .python_api import PythonAPISkill, create_python_api_skill
from .web_api import WebAPISkill, create_web_api_skill
from .codebase import CodebaseSkill, create_codebase_skill

__all__ = [
    "PythonAPISkill",
    "create_python_api_skill",
    "WebAPISkill",
    "create_web_api_skill",
    "CodebaseSkill",
    "create_codebase_skill",
]