"""CLI commands when the engine cannot be started or reached.

Each one turns the failure into a message and an exit code (or a local
fallback); none of them may crash with a traceback or hide a bug.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

import pulse.cli.daemon_command as cli_daemon
import pulse.cli.main as cli_main
from pulse.cli.daemon_command import run_daemon_command
from pulse.cli.main import main
from pulse.client.engine_client import EngineClient
from pulse.client.protocol import ENGINE_PROTOCOL


class _UnstartableEngine:
    """An engine whose start fails with `error`, as `ensure_daemon` does on timeout or spawn."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def ensure_daemon(self) -> None:
        raise self._error

    def close(self) -> None:
        return None


def _record_local_doctor(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []

    def fake_doctor(*, test_acp: bool = False, as_json: bool = False) -> int:
        calls.append(test_acp)
        return 0

    monkeypatch.setattr(cli_main, "run_doctor", fake_doctor)
    return calls


def test_doctor_falls_back_to_local_when_the_engine_does_not_start(monkeypatch, capsys):
    """`pulse doctor` exists to diagnose a broken setup, so a dead engine cannot stop it."""
    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: _UnstartableEngine(RuntimeError("no engine"))
    )
    calls = _record_local_doctor(monkeypatch)

    assert main(["doctor"]) == 0

    assert calls == [False]
    assert "no engine" in capsys.readouterr().out


def test_doctor_falls_back_to_local_when_the_engine_errors(monkeypatch, capsys):
    """A live engine that fails the doctor request is just as unusable as a dead one."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"ok": True, "protocol": ENGINE_PROTOCOL})
        return httpx.Response(500, json={"detail": "boom"})

    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: EngineClient(transport=httpx.MockTransport(handler))
    )
    calls = _record_local_doctor(monkeypatch)

    assert main(["doctor", "--test-acp"]) == 0

    assert calls == [True]
    assert "500" in capsys.readouterr().out


def test_doctor_falls_back_to_local_when_the_engine_answers_without_json(monkeypatch, capsys):
    """A non-JSON body means no usable engine, as `EngineClient.ping` already reads it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"ok": True, "protocol": ENGINE_PROTOCOL})
        return httpx.Response(200, text="<html>not the engine</html>")

    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: EngineClient(transport=httpx.MockTransport(handler))
    )
    calls = _record_local_doctor(monkeypatch)

    assert main(["doctor"]) == 0

    assert calls == [False]
    assert "using the local doctor" in capsys.readouterr().out


def test_doctor_does_not_hide_a_bug_as_an_engine_outage(monkeypatch):
    """Only engine failures fall back; a programming error must surface as itself."""
    monkeypatch.setattr(cli_main, "EngineClient", lambda: _UnstartableEngine(KeyError("bug")))
    _record_local_doctor(monkeypatch)

    with pytest.raises(KeyError, match="bug"):
        main(["doctor"])


@pytest.mark.parametrize("error", [RuntimeError("timeout"), OSError("spawn failed")])
def test_daemon_start_failure_exits_with_an_error(monkeypatch, capsys, error: Exception):
    """`pulse daemon start` reports the failure and exits 1 so scripts can react."""
    monkeypatch.setattr(cli_daemon, "is_daemon_alive", lambda: False)
    monkeypatch.setattr(cli_daemon, "EngineClient", lambda: _UnstartableEngine(error))

    assert run_daemon_command("start") == 1

    assert capsys.readouterr().out == f"[pulse] Failed to start the engine: {error}\n"


def test_the_tui_opens_even_when_the_engine_does_not_start(monkeypatch, capsys):
    """The TUI shows the engine state itself; a failed start is a warning, not an abort."""
    opened: list[Any] = []
    monkeypatch.setattr(cli_main, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_main, "global_config_exists", lambda: True)
    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: _UnstartableEngine(OSError("spawn failed"))
    )
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", lambda: opened.append(True) or 0)

    assert main([]) == 0

    assert opened == [True]
    assert "spawn failed" in capsys.readouterr().out
