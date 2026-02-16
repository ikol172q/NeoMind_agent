# cli/input_handlers.py
def get_multiline_input_with_prompt_toolkit(session):
    """Get multiline input with prompt_toolkit, supporting \ + Enter for line continuation"""
    lines = []
    prompt = "You: "
    continuation_prompt = "... "

    while True:
        try:
            line = session.prompt(
                continuation_prompt if lines else prompt,
                multiline=False,
                enable_history_search=False if lines else True
            )

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


def get_multiline_input_fallback():
    """Fallback multiline input without prompt_toolkit"""
    lines = []
    print("You: ", end="", flush=True)

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