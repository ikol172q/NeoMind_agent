#!/usr/bin/env python3
# main.py - Entry point for neomind Agent

import sys
import os

# ── Fast-path dispatch ──────────────────────────────────────────
# Handle simple flags BEFORE loading any heavy modules.
# This avoids importing agent/, prompt_toolkit, openai, etc.
# for trivial operations like --version or --help.
def _fast_path():
    """Check for fast-path arguments that don't need full module loading."""
    args = sys.argv[1:]
    if '--version' in args or '-V' in args:
        # Read version from pyproject.toml without importing anything
        try:
            _root = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(_root, 'pyproject.toml')) as f:
                for line in f:
                    if line.strip().startswith('version'):
                        ver = line.split('=')[1].strip().strip('"').strip("'")
                        print(f"neomind-agent version {ver}")
                        sys.exit(0)
        except Exception:
            pass
        print("neomind-agent version 0.2.0")
        sys.exit(0)

    if '--dump-system-prompt' in args:
        # Dump system prompt without loading the full agent
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from agent_config import agent_config
            mode = 'coding' if '--mode' in args and 'coding' in args else 'chat'
            agent_config.switch_mode(mode)
            print(agent_config.system_prompt or "(no system prompt)")
        except Exception as e:
            print(f"Error: {e}")
        sys.exit(0)

    if '--help' in args or '-h' in args:
        return  # Let argparse handle it normally

    if '-p' in args or '--print' in args:
        return  # Let argparse handle headless mode normally

    if '--resume' in args:
        return  # Let argparse handle resume

_fast_path()

# Fix for Windows terminal detection in MINGW/Cygwin before any prompt_toolkit imports
if sys.platform == "win32" and "xterm" in os.environ.get("TERM", ""):
    os.environ["PROMPT_TOOLKIT_NO_WIN32_CONSOLE"] = "1"
    os.environ["PROMPT_TOOLKIT_FORCE_VT100_OUTPUT"] = "1"

import argparse
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def interactive_main(mode: str = "chat", resume_session: str = None,
                     system_prompt: str = None, verbose: bool = False,
                     cwd: str = None, max_turns: int = None):
    """Launch interactive session in the specified mode.

    Args:
        mode: 'chat' or 'coding' — determines config, commands, and behavior
        resume_session: session name/id to resume
        system_prompt: custom system prompt override
        verbose: enable verbose/debug mode
        cwd: working directory override
        max_turns: max agentic loop iterations
    """
    # Apply working directory override
    if cwd:
        cwd_path = os.path.abspath(os.path.expanduser(cwd))
        if os.path.isdir(cwd_path):
            os.chdir(cwd_path)
        else:
            print(f"Warning: --cwd path does not exist: {cwd_path}", file=sys.stderr)
    # Run startup migrations
    try:
        from agent.migrations import run_startup_migrations
        run_startup_migrations()
    except Exception:
        pass  # Non-fatal

    # Set mode on config before anything else
    from agent_config import agent_config
    if mode != agent_config.mode:
        agent_config.switch_mode(mode)

    # Apply verbose mode to config
    if verbose:
        from agent_config import agent_config as _cfg
        _cfg.verbose = True

    # Apply custom system prompt
    if system_prompt:
        from agent_config import agent_config as _cfg2
        _cfg2.system_prompt = system_prompt

    # Try NeoMind interface first (preferred)
    try:
        from cli.neomind_interface import interactive_chat
        interactive_chat(
            mode=mode,
            resume_session=resume_session,
            system_prompt=system_prompt,
            verbose=verbose,
            max_turns=max_turns,
        )
        return
    except Exception as e:
        print(f"Note: NeoMind interface unavailable ({e}), falling back to standard interface")

    # Fallback chain
    try:
        from prompt_toolkit import PromptSession
        from cli.interface import interactive_chat_with_prompt_toolkit
        interactive_chat_with_prompt_toolkit(mode)
    except ImportError:
        print("Note: For better experience, install prompt_toolkit: pip install prompt_toolkit")
        from cli.interface import interactive_chat_fallback
        interactive_chat_fallback(mode)


def test_main():
    """Run development tests"""
    try:
        import dev_test
        success = dev_test.run_tests()
        sys.exit(0 if success else 1)
    except ImportError:
        print("Error: dev_test.py not found")
        sys.exit(1)


#: What a run with no human present may do. An explicit list, not a filter
#: over `permission_level`, because that field is wrong for several tools:
#: TeamDelete ("Delete an existing team"), TeamCreate, SendMessage ("Send a
#: message to another agent or user"), TodoWrite, TaskCreate and TaskStop all
#: declare READ_ONLY today. Deriving "safe unattended" from that declaration
#: means deriving safety from a mislabelling, so headless names what it wants
#: instead. Also excluded, though harmless in themselves: AskUser (there is
#: nobody to ask), Sleep (can stall a CI run), Brief and Enter/ExitPlanMode
#: (mutate session state), and Skill (invokes arbitrary registered skills,
#: which may write).
HEADLESS_READ_ONLY_TOOLS = (
    "CronList",
    "CtxInspect",
    "GitDiff",
    "GitLog",
    "GitStatus",
    "Glob",
    "Grep",
    "LS",
    "ListMcpResources",
    "Read",
    "ReadMcpResource",
    "SyntheticOutput",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "ToolSearch",
    "VerifyPlanExecution",
    "WebFetch",
    "WebSearch",
)


def _headless_allowed_tools(registry):
    """Intersect the allowlist with what is registered and still READ_ONLY.

    Both halves matter. The allowlist keeps a mislabelled side-effecting tool
    out even if it is registered; re-checking the level keeps a tool out if its
    declaration is ever tightened, so the list cannot silently re-widen.
    """
    from agent.coding.tool_schema import PermissionLevel

    out = []
    for name in HEADLESS_READ_ONLY_TOOLS:
        tool = registry.get_tool(name)
        if tool is None:
            continue
        if getattr(tool, "permission_level", None) is not PermissionLevel.READ_ONLY:
            continue
        out.append(name)
    return out


def _build_headless_session(agent, *, tool_parser=None):
    """Compose an `AgentSession` for a non-interactive run.

    The wiring lives here rather than in `agent/runtime/` on purpose: the
    runtime must not know which provider or which registry a surface picked,
    and `tests/runtime/test_import_boundary.py` enforces that. This function is
    the composition root for `-p`.

    Safety comes from the capability snapshot, not from remembering to check.
    The snapshot lists only tools whose definition declares READ_ONLY, so the
    executor refuses everything else before a permission question is ever
    asked — there is no human here to answer one.
    """
    from agent.coding.tool_schema import PermissionLevel
    from agent.runtime.permissions import CapabilitySnapshot, PermissionPolicy
    from agent.runtime.providers.openai_sse import OpenAICompatibleStream
    from agent.runtime.session import AgentSession
    from agent.runtime.tool_executor import ToolExecutor
    from agent.tools import ToolRegistry

    provider = agent._resolve_provider()
    llm = OpenAICompatibleStream(
        provider["base_url"],
        provider["api_key"] or agent.api_key,
        timeout=90.0,
    )

    registry = ToolRegistry(working_dir=os.getcwd())
    allowed = _headless_allowed_tools(registry)
    executor = ToolExecutor(
        registry=registry,
        policy=PermissionPolicy(capabilities=CapabilitySnapshot.only(*allowed)),
        working_dir=os.getcwd(),
    )

    if tool_parser is None:
        from agent.coding.tool_parser import ToolCallParser

        tool_parser = ToolCallParser()

    llm_kwargs = {}
    if getattr(agent, "thinking_enabled", False) and provider.get("name") == "deepseek":
        llm_kwargs["thinking"] = {"type": "enabled"}

    return AgentSession(
        llm=llm,
        executor=executor,
        model=agent.model,
        mode=getattr(agent, "mode", "chat"),
        history=list(getattr(agent, "conversation_history", []) or []),
        tool_parser=tool_parser,
        llm_kwargs=llm_kwargs,
    )


def _headless_session_v1(agent, prompt: str, output_format: str) -> int:
    """The `session_v1` path: one session, one event stream, no local loop."""
    import asyncio

    from agent.runtime.headless import consume, render

    session = _build_headless_session(agent)
    result = asyncio.run(consume(session.run_turn(prompt)))
    text = render(result, output_format)
    if result.ok:
        print(text)
        return 0
    print(text, file=sys.stderr)
    return 1


def headless_main(prompt: str, mode: str = "chat", output_format: str = "text",
                  system_prompt: str = None):
    """Run a single prompt in headless (non-interactive) mode.

    Used by the -p/--print flag for CI/CD, automation, and piping.
    Supports the agentic loop: if the LLM emits <tool_call> blocks,
    they are parsed, executed, and results fed back automatically.

    Args:
        prompt: The user prompt to process
        mode: Session mode (chat, coding, fin)
        output_format: 'text' (default) or 'json'
        system_prompt: Custom system prompt override
    """
    import json as _json
    import re as _re

    # Suppress all status/debug output in headless mode.
    # logging.disable() is process-global and was never undone, so anything
    # that called headless_main and kept running — a long-lived host, or the
    # test suite — had every logger silently dead from then on. Restore the
    # previous level on the way out.
    import logging
    _prev_logging_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)

    try:
        from agent_config import agent_config
        if mode != agent_config.mode:
            agent_config.switch_mode(mode)

        # Apply custom system prompt
        if system_prompt:
            agent_config.system_prompt = system_prompt

        from agent.core import NeoMindAgent
        agent = NeoMindAgent()

        # If a custom system prompt was provided, strip all other system
        # messages (vault context, shared memory, etc.) so the custom
        # prompt is the sole instruction the LLM follows.
        if system_prompt:
            agent.conversation_history = [
                msg for msg in agent.conversation_history
                if msg.get("role") != "system"
            ]
            agent.conversation_history.insert(
                0, {"role": "system", "content": system_prompt}
            )
            # Prevent stream_response from re-injecting default prompts
            # or code context instructions that would dilute the override.
            agent._custom_system_prompt_override = True

        # In headless mode: auto-accept reads, deny writes
        agent.verbose_mode = False

        # ── D8 rollback switch: legacy | session_v1 ──────────────────
        # session_v1 runs the turn through AgentSession, so there is one
        # authorization path instead of two. The legacy branch below is the
        # hand-rolled parse/execute/continue loop it replaces, kept only until
        # the Phase 3 real-surface gates have run in anger; it is not a second
        # runtime to maintain. Set NEOMIND_HEADLESS=legacy to fall back.
        if os.environ.get("NEOMIND_HEADLESS", "session_v1").strip() != "legacy":
            sys.exit(_headless_session_v1(agent, prompt, output_format))

        # Suppress streaming output (thinking, status, etc.) during execution
        # by redirecting stdout to devnull, then restoring for final output
        import io
        original_stdout = sys.stdout
        sys.stdout = io.StringIO()  # capture/suppress streaming prints

        try:
            response = agent.stream_response(prompt)
        finally:
            sys.stdout = original_stdout

        if not response:
            response = "(no response)"

        # ── Headless agentic loop ────────────────────────────────────
        # If the LLM response contains <tool_call> blocks, parse and
        # execute them, then feed results back for up to N iterations.
        _HEADLESS_MAX_ITERATIONS = 10
        try:
            from agent.coding.tool_parser import ToolCallParser
            from agent.coding.tool_schema import PermissionLevel
            from agent.tools import ToolRegistry

            parser = ToolCallParser()
            registry = ToolRegistry(working_dir=os.getcwd())

            for _iter in range(_HEADLESS_MAX_ITERATIONS):
                tool_call = parser.parse(response)
                if not tool_call:
                    break  # No more tool calls — done

                # Headless mode has no user available to approve side effects.
                # Fail closed: only an explicitly READ_ONLY definition may run.
                tool_def = registry.get_tool(tool_call.tool_name) if registry else None
                if tool_def is None:
                    result_text = (
                        "Permission denied: unknown tools cannot run in "
                        "non-interactive headless mode."
                    )
                elif getattr(tool_def, "permission_level", None) is not PermissionLevel.READ_ONLY:
                    result_text = (
                        "Permission denied: headless mode only allows read-only "
                        "tools; this tool was not executed."
                    )
                else:
                    try:
                        params = tool_def.apply_defaults(tool_call.params)
                        result = tool_def.execute(**params)
                        result_text = str(result) if result else "(no output)"
                    except Exception as exec_err:
                        result_text = f"Error: {exec_err}"

                # Truncate large tool output
                if len(result_text) > 5000:
                    result_text = result_text[:5000] + "\n... [truncated]"

                # Do not persist the raw tool payload in conversation history.
                clean_response = parser.strip_tool_call(response, tool_call)

                # Feed tool result back to LLM
                # stream_response() normally persisted the raw assistant reply
                # already. Replace that exact entry in place; blindly appending
                # a sanitized duplicate leaves the executable payload earlier
                # in real history (a side effect mocks do not reproduce).
                replaced_raw_response = False
                history = getattr(agent, "conversation_history", None)
                if isinstance(history, list):
                    for message in reversed(history):
                        if (
                            isinstance(message, dict)
                            and message.get("role") == "assistant"
                            and message.get("content") == response
                        ):
                            message["content"] = clean_response
                            replaced_raw_response = True
                            break
                if not replaced_raw_response:
                    agent.add_to_history("assistant", clean_response)
                agent.add_to_history("user",
                    f"Tool result for {tool_call.tool_name}:\n{result_text}\n\n"
                    "Continue based on the tool results above."
                )

                # Get next LLM response (suppress output)
                sys.stdout = io.StringIO()
                try:
                    response = agent.stream_response(
                        "[Continue based on the tool results above.]"
                    )
                finally:
                    sys.stdout = original_stdout

                if not response:
                    response = "(no response)"

        except ImportError:
            pass  # Tool system not available — return raw response

        # Strip any remaining standard or DeepSeek pipe-delimited tool-call
        # blocks from final output.
        response = _re.sub(
            r'(?:<tool_call>|<\|tool_call(?:_begin)?\|>)'
            r'.*?'
            r'(?:</tool_(?:call|result|report|re)\s*>'
            r'|<\|(?:/tool_call(?:_end)?|tool_call_end)\|>)',
            '', response, flags=_re.DOTALL,
        ).strip()
        # An incomplete/malformed invocation must not leak when parsing could
        # not produce a ToolCall.
        response = _re.sub(
            r'(?:<tool_call>|<\|tool_call(?:_begin)?\|>).*\Z',
            '', response, flags=_re.DOTALL,
        ).strip()
        # Strip orphan closing tags.
        response = _re.sub(
            r'(?:</tool_(?:call|result|report|re)\s*>'
            r'|<\|(?:/tool_call(?:_end)?|tool_call_end)\|>)',
            '', response,
        ).strip()

        if not response:
            response = "(no response)"

        if output_format == "json":
            # Estimate token count (chars / 4)
            tokens = len(response) // 4
            output = _json.dumps({"response": response, "tokens": tokens}, ensure_ascii=False)
            print(output)
        else:
            print(response)

        sys.exit(0)

    except KeyboardInterrupt:
        if output_format == "json":
            print(_json.dumps({"error": "Interrupted"}, ensure_ascii=False), file=sys.stderr)
        else:
            print("Interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        if output_format == "json":
            import json as _json
            print(_json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        logging.disable(_prev_logging_disable)


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description="neomind AI Agent — Chat, Coding, or Finance mode",
        epilog="Examples:\n"
               "  python main.py --mode chat     # General conversation\n"
               "  python main.py --mode coding   # NeoMind coding assistant\n"
               "  python main.py --mode fin      # Personal finance & investment intelligence\n"
               "  python main.py -p 'What is 2+2?'   # Headless single-turn mode\n"
               "  echo 'Hello' | python main.py -p    # Read prompt from stdin\n"
               "  python main.py --resume my-session  # Resume a saved session\n"
               "  python main.py --verbose            # Debug mode\n"
               "  python main.py --cwd ~/project      # Set working directory\n"
               "  python main.py --max-turns 5        # Limit tool call rounds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'run_mode',
        nargs='?',
        default='interactive',
        choices=['interactive', 'test'],
        help="Run mode: interactive session or development tests"
    )
    parser.add_argument(
        '--mode',
        default='chat',
        choices=['chat', 'coding', 'fin'],
        help="Session mode: chat (conversation), coding (NeoMind), or fin (finance intelligence). Default: chat"
    )
    parser.add_argument(
        '-p', '--print',
        nargs='?',
        const='__STDIN__',
        default=None,
        metavar='PROMPT',
        dest='print_prompt',
        help="Headless/print mode: run a single prompt and exit. "
             "If PROMPT is omitted, reads from stdin."
    )
    parser.add_argument(
        '--output-format',
        default='text',
        choices=['text', 'json'],
        help="Output format for headless mode. Default: text"
    )
    parser.add_argument(
        '--resume',
        default=None,
        metavar='SESSION_NAME',
        help="Resume a previous saved session by name or ID"
    )
    parser.add_argument(
        '--system-prompt',
        default=None,
        metavar='TEXT',
        help="Custom system prompt to override the default"
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        default=False,
        help="Enable verbose/debug mode"
    )
    parser.add_argument(
        '--cwd',
        default=None,
        metavar='PATH',
        help="Set working directory for the session"
    )
    parser.add_argument(
        '--max-turns',
        type=int,
        default=None,
        metavar='N',
        help="Limit agentic loop iterations (default: 15)"
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help="Show version information"
    )

    args = parser.parse_args()

    if args.version:
        # Fast-path already handled this, but in case it gets here
        print("neomind-agent version 0.2.0")
        return

    # Headless/print mode
    if args.print_prompt is not None:
        if args.print_prompt == '__STDIN__':
            # Read prompt from stdin
            if sys.stdin.isatty():
                print("Error: -p without a prompt requires piped stdin input.", file=sys.stderr)
                sys.exit(1)
            prompt = sys.stdin.read().strip()
        else:
            prompt = args.print_prompt

        if not prompt:
            print("Error: empty prompt.", file=sys.stderr)
            sys.exit(1)

        headless_main(prompt, mode=args.mode, output_format=args.output_format,
                      system_prompt=args.system_prompt)
        return

    if args.run_mode == 'test':
        test_main()
    else:
        interactive_main(
            mode=args.mode,
            resume_session=args.resume,
            system_prompt=args.system_prompt,
            verbose=args.verbose,
            cwd=args.cwd,
            max_turns=args.max_turns,
        )


if __name__ == "__main__":
    main()
