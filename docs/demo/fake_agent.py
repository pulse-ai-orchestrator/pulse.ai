#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SLUG = "001-media-lista-vazia"
STATE_PATH = ".pulse/specs/project/STATE.md"
TASK_PATH = f".pulse/specs/quick/{SLUG}/TASK.md"
SUMMARY_PATH = f".pulse/specs/quick/{SLUG}/SUMMARY.md"
SOURCE_PATH = "calc.py"
TEST_PATH = "test_calc.py"
TITLE = "media() com lista vazia"

CHUNK_WORDS = 3
CHUNK_PAUSE_SECONDS = 0.04
TOOL_PAUSE_SECONDS = 0.45


def today() -> str:
    return date.today().isoformat()


def task_body(status: str, *, checked: bool) -> str:
    box = "x" if checked else " "
    return f"""# Quick Task 001: {TITLE}

**Date:** {today()}
**Status:** {status}

## Description

`media([])` levanta `ZeroDivisionError`; a média de uma lista vazia deve ser `0.0`.

## Plan

**Approach:** devolver `0.0` quando `valores` estiver vazio, antes da divisão.

## Files to Touch

- `{SOURCE_PATH}` — guarda para lista vazia em `media()`
- `{TEST_PATH}` — teste do caso vazio

## Verification

- [{box}] `pytest -q` passa
- [{box}] `media([])` devolve `0.0`
"""


def state_body(status: str) -> str:
    return f"""# State

**Last Updated:** {datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
**Current Work:** Quick {SLUG}

---

## Quick Tasks

| #   | Description | Date | Spec | Status |
| --- | ----------- | ---- | ---- | ------ |
| 001 | {TITLE} | {today()} | `.pulse/specs/quick/{SLUG}/` | {status} |
"""


def summary_body() -> str:
    return f"""# Summary: Quick Task 001 — {TITLE}

**Completed:** {today()}

## What Changed

- `{SOURCE_PATH}` — `media()` devolve `0.0` para lista vazia
- `{TEST_PATH}` — novo teste `test_media_de_lista_vazia_e_zero`

## Verification

`pytest -q`: 2 passed.
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

PLAN_REPLY = f"""**Quick Task 001:** {TITLE}

- **Spec:** `{TASK_PATH}`
- **Files:** `{SOURCE_PATH}`, `{TEST_PATH}`
- **Approach:** devolver `0.0` antes da divisão quando a lista estiver vazia.
- **Verify:** `pytest -q`, com um teste novo para `media([])`.

```text
Preciso de algumas informações antes de continuar.
1. Aprovar a quick task e implementar?
A) Sim, aprovar e implementar
B) Não, preciso de ajustes (descreva)
C) Cancelar
```
"""

IMPLEMENT_REPLY = f"""Quick Task 001 concluída: `media()` devolve `0.0` com lista vazia, \
coberto por `test_media_de_lista_vazia_e_zero`. `pytest -q`: 2 passed. \
Resumo em `{SUMMARY_PATH}`.

```pulse:outcome
status: done
```
"""


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


def tool(session_id: str, title: str, kind: str, raw_input: dict[str, Any]) -> None:
    tool_id = uuid.uuid4().hex
    call: dict[str, Any] = {
        "sessionUpdate": "tool_call",
        "toolCallId": tool_id,
        "kind": kind,
        "title": title,
        "status": "in_progress",
        "rawInput": raw_input,
    }
    path = raw_input.get("path")
    if path:
        call["locations"] = [{"path": path}]
    update(session_id, call)
    time.sleep(TOOL_PAUSE_SECONDS)
    update(
        session_id,
        {"sessionUpdate": "tool_call_update", "toolCallId": tool_id, "status": "completed"},
    )


def read(session_id: str, cwd: Path, path: str) -> None:
    tool(session_id, "Read File", "read", {"path": str(cwd / path)})


def search(session_id: str, cwd: Path, pattern: str) -> None:
    tool(session_id, "grep", "search", {"pattern": pattern, "path": str(cwd)})


def write(session_id: str, cwd: Path, path: str, body: str) -> None:
    target = cwd / path
    target.parent.mkdir(parents=True, exist_ok=True)
    kind = "edit" if target.exists() else "write"
    target.write_text(body, encoding="utf-8")
    title = "Edit File" if kind == "edit" else "Write File"
    tool(session_id, title, kind, {"path": str(target)})


def plan_turn(session_id: str, cwd: Path) -> None:
    search(session_id, cwd, "def media")
    read(session_id, cwd, SOURCE_PATH)
    read(session_id, cwd, TEST_PATH)
    write(session_id, cwd, STATE_PATH, state_body("⏳ Awaiting Approval"))
    write(session_id, cwd, TASK_PATH, task_body("Awaiting Approval", checked=False))
    stream_text(session_id, PLAN_REPLY)


def implement_turn(session_id: str, cwd: Path) -> None:
    read(session_id, cwd, TASK_PATH)
    write(session_id, cwd, TASK_PATH, task_body("In Progress", checked=False))
    write(session_id, cwd, SOURCE_PATH, FIXED_SOURCE)
    write(session_id, cwd, TEST_PATH, FIXED_TEST)
    tool(session_id, "pytest -q", "execute", {"command": "pytest -q"})
    write(session_id, cwd, TASK_PATH, task_body("Done", checked=True))
    write(session_id, cwd, SUMMARY_PATH, summary_body())
    write(session_id, cwd, STATE_PATH, state_body("✅ Done"))
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
