"""NeoMind Agentic Loop — Canonical Tool Execution Layer

This is the single, reusable agentic loop. Every frontend (CLI, Telegram,
WhatsApp, API) MUST use this instead of implementing their own.

Design principles:
1. Frontend-agnostic: yields AgenticEvent objects, no UI code
2. LLM-agnostic: takes an async callable `llm_caller` — works with any API
3. Streaming-friendly: events are yielded incrementally
4. Fail-safe: tool errors don't crash the loop, they're fed back to LLM
5. Fully async: never blocks the event loop — all I/O via await

Usage (from any async frontend, e.g. Telegram):
    loop = AgenticLoop(tool_registry, config)
    async for event in loop.run(llm_response, messages, llm_caller):
        if event.type == "tool_start":
            await show("Running Read(path)...")
        elif event.type == "tool_result":
            await show(result_preview)
        elif event.type == "llm_response":
            await display(new_llm_text)

Usage (from sync frontend, e.g. CLI):
    import asyncio
    async def _loop():
        async for event in loop.run(resp, msgs, async_llm_caller):
            handle(event)
    asyncio.run(_loop())

No external dependencies — stdlib + project internals only.
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict, Any, AsyncIterator, Awaitable

logger = logging.getLogger(__name__)

# Lazy import for hooks to avoid circular dependencies
_hooks_module = None


def _get_hooks_module():
    """Lazy load integration_hooks if available."""
    global _hooks_module
    if _hooks_module is None:
        try:
            from agent.evolution import integration_hooks
            _hooks_module = integration_hooks
        except Exception as e:
            logger.debug(f"Integration hooks unavailable: {e}")
    return _hooks_module


@dataclass
class AgenticConfig:
    """Configuration for the agentic loop."""
    max_iterations: int = 10          # Hard limit on tool call rounds
    soft_limit: int = 7               # After this, tell LLM to wrap up
    auto_approve_reads: bool = True   # READ_ONLY tools don't need permission
    tool_output_limit: int = 3000     # Max chars per tool output
    continuation_prompt: str = "Continue based on the tool results above."
    wrapup_prompt: str = (
        "You have used many tool calls. Now STOP making tool calls "
        "and provide your final analysis/summary based on everything "
        "you've gathered so far."
    )
    hooks_enabled: bool = True        # Enable NeoMind evolution hooks
    skill_forge: Optional[Any] = None # Optional SkillForge instance for skill matching


@dataclass
class AgenticEvent:
    """An event yielded by the agentic loop for the frontend to handle.

    Event types:
        tool_start    — a tool call was parsed, about to execute
        tool_result   — tool finished executing, result available
        llm_response  — LLM produced a new response (after tool feedback)
        permission    — asking frontend for permission (frontend sets .approved)
        skill_match   — matching skills found and prepended to context
        skill_record  — skill usage recorded (success/failure)
        done          — loop finished (no more tool calls or max iterations)
        error         — something went wrong
    """
    type: str
    iteration: int = 0
    tool_name: Optional[str] = None
    tool_params: Optional[dict] = None
    tool_preview: Optional[str] = None
    result_success: Optional[bool] = None
    result_output: Optional[str] = None
    result_error: Optional[str] = None
    llm_text: Optional[str] = None
    error_message: Optional[str] = None
    # For permission events — frontend sets this
    approved: bool = True
    # The full feedback message added to history
    feedback_message: Optional[str] = None
    # For skill_match events — matched skills list
    matched_skills: Optional[List[Dict[str, Any]]] = None
    # For skill_record events — skill ID that was recorded
    skill_id: Optional[int] = None


class AgenticLoop:
    """The canonical agentic loop.

    Takes:
        tool_registry — ToolRegistry instance with registered tools
        config — AgenticConfig

    The `run()` method is an async generator that yields AgenticEvent objects.
    The frontend decides how to render them (spinner, live edit, log, etc.).
    """

    def __init__(self, tool_registry, config: AgenticConfig = None):
        self.registry = tool_registry
        self.config = config or AgenticConfig()
        # Lazy import to avoid circular deps
        self._parser = None

    def _get_parser(self):
        if self._parser is None:
            from agent.coding.tool_parser import ToolCallParser
            self._parser = ToolCallParser()
        return self._parser

    async def run(
        self,
        llm_response: str,
        messages: List[Dict[str, str]],
        llm_caller: Callable[[List[Dict[str, str]]], Awaitable[str]],
    ) -> AsyncIterator[AgenticEvent]:
        """Run the agentic loop (async generator).

        Args:
            llm_response: The initial LLM response (may contain tool calls)
            messages: The full conversation history (will be mutated — appended to)
            llm_caller: An async callable that takes messages list and returns
                        LLM response text. This abstracts away the LLM API —
                        any provider works.

        Yields:
            AgenticEvent objects for the frontend to handle.

        The loop:
            0. (First iteration) Match skills from context if skill_forge available
            1. Parse first <tool_call> from llm_response
            2. If none → yield done, return
            3. Yield tool_start event
            4. Execute tool (via asyncio.to_thread for sync tools)
            5. Yield tool_result event
            6. Format result, append to messages as user message
            7. await llm_caller to get new response
            8. Yield llm_response event
            9. Repeat from 1
        """
        parser = self._get_parser()
        current_response = llm_response
        matched_skills = []
        matched_skill_id = None

        for iteration in range(self.config.max_iterations):
            # 0. On first iteration, try to match skills from context
            if iteration == 0 and self.config.skill_forge is not None:
                try:
                    # Build context from latest user message
                    context = {}
                    if messages:
                        last_user_msg = next(
                            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                            ""
                        )
                        context["user_query"] = last_user_msg

                    # Try to find matching skills (assume "chat" mode for now)
                    matched_skills = await asyncio.to_thread(
                        self.config.skill_forge.find_matching_skills, "chat", context
                    )

                    if matched_skills:
                        yield AgenticEvent(
                            type="skill_match",
                            iteration=iteration,
                            matched_skills=matched_skills,
                        )

                        # Optionally prepend skill recipes as system hint
                        if len(matched_skills) > 0:
                            skill_hint = "Relevant skills available:\n"
                            for skill in matched_skills[:3]:  # Top 3 skills
                                skill_hint += f"- {skill['name']}: {skill.get('description', '')}\n"
                            # Could prepend to messages here if desired

                except Exception as e:
                    logger.debug(f"Skill matching failed (non-fatal): {e}")

            # 1. Parse tool call (pure CPU, no I/O — safe to call directly)
            tool_call = parser.parse(current_response)
            if not tool_call:
                if '<tool_call>' in current_response:
                    logger.error(
                        f"[agentic] Response contains <tool_call> but parser returned None! "
                        f"Response snippet: {current_response[:300]}"
                    )
                    print(f"[agentic] ⚠️ tool_call tag present but PARSE FAILED. Snippet: {current_response[:200]}", flush=True)
                yield AgenticEvent(type="done", iteration=iteration)
                return

            # 2. Yield tool_start (frontend can show preview, ask permission)
            event = AgenticEvent(
                type="tool_start",
                iteration=iteration,
                tool_name=tool_call.tool_name,
                tool_params=tool_call.params,
                tool_preview=tool_call.preview(),
            )
            yield event

            # Check if frontend denied permission
            if not event.approved:
                yield AgenticEvent(type="done", iteration=iteration)
                return

            # 3. Execute tool (async — sync tools wrapped via to_thread)
            try:
                result = await self._execute(tool_call)
            except Exception as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                from agent.coding.tools import ToolResult
                result = ToolResult(False, error=str(e))

            # 4. Format result for history
            from agent.coding.tool_parser import format_tool_result
            feedback = format_tool_result(tool_call, result)

            # 5. Yield tool_result (with feedback for frontend to persist)
            yield AgenticEvent(
                type="tool_result",
                iteration=iteration,
                tool_name=tool_call.tool_name,
                result_success=result.success,
                result_output=(result.output or "")[:4000],  # pass more to frontend for foldable display
                result_error=result.error,
                feedback_message=feedback,
            )

            # Record matched skill usage if one was matched
            if matched_skills and self.config.skill_forge is not None:
                matched_skill = matched_skills[0]  # Use top match
                try:
                    context = {
                        "tool_name": tool_call.tool_name,
                        "tool_success": result.success,
                    }
                    await asyncio.to_thread(
                        self.config.skill_forge.record_usage,
                        matched_skill["id"],
                        result.success,
                        0,  # latency_ms
                        context,
                    )

                    yield AgenticEvent(
                        type="skill_record",
                        iteration=iteration,
                        skill_id=matched_skill["id"],
                    )

                except Exception as e:
                    logger.debug(f"Skill recording failed (non-fatal): {e}")

            # After soft limit, tell LLM to wrap up
            if iteration >= self.config.soft_limit - 1:
                continuation = self.config.wrapup_prompt
            else:
                continuation = self.config.continuation_prompt

            combined = feedback + "\n\n" + continuation
            messages.append({"role": "assistant", "content": current_response})
            messages.append({"role": "user", "content": combined})

            # 6a. Call pre_llm_call hook (if enabled)
            pre_call_result = None
            if self.config.hooks_enabled:
                try:
                    hooks = _get_hooks_module()
                    if hooks:
                        pre_call_result = await asyncio.to_thread(
                            hooks.pre_llm_call,
                            prompt=combined,
                            mode="chat",
                            model="deepseek-chat",
                        )
                        if pre_call_result.get("skip_api"):
                            # Degraded to STATIC tier — use fallback
                            fallback = pre_call_result.get("fallback_response", "")
                            logger.info(
                                f"[agentic_loop] pre_llm_call skipping API: {fallback[:100]}..."
                            )
                            current_response = fallback
                        else:
                            # Update prompt if distillation modified it
                            if pre_call_result.get("distillation_used"):
                                combined = pre_call_result.get("modified_prompt", combined)
                                # Update messages with modified prompt
                                messages[-1]["content"] = combined
                except Exception as e:
                    logger.error(f"[agentic_loop] pre_llm_call hook error: {e}", exc_info=True)

            # 6. Call LLM (only if not already handled by fallback)
            if not (pre_call_result and pre_call_result.get("skip_api")):
                try:
                    current_response = await llm_caller(messages)
                except Exception as e:
                    logger.error(f"LLM call error in agentic loop: {e}")
                    yield AgenticEvent(
                        type="error",
                        iteration=iteration,
                        error_message=str(e),
                    )
                    return

            # 6b. Call post_response hook (if enabled)
            if self.config.hooks_enabled:
                try:
                    hooks = _get_hooks_module()
                    if hooks:
                        await asyncio.to_thread(
                            hooks.post_response,
                            prompt=combined,
                            response=current_response,
                            mode="chat",
                            model="deepseek-chat",
                            latency_ms=0,
                            tokens_used=0,
                            cost_usd=0.0,
                            success=True,
                            pre_call_result=pre_call_result,
                        )
                except Exception as e:
                    logger.error(f"[agentic_loop] post_response hook error: {e}", exc_info=True)

            # 7. Yield new LLM response
            yield AgenticEvent(
                type="llm_response",
                iteration=iteration,
                llm_text=current_response,
            )

            # Add to messages for next iteration
            # (Don't add here — next iteration's parse will use current_response,
            #  and if there's a tool call, we'll add it in step 5)

        # Max iterations reached
        yield AgenticEvent(type="done", iteration=self.config.max_iterations)

    async def _execute(self, tool_call):
        """Execute a tool call through the registry.

        Supports both sync and async tool execute functions.
        Sync functions are automatically wrapped with asyncio.to_thread()
        so they never block the event loop.
        """
        tool_def = self.registry.get_tool(tool_call.tool_name)

        if tool_def is None:
            from agent.coding.tools import ToolResult
            return ToolResult(False, error=f"Unknown tool: {tool_call.tool_name}")

        # Validate params
        valid, error = tool_def.validate_params(tool_call.params)
        if not valid:
            from agent.coding.tools import ToolResult
            return ToolResult(False, error=f"Invalid params: {error}")

        # Apply defaults and execute
        params = tool_def.apply_defaults(tool_call.params)

        # Async-aware execution: if the tool is async, await it directly;
        # otherwise run it in a thread to avoid blocking the event loop.
        if asyncio.iscoroutinefunction(tool_def.execute):
            return await tool_def.execute(**params)
        else:
            return await asyncio.to_thread(tool_def.execute, **params)

    def get_tool_prompt(self) -> str:
        """Generate the tool system prompt section from registered tools.

        This should be appended to the system prompt so the LLM knows
        what tools are available and how to call them.
        """
        from agent.coding.tool_schema import generate_tool_prompt
        tools = self.registry.get_all_tools()
        return generate_tool_prompt(tools)
