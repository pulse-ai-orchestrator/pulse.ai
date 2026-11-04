#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

TASK_PATH = ".pulse/specs/quick/001-media-lista-vazia/TASK.md"
SOURCE_PATH = "calc.py"
TEST_PATH = "test_calc.py"

TASK_BODY = """# Quick 001 — media() com lista vazia

**Status:** Awaiting Approval

## Problema
`media([])` levanta `ZeroDivisionError`.

## Abordagem
Devolver `0.0` quando a lista estiver vazia, antes da divisão.

## Arquivos
- `calc.py`
- `test_calc.py`

## Verificação
`pytest -q`
"""

FIXED_SOURCE = """def media(valores: list[float]) -> float:
    if not valores:
        return 0.0
    return sum(valores) / len(valores)
"""

FIXED_TEST = """from calc import media


def test_media_de_valores():
    assert media([2, 4, 6]) == 4


def test_media_de_lista_vazia_e_zero():
    assert media([]) == 0.0
"""

PLAN_REPLY = f"""Spec em `{TASK_PATH}`.

**Causa:** `media()` divide por `len(valores)` sem checar a lista vazia.
**Arquivos:** `{SOURCE_PATH}`, `{TEST_PATH}`.
**Abordagem:** devolver `0.0` antes da divisão.
**Verificação:** `pytest -q`.

```text
Preciso de algumas informações antes de continuar.
1. Aprovar Plano e avançar?
A) Sim, aprovar e continuar
B) Não, preciso de ajustes (descreva)
C) Cancelar workflow
```
"""

IMPLEMENT_REPLY = """Corrigi `media()` para devolver `0.0` com lista vazia e cobri o caso \
em `test_calc.py`. `pytest -q`: 2 passed.

```pulse:outcome
status: done
```
"""

CHUNK_WORDS = 3
CHUNK_PAUSE_SECONDS = 0.05
TOOL_PAUSE_SECONDS = 0.6


def send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def reply(request_id: object, result: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def update(session_id: str, body: dict[str, Any]) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"sessionId": session_id, "update": body},
        }
    )


def chunks(text: str) -> list[str]:
    pieces: list[str] = []
    for line in text.splitlines(keepends=True):
        words = line.split(" ")
        for start in range(0, len(words), CHUNK_WORDS):
            piece = " ".join(words[start : start + CHUNK_WORDS])
            pieces.append(piece if start + CHUNK_WORDS >= len(words) else piece + " ")
    return pieces


def stream_text(session_id: str, text: str) -> None:
    for piece in chunks(text):
        update(
            session_id,
            {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": piece}},
        )
        time.sleep(CHUNK_PAUSE_SECONDS)


def tool(session_id: str, cwd: Path, *, kind: str, title: str, path: str = "") -> None:
    tool_id = uuid.uuid4().hex
    call: dict[str, Any] = {
        "sessionUpdate": "tool_call",
        "toolCallId": tool_id,
        "kind": kind,
        "title": title,
        "status": "in_progress",
    }
    if path:
        absolute = str(cwd / path)
        call["locations"] = [{"path": absolute}]
        call["rawInput"] = {"path": absolute}
    else:
        call["rawInput"] = {"command": title}
    update(session_id, call)
    time.sleep(TOOL_PAUSE_SECONDS)
    update(
        session_id,
        {"sessionUpdate": "tool_call_update", "toolCallId": tool_id, "status": "completed"},
    )


def write(cwd: Path, path: str, body: str) -> None:
    target = cwd / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def plan_turn(session_id: str, cwd: Path) -> None:
    tool(session_id, cwd, kind="read", title=f"Read {SOURCE_PATH}", path=SOURCE_PATH)
    tool(session_id, cwd, kind="read", title=f"Read {TEST_PATH}", path=TEST_PATH)
    write(cwd, TASK_PATH, TASK_BODY)
    tool(session_id, cwd, kind="edit", title=f"Write {TASK_PATH}", path=TASK_PATH)
    stream_text(session_id, PLAN_REPLY)


def implement_turn(session_id: str, cwd: Path) -> None:
    tool(session_id, cwd, kind="read", title=f"Read {TASK_PATH}", path=TASK_PATH)
    write(cwd, SOURCE_PATH, FIXED_SOURCE)
    tool(session_id, cwd, kind="edit", title=f"Edit {SOURCE_PATH}", path=SOURCE_PATH)
    write(cwd, TEST_PATH, FIXED_TEST)
    tool(session_id, cwd, kind="edit", title=f"Edit {TEST_PATH}", path=TEST_PATH)
    tool(session_id, cwd, kind="execute", title="pytest -q")
    stream_text(session_id, IMPLEMENT_REPLY)


def prompt_text(params: dict[str, Any]) -> str:
    blocks = params.get("prompt") or []
    return "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))


def new_session() -> dict[str, Any]:
    return {
        "sessionId": uuid.uuid4().hex,
        "modes": {
            "currentModeId": "agent",
            "availableModes": [{"id": "agent", "name": "Agent"}],
        },
    }


def serve() -> None:
    cwds: dict[str, Path] = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        if request_id is None:
            continue
        if method == "initialize":
            reply(request_id, {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []})
        elif method == "session/new":
            session = new_session()
            cwds[session["sessionId"]] = Path(params.get("cwd") or ".")
            reply(request_id, session)
        elif method == "session/prompt":
            session_id = str(params.get("sessionId"))
            cwd = cwds.get(session_id, Path.cwd())
            turn = implement_turn if "pulse:outcome" in prompt_text(params) else plan_turn
            turn(session_id, cwd)
            reply(request_id, {"stopReason": "end_turn"})
        else:
            reply(request_id, {})


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "acp":
        serve()
    elif command == "--version":
        sys.stdout.write("pulse-demo-agent 1.0\n")
    elif command in {"status", "whoami"}:
        sys.stdout.write("Logged in\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
