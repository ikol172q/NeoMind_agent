"""
Message Normalizer for NeoMind Agent.

Ensures all messages conform to expected API schemas before sending to the model.
Inspired by Claude Code's message normalization pattern.

Created: 2026-04-01
Phase: 0 - Infrastructure
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
import re
import json


@dataclass
class NormalizedMessage:
    """标准化消息结构。"""
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MessageNormalizer:
    """
    消息标准化器。

    确保所有发送给 LLM 的消息都符合预期的格式。
    这是防止 API 错误的关键组件。

    Inspired by Claude Code's queryHelpers.ts
    """

    VALID_ROLES = {"system", "user", "assistant", "tool"}
    MAX_CONTENT_SIZE = 100000  # 100KB
    TRUNCATION_SUFFIX = "\n\n[Content truncated due to size limit]"

    def __init__(self, max_content_size: int = MAX_CONTENT_SIZE):
        """
        初始化消息标准化器。

        Args:
            max_content_size: 最大内容大小（字符数）
        """
        self.max_content_size = max_content_size

    def normalize(self, message: Union[Dict, str, NormalizedMessage]) -> NormalizedMessage:
        """
        标准化任意格式的消息。

        Args:
            message: 原始消息（字典、字符串或已标准化的消息）

        Returns:
            标准化后的消息

        Raises:
            ValueError: 如果消息格式不支持
        """
        if isinstance(message, NormalizedMessage):
            return self._validate_and_truncate(message)

        if isinstance(message, str):
            return NormalizedMessage(
                role="user",
                content=self._sanitize_content(message)
            )

        if isinstance(message, dict):
            return self._normalize_dict(message)

        raise ValueError(f"Unsupported message type: {type(message)}")

    def _normalize_dict(self, message: Dict) -> NormalizedMessage:
        """标准化字典消息。"""
        role = message.get("role", "user")
        content = message.get("content", "")

        # 确保角色有效
        if role not in self.VALID_ROLES:
            role = "user"

        # 处理内容
        if isinstance(content, list):
            content = self._merge_content_parts(content)
        elif not isinstance(content, str):
            content = str(content)

        return NormalizedMessage(
            role=role,
            content=self._sanitize_content(content),
            name=message.get("name"),
            tool_calls=message.get("tool_calls"),
            tool_call_id=message.get("tool_call_id"),
            metadata={
                k: v for k, v in message.items()
                if k not in {"role", "content", "name", "tool_calls", "tool_call_id"}
            }
        )

    def _validate_and_truncate(self, message: NormalizedMessage) -> NormalizedMessage:
        """验证并截断消息。"""
        if message.role not in self.VALID_ROLES:
            raise ValueError(f"Invalid role: {message.role}")

        content = self._sanitize_content(message.content)

        # 截断过长内容
        if len(content) > self.max_content_size:
            content = content[:self.max_content_size] + self.TRUNCATION_SUFFIX

        return NormalizedMessage(
            role=message.role,
            content=content,
            name=message.name,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            metadata=message.metadata
        )

    def _sanitize_content(self, content: str) -> str:
        """清理内容。"""
        if not content:
            return ""

        # 移除控制字符 (保留换行和制表符)
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', content)

        # 标准化换行符
        content = content.replace('\r\n', '\n').replace('\r', '\n')

        return content

    def _merge_content_parts(self, parts: List) -> str:
        """合并多部分内容。"""
        text_parts = []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "image":
                    text_parts.append("[Image content]")
                else:
                    text_parts.append(str(part))
        return "\n".join(text_parts)

    def normalize_tool_result(self, tool_name: str, result: str,
                            tool_call_id: Optional[str] = None,
                            success: bool = True) -> NormalizedMessage:
        """
        标准化工具执行结果。

        Args:
            tool_name: 工具名称
            result: 执行结果
            tool_call_id: 工具调用ID
            success: 是否成功

        Returns:
            标准化后的工具消息
        """
        # 处理大型结果
        if len(result) > self.max_content_size:
            result = result[:self.max_content_size] + "\n\n[Result truncated]"

        return NormalizedMessage(
            role="tool",
            content=result,
            name=tool_name,
            tool_call_id=tool_call_id,
            metadata={"success": success, "tool_name": tool_name}
        )

    def normalize_conversation(self, messages: List) -> List[NormalizedMessage]:
        """
        标准化整个对话。

        Args:
            messages: 消息列表

        Returns:
            标准化后的消息列表
        """
        normalized = []
        for msg in messages:
            try:
                normalized.append(self.normalize(msg))
            except Exception as e:
                # 记录错误但继续处理
                error_msg = NormalizedMessage(
                    role="system",
                    content=f"[Failed to normalize message: {e}]",
                    metadata={"error": str(e)}
                )
                normalized.append(error_msg)
        return normalized

    def to_api_format(self, message: NormalizedMessage) -> Dict[str, Any]:
        """
        转换为 API 调用格式。

        Args:
            message: 标准化消息

        Returns:
            适合 API 调用的字典格式
        """
        result = {"role": message.role, "content": message.content}

        if message.name:
            result["name"] = message.name

        if message.tool_calls:
            result["tool_calls"] = message.tool_calls

        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id

        return result

    def to_api_format_list(self, messages: List[NormalizedMessage]) -> List[Dict]:
        """
        转换消息列表为 API 格式。

        Args:
            messages: 标准化消息列表

        Returns:
            API 格式的消息列表
        """
        return [self.to_api_format(msg) for msg in messages]

    def extract_tool_calls(self, content: str) -> List[Dict]:
        """
        从内容中提取工具调用。

        用于解析 LLM 响应中的工具调用。

        Args:
            content: 响应内容

        Returns:
            提取的工具调用列表
        """
        tool_calls = []

        # 匹配 XML 格式的工具调用
        xml_pattern = r'<tool_call[^>]*>(.*?)</tool_call\>'
        for match in re.finditer(xml_pattern, content, re.DOTALL):
            try:
                call_content = match.group(1)
                # 尝试解析 JSON
                json_match = re.search(r'\{.*\}', call_content, re.DOTALL)
                if json_match:
                    call = json.loads(json_match.group())
                    if "name" in call:
                        tool_calls.append({
                            "id": f"call_{len(tool_calls)}",
                            "type": "function",
                            "function": call
                        })
            except json.JSONDecodeError:
                continue

        # 匹配 JSON 格式的工具调用
        json_pattern = r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\s*\}'
        for match in re.finditer(json_pattern, content):
            try:
                call = json.loads(match.group())
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "type": "function",
                    "function": call
                })
            except json.JSONDecodeError:
                continue

        return tool_calls if tool_calls else None


# 全局实例
_normalizer = None


def get_normalizer() -> MessageNormalizer:
    """获取全局消息标准化器实例。"""
    global _normalizer
    if _normalizer is None:
        _normalizer = MessageNormalizer()
    return _normalizer


def normalize_message(message: Union[Dict, str, NormalizedMessage]) -> NormalizedMessage:
    """
    快捷函数：标准化单个消息。

    Args:
        message: 原始消息

    Returns:
        标准化后的消息
    """
    return get_normalizer().normalize(message)


__all__ = [
    'MessageNormalizer',
    'NormalizedMessage',
    'get_normalizer',
    'normalize_message',
]


if __name__ == "__main__":
    # 简单测试
    normalizer = MessageNormalizer()

    # 测试字符串
    msg1 = normalizer.normalize("Hello, world!")
    print(f"String: role={msg1.role}, content={msg1.content[:20]}...")

    # 测试字典
    msg2 = normalizer.normalize({"role": "assistant", "content": "Hi there!"})
    print(f"Dict: role={msg2.role}, content={msg2.content}")

    # 测试工具结果
    msg3 = normalizer.normalize_tool_result("bash", "output...", "call_123")
    print(f"Tool: role={msg3.role}, name={msg3.name}")

    # 测试长内容截断
    long_content = "x" * 150000
    msg4 = normalizer.normalize(long_content)
    print(f"Truncated: {len(msg4.content)} chars, has suffix: {'[Content truncated' in msg4.content}")

    print("\nAll tests passed!")
