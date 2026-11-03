from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeAlias

from pulse import __version__
from pulse.domain.ports import PromptPort

DEFAULT_PROTOCOL_VERSION = "2025-06-18"
TOOL_NAME = "AskQuestion"
SERVER_NAME = "pulse-ask"
SERVER_VERSION = __version__

RequestId: TypeAlias = int | str | None
"""A JSON-RPC id; `None` for a notification."""


def tool_definition() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Apresenta perguntas de múltipla escolha ao usuário e aguarda a resposta. "
            "Use para entrevistas e esclarecimentos."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "questionIndex": {"type": "integer"},
                "totalQuestions": {"type": "integer"},
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "label": {"type": "string"},
                                    },
                                    "required": ["id", "label"],
                                },
                            },
                            "allowMultiple": {"type": "boolean"},
                        },
                        "required": ["id", "prompt"],
                    },
                },
            },
            "required": ["questions"],
        },
    }


def _result(request_id: RequestId, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: RequestId, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_tools_call(
    request_id: RequestId,
    params: dict[str, Any],
    prompt_handler: PromptPort,
    on_question: Callable[[], None] | None,
) -> dict[str, Any]:
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    if on_question is not None:
        on_question()
    result = prompt_handler.respond_to_ask_question(arguments)
    outcome = result.get("outcome", {})
    cancelled = isinstance(outcome, dict) and outcome.get("outcome") == "cancelled"
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "isError": cancelled,
        },
    )


def dispatch_message(
    message: dict[str, Any],
    *,
    prompt_handler: PromptPort,
    on_question: Callable[[], None] | None = None,
    protocol_version: str = DEFAULT_PROTOCOL_VERSION,
) -> dict[str, Any] | None:
    method = str(message.get("method", ""))
    request_id = message.get("id")
    params = message.get("params", {})
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if isinstance(requested, str) and requested else protocol_version
        return _result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [tool_definition()]})
    if method == "tools/call":
        return _handle_tools_call(request_id, params, prompt_handler, on_question)
    if request_id is not None:
        return _error(request_id, -32601, f"Method not supported: {method}")
    return None
