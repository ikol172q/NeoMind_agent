"""
Unit tests for ContextBuilder system.

Phase 0 - Infrastructure
"""

import pytest
from agent.context_builder import (
    ContextBuilder,
    PromptSection,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    get_context_builder,
    build_system_prompt
)


class TestPromptSection:
    """PromptSection数据类测试。"""

    def test_default_values(self):
        """测试默认值。"""
        section = PromptSection(name="test", content="test content")
        assert section.name == "test"
        assert section.content == "test content"
        assert section.is_static is True
        assert section.priority == 0
        assert section.condition is None

    def test_custom_values(self):
        """测试自定义值。"""
        condition = lambda: True
        section = PromptSection(
            name="custom",
            content="custom content",
            is_static=False,
            priority=100,
            condition=condition
        )
        assert section.name == "custom"
        assert section.content == "custom content"
        assert section.is_static is False
        assert section.priority == 100
        assert section.condition is condition


class TestContextBuilder:
    """ContextBuilder单元测试。"""

    # ── Fixtures ─────────────────────────────────────

    @pytest.fixture
    def builder(self):
        """创建默认上下文构建器。"""
        return ContextBuilder()

    # ── 基础功能测试 ─────────────────────────────────

    def test_initial_sections_registered(self, builder):
        """测试默认部分已注册。"""
        assert "identity" in builder._sections
        assert "capabilities" in builder._sections
        assert "tool_schema" in builder._sections
        assert "git_context" in builder._sections
        assert "memory_context" in builder._sections
        assert "personality_context" in builder._sections
        assert "rules" in builder._sections

    def test_register_section(self, builder):
        """测试注册新部分。"""
        section = PromptSection(
            name="custom",
            content="custom content",
            is_static=True,
            priority=50
        )
        builder.register_section(section)
        assert "custom" in builder._sections
        assert builder._sections["custom"].content == "custom content"

    def test_update_section(self, builder):
        """测试更新部分内容。"""
        builder.update_section("git_context", "New git context")
        assert builder._sections["git_context"].content == "New git context"

    def test_build_static_only(self, builder):
        """测试仅构建静态部分。"""
        static_prompt = builder.build_static_only()

        # 应包含静态部分
        assert "# IDENTITY" in static_prompt
        assert "# CAPABILITIES" in static_prompt
        assert "# RULES" in static_prompt

        # 不应包含动态边界
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in static_prompt

    def test_build_with_dynamic(self, builder):
        """测试构建完整提示（包含动态部分）。"""
        builder.set_git_context("Branch: main\nStatus: clean")
        builder.set_memory_context("User prefers Python")
        builder.set_personality_context("coding", "coding")

        full_prompt = builder.build()

        # 应包含静态部分
        assert "# IDENTITY" in full_prompt
        assert "# CAPABILITIES" in full_prompt
        assert "# RULES" in full_prompt

        # 应包含动态部分
        assert "# GIT_CONTEXT" in full_prompt
        assert "# MEMORY_CONTEXT" in full_prompt
        assert "# PERSONALITY_CONTEXT" in full_prompt

        # 应包含边界标记
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in full_prompt

    def test_build_without_dynamic_content(self, builder):
        """测试构建时没有动态内容。"""
        # 不设置任何动态上下文
        full_prompt = builder.build()

        # 如果没有动态内容，不应该有边界标记
        # 但因为默认 personality_context 有内容，所以会有边界
        assert "# IDENTITY" in full_prompt

    # ── 上下文设置测试 ───────────────────────────────

    def test_set_git_context(self, builder):
        """测试设置Git上下文。"""
        builder.set_git_context("Branch: feature\nModified: 3 files")

        assert builder._git_context == "Branch: feature\nModified: 3 files"
        assert builder._sections["git_context"].content == "Branch: feature\nModified: 3 files"

    def test_set_memory_context(self, builder):
        """测试设置记忆上下文。"""
        builder.set_memory_context("Previous task: implement token budget")

        assert builder._memory_context == "Previous task: implement token budget"
        assert builder._sections["memory_context"].content == "Previous task: implement token budget"

    def test_set_tool_context(self, builder):
        """测试设置工具上下文。"""
        tool_schema = '{"name": "bash", "type": "function"}'
        builder.set_tool_context(tool_schema)

        assert builder._tool_context == tool_schema
        assert builder._sections["tool_schema"].content == tool_schema

    def test_set_personality_context_chat(self, builder):
        """测试设置Chat人格上下文。"""
        builder.set_personality_context("chat", "chat")

        assert "Chat 探索者" in builder._sections["personality_context"].content
        assert "/deep" in builder._sections["personality_context"].content

    def test_set_personality_context_coding(self, builder):
        """测试设置Coding人格上下文。"""
        builder.set_personality_context("coding", "coding")

        assert "Coding 工程师" in builder._sections["personality_context"].content
        assert "/code" in builder._sections["personality_context"].content

    def test_set_personality_context_finance(self, builder):
        """测试设置Finance人格上下文。"""
        builder.set_personality_context("finance", "finance")

        assert "Finance 赚钱" in builder._sections["personality_context"].content
        assert "/stock" in builder._sections["personality_context"].content

    # ── 优先级排序测试 ───────────────────────────────

    def test_sections_sorted_by_priority(self, builder):
        """测试部分按优先级排序。"""
        # identity = 100, capabilities = 90, tool_schema = 80
        # git_context = 70, memory_context = 60, personality_context = 50
        # rules = 40

        builder.set_git_context("git info")
        full_prompt = builder.build()

        # identity 应该在 capabilities 之前
        identity_pos = full_prompt.find("# IDENTITY")
        capabilities_pos = full_prompt.find("# CAPABILITIES")
        git_pos = full_prompt.find("# GIT_CONTEXT")
        rules_pos = full_prompt.find("# RULES")

        assert identity_pos < capabilities_pos
        assert capabilities_pos < git_pos
        assert git_pos > rules_pos  # rules is lower priority

    # ── 条件过滤测试 ─────────────────────────────────

    def test_section_with_false_condition_excluded(self, builder):
        """测试条件为False的部分被排除。"""
        conditional_section = PromptSection(
            name="conditional",
            content="Conditional content",
            is_static=True,
            priority=200,
            condition=lambda: False
        )
        builder.register_section(conditional_section)

        prompt = builder.build()
        assert "Conditional content" not in prompt

    def test_section_with_true_condition_included(self, builder):
        """测试条件为True的部分被包含。"""
        conditional_section = PromptSection(
            name="conditional",
            content="Conditional content",
            is_static=True,
            priority=200,
            condition=lambda: True
        )
        builder.register_section(conditional_section)

        prompt = builder.build()
        assert "Conditional content" in prompt

    # ── 边界标记测试 ───────────────────────────────

    def test_boundary_marker(self, builder):
        """测试边界标记获取。"""
        assert builder.get_boundary_marker() == SYSTEM_PROMPT_DYNAMIC_BOUNDARY

    def test_boundary_marker_constant(self):
        """测试边界标记常量。"""
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY == "<<DYNAMIC_BOUNDARY>>"

    # ── 统计信息测试 ───────────────────────────────

    def test_get_stats_initial(self, builder):
        """测试初始统计信息。"""
        stats = builder.get_stats()

        assert stats["total_sections"] == 7
        assert stats["static_sections"] == 3  # identity, capabilities, rules
        assert stats["dynamic_sections"] == 4  # tool_schema, git, memory, personality
        assert stats["has_git_context"] is False
        assert stats["has_memory_context"] is False
        assert stats["has_tool_context"] is False

    def test_get_stats_with_contexts(self, builder):
        """测试设置上下文后的统计信息。"""
        builder.set_git_context("git info")
        builder.set_memory_context("memory info")
        builder.set_tool_context("tool schema")

        stats = builder.get_stats()

        assert stats["has_git_context"] is True
        assert stats["has_memory_context"] is True
        assert stats["has_tool_context"] is True

    # ── 全局实例测试 ───────────────────────────────

    def test_get_context_builder_singleton(self):
        """测试全局实例是单例。"""
        builder1 = get_context_builder()
        builder2 = get_context_builder()
        assert builder1 is builder2

    def test_build_system_prompt_function(self):
        """测试快捷函数。"""
        prompt = build_system_prompt()
        assert "# IDENTITY" in prompt

    # ── 内容验证测试 ───────────────────────────────

    def test_identity_content(self, builder):
        """测试身份提示内容。"""
        identity = builder._get_identity_prompt()
        assert "NeoMind" in identity
        assert "Chat 探索者" in identity
        assert "Coding 工程师" in identity
        assert "Finance 赚钱" in identity

    def test_capabilities_content(self, builder):
        """测试能力提示内容。"""
        capabilities = builder._get_capabilities_prompt()
        assert "File Operations" in capabilities
        assert "Shell Execution" in capabilities
        assert "Web Access" in capabilities
        assert "Memory System" in capabilities
        assert "Confidence Levels" in capabilities

    def test_rules_content(self, builder):
        """测试规则提示内容。"""
        rules = builder._get_rules_prompt()
        assert "Be Honest" in rules
        assert "Be Safe" in rules
        assert "Safety Protocol" in rules

    # ── 空内容处理测试 ───────────────────────────

    def test_empty_section_skipped(self, builder):
        """测试空内容部分被跳过。"""
        # tool_schema 默认为空
        prompt = builder.build_static_only()

        # tool_schema 不应该出现在静态部分（因为它被标记为动态）
        # 但如果它的内容为空，应该被跳过
        assert "# TOOL_SCHEMA" not in prompt

    # ── 特殊字符处理测试 ───────────────────────────

    def test_content_with_special_characters(self, builder):
        """测试包含特殊字符的内容。"""
        special_content = "Content with <xml> tags & \"quotes\" and 'apostrophes'"
        builder.set_git_context(special_content)

        prompt = builder.build()
        assert special_content in prompt


class TestPromptComposition:
    """提示组合测试。"""

    @pytest.fixture
    def builder(self):
        return ContextBuilder()

    def test_full_prompt_structure(self, builder):
        """测试完整提示结构。"""
        builder.set_git_context("Git: main")
        builder.set_memory_context("Memory: test")
        builder.set_personality_context("coding", "coding")

        prompt = builder.build()

        # 验证结构
        boundary_pos = prompt.find(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        assert boundary_pos > 0, "Boundary marker should exist"

        static_part = prompt[:boundary_pos]
        dynamic_part = prompt[boundary_pos + len(SYSTEM_PROMPT_DYNAMIC_BOUNDARY):]

        # 静态部分应该包含静态内容
        assert "# IDENTITY" in static_part
        assert "# CAPABILITIES" in static_part
        assert "# RULES" in static_part

        # 动态部分应该包含动态内容
        assert "# GIT_CONTEXT" in dynamic_part
        assert "# MEMORY_CONTEXT" in dynamic_part
        assert "# PERSONALITY_CONTEXT" in dynamic_part


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
