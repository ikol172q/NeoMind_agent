# cli/input_handlers.py
from typing import Optional

try:
    from prompt_toolkit.completion import Completer
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    Completer = None

from agent_config import agent_config


def get_multiline_input_with_prompt_toolkit(session, mode: str = "chat", completer: Optional[Completer] = None, debug: Optional[bool] = None):
    """Get multiline input with prompt_toolkit, supporting \ + Enter for line continuation"""
    import sys
    if debug is None:
        debug = agent_config.debug
    if debug:
        sys.stderr.write(f"[DEBUG] get_multiline_input_with_prompt_toolkit called with mode='{mode}'\n")
        sys.stderr.flush()
    lines = []
    # Use simplified prompt for coding mode (like Claude CLI)
    # Normalize mode string for comparison
    normalized_mode = mode.strip().lower()
    prompt = "> " if normalized_mode == "coding" else f"[{mode.strip()}] > "
    continuation_prompt = "... "

    while True:
        try:
            # Build prompt arguments with optional parameters for compatibility
            # Get the signature of session.prompt to only pass supported parameters
            import inspect
            try:
                sig = inspect.signature(session.prompt)
                supported_params = set(sig.parameters.keys())
            except Exception:
                # Fallback to a basic set of parameters if inspection fails
                supported_params = {"message", "multiline", "completer", "complete_while_typing"}

            # Determine the correct parameter name for the prompt message
            prompt_param_name = "message"  # default for newer versions
            if "prompt" in supported_params:
                prompt_param_name = "prompt"
            elif "message" in supported_params:
                prompt_param_name = "message"

            # Build argument dictionary with only supported parameters
            prompt_args = {}
            # Add prompt/message
            prompt_args[prompt_param_name] = continuation_prompt if lines else prompt

            # Add other parameters only if they are supported
            if "multiline" in supported_params:
                prompt_args["multiline"] = False
            if "enable_history_search" in supported_params:
                prompt_args["enable_history_search"] = False if lines else True
            if "completer" in supported_params and completer is not None:
                prompt_args["completer"] = completer
            if "complete_while_typing" in supported_params:
                prompt_args["complete_while_typing"] = True
            if "complete_in_thread" in supported_params:
                prompt_args["complete_in_thread"] = True

            line = session.prompt(**prompt_args)

            if line.rstrip().endswith('\\'):
                lines.append(line.rstrip()[:-1])
                continue
            else:
                lines.append(line)
                break

        except KeyboardInterrupt:
            print("\n[Input cancelled]")
            return None
        except EOFError:
            print()
            break

    if not lines:
        return None

    return '\n'.join(lines)


def get_multiline_input_fallback(mode: str = "chat", debug: Optional[bool] = None):
    """Fallback multiline input without prompt_toolkit"""
    import sys
    if debug is None:
        debug = agent_config.debug
    if debug:
        sys.stderr.write(f"[DEBUG] get_multiline_input_fallback called with mode='{mode}'\n")
        sys.stderr.flush()
    lines = []
    # Use simplified prompt for coding mode (like Claude CLI)
    # Normalize mode string for comparison
    normalized_mode = mode.strip().lower()
    prompt = "> " if normalized_mode == "coding" else f"[{mode.strip()}] > "
    print(prompt, end="", flush=True)

    while True:
        try:
            line = input()

            if line.rstrip().endswith('\\'):
                lines.append(line.rstrip()[:-1])
                print("... ", end="", flush=True)
                continue
            else:
                lines.append(line)
                break

        except KeyboardInterrupt:
            print("\n[Input cancelled]")
            return None
        except EOFError:
            print()
            break

    if not lines:
        return None

    return '\n'.join(lines)