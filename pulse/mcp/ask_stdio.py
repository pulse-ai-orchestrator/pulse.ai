from __future__ import annotations

import json
import os
import sys
from typing import Any

from pulse.mcp.ask_bridge import SOCKET_ENV, request_ask_question_via_socket
from pulse.mcp.ask_protocol import (
    DEFAULT_PROTOCOL_VERSION,
    SERVER_VERSION,
    RequestId,
    tool_definition,
)

_TOOL_NAME = tool_definition()["name"]


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _handle_initialize(request_id: RequestId) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pulse-ask", "version": SERVER_VERSION},
            },
        }
    )


def _handle_tools_list(request_id: RequestId) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [tool_definition()]},
        }
    )


def _handle_tools_call(request_id: RequestId, params: dict[str, Any]) -> None:
    socket_path = os.environ.get(SOCKET_ENV, "").strip()
    if not socket_path:
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": "PULSE_ASK_SOCKET not configured"},
            }
        )
        return

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    try:
        result = request_ask_question_via_socket(arguments, socket_path=socket_path)
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": result.get("outcome", {}).get("outcome") == "cancelled",
                },
            }
        )
    except OSError as error:
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(error)},
            }
        )


def _dispatch(message: dict[str, Any]) -> None:
    method = str(message.get("method", ""))
    request_id = message.get("id")
    params = message.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        _handle_initialize(request_id)
        return
    if method == "notifications/initialized":
        return
    if method == "tools/list":
        _handle_tools_list(request_id)
        return
    if method == "tools/call":
        _handle_tools_call(request_id, params)
        return
    if request_id is not None:
        _send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not supported: {method}"},
            }
        )


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            _dispatch(message)


if __name__ == "__main__":
    main()
