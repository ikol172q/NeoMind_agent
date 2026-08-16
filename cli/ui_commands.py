"""The REPL's own commands, declared into the one registry.

Phase 6A task 2. Commands reached the user through three separate places: the
`CommandDispatcher` registry, a 21-branch `if cmd == ...` chain in
`_handle_local_command`, and the personality handlers on `agent.core`. Fourteen
of those branches were shadowed — the dispatcher answers first and returns, so
editing the legacy `/clear` changed nothing while looking like it should.

Seven commands are genuinely owned by the terminal frontend: they draw, they
read interface state, and they have no meaning to a chat surface. They belong
in the registry as declarations all the same, because "what commands exist" has
to have one answer — otherwise autocomplete, `/help` and mode-availability
checks each learn a different list.

So the handlers stay here, bound to the interface that owns them, and the
registry gains the declarations. Nothing else registers commands into a
frontend's registry: `NeoMindAgent` builds a fresh one per instance, so these
are scoped to this session and never leak into Telegram's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List

from agent.cli_command_system import (
    Command,
    CommandResult,
    CommandSource,
    CommandType,
)

if TYPE_CHECKING:  # pragma: no cover
    from cli.neomind_interface import NeoMindInterface


#: name → (description, modes, method on the interface)
#:
#: `modes=None` means every mode. These mirror what the legacy chain allowed,
#: including `/fleet` being mode-agnostic because a multi-agent monitor is not
#: a property of the personality you happen to be in.
UI_COMMANDS = (
    ("fleet", "Multi-agent fleet monitor and controls", None, "_handle_fleet_command"),
    ("expand", "Show the thinking content from a previous turn", None, "_show_expand"),
    ("freeze", "Restrict edits to one directory", None, "_ui_cmd_freeze"),
    ("unfreeze", "Remove the freeze restriction", None, "_ui_cmd_unfreeze"),
    ("guard", "Careful mode plus freeze, in one step", None, "_ui_cmd_guard"),
    ("sprint", "Run a timeboxed working sprint", None, "_ui_cmd_sprint"),
    ("evidence", "Show the evidence collected for the current claim", None, "_ui_cmd_evidence"),
)


def _make_handler(interface: "NeoMindInterface", method_name: str) -> Callable:
    """Bind a registry command to the interface method that draws it.

    The handler returns an empty `CommandResult` with `display="skip"`: these
    commands print for themselves, and returning their output as text would
    make the dispatcher print it a second time. Control signals, if one ever
    needs them, go through `effects` — never through the text field.
    """

    def handler(args: str, agent=None, **kw) -> CommandResult:
        getattr(interface, method_name)(args)
        return CommandResult(display="skip")

    handler.__name__ = f"ui_{method_name.lstrip('_')}"
    return handler


def register_ui_commands(interface: "NeoMindInterface", registry: Any) -> List[str]:
    """Declare the frontend's commands in `registry`. Returns the names added.

    Skips any name the registry already defines. A frontend quietly overriding
    a shared command is how two implementations of `/clear` happened in the
    first place, and a silent override would hide the next one.
    """
    if registry is None:
        return []

    added: List[str] = []
    for name, description, modes, method_name in UI_COMMANDS:
        if registry.find(name) is not None:
            continue
        if not hasattr(interface, method_name):
            continue
        registry.register(
            Command(
                name=name,
                description=description,
                type=CommandType.LOCAL_UI,
                handler=_make_handler(interface, method_name),
                source=CommandSource.BUILTIN,
                modes=list(modes) if modes else ["chat", "coding", "fin"],
            )
        )
        added.append(name)
    return added
