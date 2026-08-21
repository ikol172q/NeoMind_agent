"""The dispatch both REPL surfaces share.

Extracted from the line-based loop so the full-screen Application can run the
same one. The risk in an extraction like this is a silently changed branch, so
these assert the three-way contract directly rather than that the code looks
the same.
"""

from __future__ import annotations

from unittest import mock

from cli.neomind_interface import NeoMindInterface


def _iface(local_result):
    iface = NeoMindInterface.__new__(NeoMindInterface)
    iface._handle_local_command = mock.Mock(return_value=local_result)
    iface._stream_and_render = mock.Mock()
    return iface


class TestDispatchPreservesTheThreeWayResult:

    def test_false_stops_the_repl(self):
        iface = _iface(False)
        assert iface._dispatch_input("/exit") is False
        iface._stream_and_render.assert_not_called()

    def test_true_means_handled_and_the_agent_is_not_called(self):
        iface = _iface(True)
        assert iface._dispatch_input("/help") is True
        iface._stream_and_render.assert_not_called()

    def test_none_falls_through_to_the_agent(self):
        """The branch most easily lost in an extraction: an unrecognised slash
        command is not swallowed, it goes to the agent."""
        iface = _iface(None)
        assert iface._dispatch_input("/notacommand") is True
        iface._stream_and_render.assert_called_once_with("/notacommand")

    def test_the_input_reaches_the_command_handler_verbatim(self):
        iface = _iface(True)
        iface._dispatch_input("/model gpt-5  ")
        iface._handle_local_command.assert_called_once_with("/model gpt-5  ")


class TestBothSurfacesUseIt:
    """A second copy of this dispatch is how the headless loop and the REPL
    drifted apart before. Assert on the parsed source, not on a substring —
    a comment mentioning the name would satisfy a grep."""

    @staticmethod
    def _calls_in(func_name):
        import ast
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(getattr(NeoMindInterface, func_name)))
        tree = ast.parse(src)
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_the_line_based_loop_dispatches_through_it(self):
        assert "_dispatch_input" in self._calls_in("run")

    def test_the_loop_no_longer_calls_the_command_handler_itself(self):
        """If it still did, the two paths could diverge again."""
        assert "_handle_local_command" not in self._calls_in("run")
