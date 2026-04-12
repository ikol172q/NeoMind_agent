"""
Context Builder for NeoMind Agent.

Builds dynamic system prompts with static/dynamic boundary for prompt caching.
Inspired by Claude Code's prompt composition pattern.

Created: 2026-04-01
Phase: 0 - Infrastructure
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path
import os


# 静态/动态边界标记
SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "<<DYNAMIC_BOUNDARY>>"


@dataclass
class PromptSection:
    """系统提示的一个部分。"""
    name: str
    content: str
    is_static: bool = True  # 静态部分可缓存
    priority: int = 0  # 优先级越高越靠前
    condition: Optional[Callable[[], bool]] = None  # 条件函数


class ContextBuilder:
    """
    上下文构建器。

    负责动态组装系统提示，使用静态/动态边界
    以支持 prompt caching。

    Inspired by Claude Code's prompts.ts pattern.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        """
        初始化上下文构建器。

        Args:
            base_dir: 基础目录（用于加载提示文件）
        """
        self.base_dir = base_dir or Path(__file__).parent
        self._sections: Dict[str, PromptSection] = {}
        self._git_context: Optional[str] = None
        self._memory_context: Optional[str] = None
        self._tool_context: Optional[str] = None

        # 注册默认部分
        self._register_default_sections()

    def _register_default_sections(self) -> None:
        """注册默认的提示部分。"""
        # 静态部分（可缓存）
        self.register_section(PromptSection(
            name="identity",
            content=self._get_identity_prompt(),
            is_static=True,
            priority=100
        ))

        self.register_section(PromptSection(
            name="capabilities",
            content=self._get_capabilities_prompt(),
            is_static=True,
            priority=90
        ))

        self.register_section(PromptSection(
            name="tool_schema",
            content="",  # 动态填充
            is_static=False,
            priority=80
        ))

        # 动态部分（不可缓存）
        self.register_section(PromptSection(
            name="git_context",
            content="",  # 动态填充
            is_static=False,
            priority=70
        ))

        self.register_section(PromptSection(
            name="memory_context",
            content="",  # 动态填充
            is_static=False,
            priority=60
        ))

        self.register_section(PromptSection(
            name="personality_context",
            content="",  # 动态填充
            is_static=False,
            priority=50
        ))

        self.register_section(PromptSection(
            name="rules",
            content=self._get_rules_prompt(),
            is_static=True,
            priority=40
        ))

    def register_section(self, section: PromptSection) -> None:
        """
        注册一个提示部分。

        Args:
            section: 提示部分
        """
        self._sections[section.name] = section

    def update_section(self, name: str, content: str) -> None:
        """
        更新提示部分的内容。

        Args:
            name: 部分名称
            content: 新内容
        """
        if name in self._sections:
            self._sections[name].content = content

    def set_git_context(self, context: str) -> None:
        """设置 Git 上下文。"""
        self._git_context = context
        self.update_section("git_context", context)

    def set_memory_context(self, context: str) -> None:
        """设置记忆上下文。"""
        self._memory_context = context
        self.update_section("memory_context", context)

    def set_tool_context(self, context: str) -> None:
        """设置工具上下文。"""
        self._tool_context = context
        self.update_section("tool_schema", context)

    def set_personality_context(self, personality: str, mode: str) -> None:
        """
        设置人格特定上下文。

        Args:
            personality: 人格名称
            mode: 模式名称
        """
        content = self._get_personality_prompt(personality, mode)
        self.update_section("personality_context", content)

    def build(self, include_dynamic: bool = True) -> str:
        """
        构建完整的系统提示。

        Args:
            include_dynamic: 是否包含动态部分

        Returns:
            完整的系统提示
        """
        # 按优先级排序
        sorted_sections = sorted(
            self._sections.values(),
            key=lambda s: s.priority,
            reverse=True
        )

        parts = []
        dynamic_parts = []

        for section in sorted_sections:
            # 检查条件
            if section.condition and not section.condition():
                continue

            # 跳过空内容
            if not section.content:
                continue

            if section.is_static:
                parts.append(f"# {section.name.upper()}\n\n{section.content}")
            else:
                dynamic_parts.append(f"# {section.name.upper()}\n\n{section.content}")

        # 组装
        if include_dynamic:
            static_content = "\n\n---\n\n".join(parts)
            dynamic_content = "\n\n---\n\n".join(dynamic_parts)

            if dynamic_content:
                return f"{static_content}\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n\n{dynamic_content}"
            return static_content
        else:
            return "\n\n---\n\n".join(parts)

    def build_static_only(self) -> str:
        """仅构建静态部分（用于缓存）。"""
        return self.build(include_dynamic=False)

    def get_boundary_marker(self) -> str:
        """获取边界标记。"""
        return SYSTEM_PROMPT_DYNAMIC_BOUNDARY

    def _get_identity_prompt(self) -> str:
        """获取身份提示。"""
        return """You are NeoMind, an advanced AI agent with three personalities:

1. **Chat 探索者 (Explorer)** - Cross-domain research and synthesis
2. **Coding 工程师 (Engineer)** - Software development and code analysis
3. **Finance 赚钱 (Money Maker)** - Financial analysis and trading

You can switch between personalities based on user needs. Each personality has specialized tools and knowledge domains."""

    def _get_capabilities_prompt(self) -> str:
        """获取能力提示。"""
        return """## Core Capabilities

- **File Operations**: Read, write, edit, search files
- **Shell Execution**: Run commands with safety checks
- **Web Access**: Search and fetch web content
- **Memory System**: Persistent cross-session memory
- **Self-Evolution**: Autonomous improvement with safety gates
- **Multi-Provider LLM**: Fallback chain across providers

## Confidence Levels

- **VERIFIED**: Directly observed or computed
- **INFERRED**: Logical deduction from evidence
- **GUESSED**: Speculation without firm evidence"""

    def _get_rules_prompt(self) -> str:
        """获取规则提示。"""
        return """## Operating Rules

1. **Be Honest**: Never fabricate information. State confidence level.
2. **Be Safe**: Check for destructive operations before execution.
3. **Be Efficient**: Use the right tool for the job.
4. **Be Helpful**: Anticipate user needs and provide context.
5. **Be Concise**: Get to the point, avoid unnecessary preamble.

## Safety Protocol

- Always confirm destructive operations
- Protect sensitive files (.env, .ssh, configs)
- Validate inputs before execution
- Log important operations"""

    def _get_personality_prompt(self, personality: str, mode: str) -> str:
        """获取人格特定提示。"""
        prompts = {
            "chat": """## Current Personality: Chat 探索者

You are in **Chat** mode, optimized for:
- Cross-domain research and exploration
- Multi-source synthesis
- Creative brainstorming
- Deep-dive analysis

Unique commands: /deep, /compare, /draft, /brainstorm, /tldr, /explore""",

            "coding": """## Current Personality: Coding 工程师

You are in **Coding** mode, optimized for:
- Software development
- Code analysis and modification
- File operations and search
- Test execution

Unique commands: /code, /fix, /refactor, /grep, /find, /test, /apply""",

            "finance": """## Current Personality: Finance 赚钱

You are in **Finance** mode, optimized for:
- Financial analysis
- Quantitative computation
- Market research
- Investment recommendations

Unique commands: /stock, /portfolio, /market, /news, /watchlist, /quant

**Principle**: If it can be computed, compute it. NEVER estimate when calculation is possible.""",
        }
        return prompts.get(personality, prompts["chat"])

    def load_prompt_file(self, filename: str) -> Optional[str]:
        """
        从文件加载提示。

        Args:
            filename: 文件名（相对于 prompts/ 目录）

        Returns:
            文件内容或 None
        """
        prompt_path = self.base_dir / "prompts" / filename
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return None

    def get_stats(self) -> Dict[str, Any]:
        """获取构建器统计信息。"""
        static_count = sum(1 for s in self._sections.values() if s.is_static)
        dynamic_count = len(self._sections) - static_count

        return {
            "total_sections": len(self._sections),
            "static_sections": static_count,
            "dynamic_sections": dynamic_count,
            "has_git_context": self._git_context is not None,
            "has_memory_context": self._memory_context is not None,
            "has_tool_context": self._tool_context is not None,
        }


# 全局实例
_builder = None


def get_context_builder() -> ContextBuilder:
    """获取全局上下文构建器实例。"""
    global _builder
    if _builder is None:
        _builder = ContextBuilder()
    return _builder


def build_system_prompt(include_dynamic: bool = True) -> str:
    """快捷函数：构建系统提示。"""
    return get_context_builder().build(include_dynamic)


__all__ = [
    'ContextBuilder',
    'PromptSection',
    'SYSTEM_PROMPT_DYNAMIC_BOUNDARY',
    'get_context_builder',
    'build_system_prompt',
]


if __name__ == "__main__":
    # 简单测试
    builder = ContextBuilder()

    # 设置动态上下文
    builder.set_git_context("Branch: main\nStatus: clean")
    builder.set_memory_context("User prefers Python over JavaScript")
    builder.set_personality_context("coding", "coding")

    # 构建完整提示
    full_prompt = builder.build()
    print(f"Full prompt length: {len(full_prompt)} chars")
    print(f"Has boundary: {SYSTEM_PROMPT_DYNAMIC_BOUNDARY in full_prompt}")

    # 仅静态部分
    static_prompt = builder.build_static_only()
    print(f"Static only length: {len(static_prompt)} chars")

    print(f"\nStats: {builder.get_stats()}")
    print("\nContextBuilder tests passed!")
