"""Ports the runtime depends on.

Protocols, not base classes: the existing ToolRegistry, ChatStore and provider
clients already exist and should not have to inherit from anything to be used
here. Adapters satisfy these structurally.

The direction matters — runtime depends on these abstractions, adapters depend
on the runtime. Nothing here may reference a concrete frontend or provider.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:  # import-only: ports must not pull adapters in at runtime
    from agent.runtime.llm_stream import StreamChunk


@runtime_checkable
class ToolRegistryPort(Protocol):
    """What the executor needs from a tool registry.

    Deliberately mirrors the real `agent.coding.tools.ToolRegistry`: `get_tool`
    and `get_all_tools`. The dead QueryEngine called `registry.execute(...)`,
    which no registry has ever implemented — writing the port against the real
    object is what stops that class of drift.
    """

    def get_tool(self, name: str) -> Optional[Any]: ...

    def get_all_tools(self) -> List[Any]: ...


@runtime_checkable
class PermissionBroker(Protocol):
    """Asks a human and returns their answer.

    Implementations must be cancellable and must raise rather than hang
    forever; the executor converts any failure into a denial.
    """

    async def request(
        self,
        request_id: str,
        tool_name: str,
        preview: str,
        risk: str,
        explanation: str,
        allowed_scopes: tuple,
        params: Optional[Mapping[str, Any]] = None,
    ) -> Any: ...


@runtime_checkable
class AuditPort(Protocol):
    def record(self, entry: Mapping[str, Any]) -> None: ...


@runtime_checkable
class LLMPort(Protocol):
    """Provider-neutral streaming.

    Yields incremental chunks. A port that returns the finished string and
    emits it as a single delta is not streaming — that is what QueryEngine did,
    and it is why nothing built on it could render progressively.

    Phase 2 narrowed the yield type from ``Dict[str, Any]`` to the frozen
    chunk classes in ``agent.runtime.llm_stream``. The dict version was a
    placeholder written before any adapter existed; a bag of keys pushes the
    "which shape is this" question onto every consumer, which is the same
    class of drift the ToolRegistryPort docstring describes. Nothing
    implemented the old signature, so nothing had to change with it.

    Failures are raised as ``LLMStreamError`` subclasses rather than yielded,
    so a consumer cannot accidentally treat an error as content.
    """

    def stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]: ...


@runtime_checkable
class ConversationStorePort(Protocol):
    """One owner per session. The runtime is the only writer."""

    def append(self, session_id: str, message: Mapping[str, Any]) -> None: ...

    def load(self, session_id: str) -> List[Dict[str, Any]]: ...
