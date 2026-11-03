"""The stdio MCP server the agent talks to: JSON-RPC lines in, JSON-RPC lines out.

Each test feeds real lines through stdin and reads what `main` wrote to stdout;
`tools/call` goes through a real `AskQuestionBridgeServer` on a Unix socket.
"""

from __future__ import annotations

import io
import json
import socket
import sys
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pulse import __version__
from pulse.domain.ports import JsonObject, NullPromptPort
from pulse.mcp import ask_stdio
from pulse.mcp.ask_bridge import SOCKET_ENV, AskQuestionBridgeServer
from pulse.mcp.ask_protocol import DEFAULT_PROTOCOL_VERSION, TOOL_NAME

ANSWERED: JsonObject = {
    "outcome": {
        "outcome": "answered",
        "answers": [{"questionId": "q1", "selectedOptionIds": ["py"]}],
    }
}


class _RecordingPrompts(NullPromptPort):
    def __init__(self, reply: JsonObject) -> None:
        self.reply = reply
        self.calls: list[JsonObject] = []

    def respond_to_ask_question(self, params: JsonObject) -> JsonObject:
        self.calls.append(params)
        return self.reply


@pytest.fixture
def socket_path() -> Iterator[Path]:
    """A short private directory: `tmp_path` can exceed the AF_UNIX path limit on macOS."""
    with tempfile.TemporaryDirectory(prefix="pulse-") as directory:
        yield Path(directory) / "ask.sock"


def _serve(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> list[Any]:
    """Run the server over `lines` and return every message it wrote."""
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(f"{line}\n" for line in lines)))
    monkeypatch.setattr(sys, "stdout", stdout)
    ask_stdio.main()
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def _call(request_id: int, arguments: object) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": arguments},
        }
    )


def test_initialize_announces_the_server_and_its_tool_capability(
    monkeypatch: pytest.MonkeyPatch,
):
    [reply] = _serve(monkeypatch, [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})])

    assert reply == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": DEFAULT_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pulse-ask", "version": __version__},
        },
    }


def test_initialize_announces_the_stamped_package_version(monkeypatch: pytest.MonkeyPatch):
    """A release stamps ``pulse.__version__``; the server must read that value, not a copy."""
    monkeypatch.setattr(ask_stdio, "SERVER_VERSION", "9.9.9")

    [reply] = _serve(monkeypatch, [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})])

    assert reply["result"]["serverInfo"]["version"] == "9.9.9"


def test_tools_list_offers_only_the_ask_question_tool(monkeypatch: pytest.MonkeyPatch):
    [reply] = _serve(
        monkeypatch, [json.dumps({"jsonrpc": "2.0", "id": "a", "method": "tools/list"})]
    )

    assert reply["id"] == "a"
    tools = reply["result"]["tools"]
    assert [tool["name"] for tool in tools] == [TOOL_NAME]
    assert tools[0]["inputSchema"]["required"] == ["questions"]


def test_noise_on_stdin_is_skipped_and_the_valid_lines_still_answered(
    monkeypatch: pytest.MonkeyPatch,
):
    """A stray line from the agent must not kill the server mid-session."""
    replies = _serve(
        monkeypatch,
        [
            "",
            "   ",
            "{not json",
            "[1, 2]",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": "bad"}),
        ],
    )

    assert [reply["id"] for reply in replies] == [7]


def test_an_unknown_method_is_an_error_only_when_it_expects_a_reply(
    monkeypatch: pytest.MonkeyPatch,
):
    replies = _serve(
        monkeypatch,
        [
            json.dumps({"jsonrpc": "2.0", "method": "resources/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "resources/list"}),
        ],
    )

    assert replies == [
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {"code": -32601, "message": "Method not supported: resources/list"},
        }
    ]


def test_tools_call_without_the_socket_env_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(SOCKET_ENV, "   ")
    [reply] = _serve(monkeypatch, [_call(4, {"questions": []})])

    assert reply == {
        "jsonrpc": "2.0",
        "id": 4,
        "error": {"code": -32603, "message": f"{SOCKET_ENV} not configured"},
    }


def test_tools_call_relays_the_arguments_and_returns_the_answer_as_text(
    monkeypatch: pytest.MonkeyPatch, socket_path: Path
):
    prompts = _RecordingPrompts(ANSWERED)
    server = AskQuestionBridgeServer(socket_path=socket_path, prompt_handler=prompts)
    server.start()
    monkeypatch.setenv(SOCKET_ENV, str(socket_path))
    arguments = {"questions": [{"id": "q1", "prompt": "Qual stack?"}]}
    try:
        [reply] = _serve(monkeypatch, [_call(5, arguments)])
    finally:
        server.close()

    assert prompts.calls == [arguments]
    result = reply["result"]
    assert reply["id"] == 5
    assert result["isError"] is False
    [content] = result["content"]
    assert content["type"] == "text"
    assert json.loads(content["text"]) == ANSWERED


def test_a_cancelled_answer_is_flagged_as_a_tool_error(
    monkeypatch: pytest.MonkeyPatch, socket_path: Path
):
    """The agent must see a cancellation as a failed call, not as an empty answer."""
    prompts = _RecordingPrompts({"outcome": {"outcome": "cancelled"}})
    server = AskQuestionBridgeServer(socket_path=socket_path, prompt_handler=prompts)
    server.start()
    monkeypatch.setenv(SOCKET_ENV, str(socket_path))
    try:
        [reply] = _serve(monkeypatch, [_call(6, "not an object")])
    finally:
        server.close()

    assert prompts.calls == [{}]
    assert reply["result"]["isError"] is True


def test_an_unreachable_socket_is_reported_as_an_internal_error(
    monkeypatch: pytest.MonkeyPatch, socket_path: Path
):
    monkeypatch.setenv(SOCKET_ENV, str(socket_path))
    [reply] = _serve(monkeypatch, [_call(8, {"questions": []})])

    assert reply["id"] == 8
    error = reply["error"]
    assert error["code"] == -32603
    assert error["message"]


def test_a_bridge_that_closes_without_answering_reads_as_cancelled(
    monkeypatch: pytest.MonkeyPatch, socket_path: Path
):
    """No reply on the socket means nobody answered: never a delivered answer."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(socket_path))
        listener.listen(1)
        stdout = io.StringIO()
        monkeypatch.setenv(SOCKET_ENV, str(socket_path))
        monkeypatch.setattr(sys, "stdin", io.StringIO(_call(9, {}) + "\n"))
        monkeypatch.setattr(sys, "stdout", stdout)

        def hang_up() -> None:
            connection, _ = listener.accept()
            with connection:
                while connection.recv(4096):
                    pass

        worker = threading.Thread(target=hang_up)
        worker.start()
        ask_stdio.main()
        worker.join(timeout=5)

    [reply] = [json.loads(line) for line in stdout.getvalue().splitlines()]
    result = reply["result"]
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == {"outcome": {"outcome": "cancelled"}}
