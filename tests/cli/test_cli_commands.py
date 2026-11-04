"""CLI commands against a reachable engine: what is printed and which exit code is returned.

The engine is a real `EngineClient` over `httpx.MockTransport`, so the HTTP
requests the CLI makes are the ones checked; the TUI entry points are replaced
at their import seam since opening Textual is out of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import pulse.cli.daemon_command as cli_daemon
import pulse.cli.main as cli_main
from pulse import __version__
from pulse.cli.daemon_command import run_daemon_command
from pulse.cli.main import main
from pulse.client.engine_client import EngineClient
from pulse.client.protocol import ENGINE_PROTOCOL
from pulse.history import status_labels
from pulse.tui.brand import PULSE_LINE, PULSE_WAVE


class _Engine:
    """A current engine answering the doctor routes with fixed payloads."""

    def __init__(self, checks: list[dict[str, str]], probe: dict[str, Any] | None = None):
        self.checks = checks
        self.probe = probe or {"ok": True, "message": "connected"}
        self.paths: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"ok": True, "protocol": ENGINE_PROTOCOL})
        if request.url.path == "/api/doctor":
            return httpx.Response(200, json={"checks": self.checks})
        if request.url.path == "/api/doctor/acp-probe":
            return httpx.Response(200, json=self.probe)
        return httpx.Response(404, json={"detail": "unknown"})


def _use_engine(monkeypatch: pytest.MonkeyPatch, module: Any, engine: _Engine) -> None:
    monkeypatch.setattr(
        module, "EngineClient", lambda: EngineClient(transport=httpx.MockTransport(engine))
    )


def _no_local_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*, test_acp: bool = False, as_json: bool = False) -> int:
        raise AssertionError("the local doctor must not run while the engine answers")

    monkeypatch.setattr(cli_main, "run_doctor", refuse)


def test_doctor_prints_each_engine_check_and_passes_without_failures(monkeypatch, capsys):
    engine = _Engine(
        [
            {"status": "ok", "name": "claude", "message": "found"},
            {"status": "warn", "name": "cursor", "message": "not logged in"},
        ]
    )
    _use_engine(monkeypatch, cli_main, engine)
    _no_local_doctor(monkeypatch)

    assert main(["doctor"]) == 0

    assert capsys.readouterr().out == "[ok] claude: found\n[warn] cursor: not logged in\n"
    assert "/api/doctor/acp-probe" not in engine.paths


def test_doctor_exits_1_when_a_check_fails(monkeypatch, capsys):
    """Scripts gate on the exit code; a failed check must not exit 0."""
    engine = _Engine([{"status": "fail", "name": "git", "message": "missing"}])
    _use_engine(monkeypatch, cli_main, engine)
    _no_local_doctor(monkeypatch)

    assert main(["doctor"]) == 1

    assert capsys.readouterr().out == "[FAIL] git: missing\n"


def test_doctor_shows_an_unknown_status_as_a_failure_mark_without_failing(monkeypatch, capsys):
    engine = _Engine([{"status": "weird", "name": "x", "message": "?"}])
    _use_engine(monkeypatch, cli_main, engine)
    _no_local_doctor(monkeypatch)

    assert main(["doctor"]) == 0

    assert capsys.readouterr().out == "[FAIL] x: ?\n"


def test_doctor_with_test_acp_reports_the_probe(monkeypatch, capsys):
    engine = _Engine([], probe={"ok": True, "message": "session opened"})
    _use_engine(monkeypatch, cli_main, engine)
    _no_local_doctor(monkeypatch)

    assert main(["doctor", "--test-acp"]) == 0

    assert capsys.readouterr().out == "[ok] ACP: session opened\n"
    assert engine.paths[-1] == "/api/doctor/acp-probe"


def test_doctor_with_a_failed_acp_probe_exits_1(monkeypatch, capsys):
    engine = _Engine(
        [{"status": "ok", "name": "claude", "message": "found"}],
        probe={"ok": False, "message": "handshake timed out"},
    )
    _use_engine(monkeypatch, cli_main, engine)
    _no_local_doctor(monkeypatch)

    assert main(["doctor", "--test-acp"]) == 1

    assert capsys.readouterr().out.splitlines()[-1] == "[FAIL] ACP: handshake timed out"


def test_config_show_prints_the_effective_config(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["config", "--workflow", "review"]) == 0

    assert capsys.readouterr().out.splitlines()[0] == "Effective config · workflow review"


def test_the_daemon_subcommand_dispatches_its_action(monkeypatch):
    actions: list[str] = []
    monkeypatch.setattr(cli_main, "run_daemon_command", lambda action: actions.append(action) or 7)

    assert main(["daemon", "stop"]) == 7
    assert actions == ["stop"]


def test_version_prints_the_package_version(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["--version"])

    assert exited.value.code == 0
    assert capsys.readouterr().out == f"pulse {__version__}\n"


def test_an_unknown_subcommand_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exited:
        main(["frobnicate"])

    assert exited.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_a_non_interactive_terminal_gets_a_plain_welcome_instead_of_the_tui(monkeypatch, capsys):
    """Piping `pulse` must not start Textual on a stream that is not a terminal."""
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", _must_not_open)

    assert main([]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert PULSE_LINE in lines
    assert PULSE_WAVE in lines
    assert f"Pulse v{__version__}" in lines
    assert lines[-1] == "Run `pulse` in an interactive terminal to open the TUI."


def _must_not_open(*_args: Any, **_kwargs: Any) -> int:
    raise AssertionError("the TUI must not open")


class _Tty:
    def isatty(self) -> bool:
        return True


def test_an_interactive_terminal_opens_the_tui_after_starting_the_engine(monkeypatch, capsys):
    engine = _Engine([])
    monkeypatch.setattr(cli_main.sys, "stdin", _Tty())
    monkeypatch.setattr(cli_main.sys, "stdout", _Tty())
    monkeypatch.setattr(cli_main, "global_config_exists", lambda: True)
    _use_engine(monkeypatch, cli_main, engine)
    monkeypatch.setattr("pulse.tui.app.run_onboarding_app", _must_not_open)
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", lambda: 5)

    assert main([]) == 5

    assert engine.paths[0] == "/api/status"


def test_a_first_run_goes_through_onboarding_before_the_tui(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(cli_main, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_main, "global_config_exists", lambda: False)
    _use_engine(monkeypatch, cli_main, _Engine([]))
    monkeypatch.setattr(
        "pulse.tui.app.run_onboarding_app", lambda: opened.append("onboarding") or 0
    )
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", lambda: opened.append("tui") or 0)

    assert main([]) == 0

    assert opened == ["onboarding", "tui"]


def test_a_first_run_starts_the_engine_before_onboarding_asks_it_anything(monkeypatch):
    """Onboarding reads the daemon from the event loop, where screens never start one."""
    engine = _Engine([])
    asked_at: list[list[str]] = []
    monkeypatch.setattr(cli_main, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_main, "global_config_exists", lambda: False)
    _use_engine(monkeypatch, cli_main, engine)
    monkeypatch.setattr(
        "pulse.tui.app.run_onboarding_app", lambda: asked_at.append(list(engine.paths)) or 0
    )
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", lambda: 0)

    assert main([]) == 0

    assert asked_at == [["/api/status", "/api/status"]]


def test_init_starts_the_engine_before_onboarding(monkeypatch):
    engine = _Engine([])
    asked_at: list[list[str]] = []
    _use_engine(monkeypatch, cli_main, engine)

    def onboarding(*, force: bool = False) -> int:
        asked_at.append(list(engine.paths))
        return 0

    monkeypatch.setattr("pulse.tui.app.run_onboarding_app", onboarding)

    assert main(["init"]) == 0

    assert asked_at == [["/api/status", "/api/status"]]


def test_an_abandoned_onboarding_exits_with_its_code_without_the_tui(monkeypatch):
    """Without a config the TUI cannot run; quitting onboarding must stop there."""
    monkeypatch.setattr(cli_main, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_main, "global_config_exists", lambda: False)
    _use_engine(monkeypatch, cli_main, _Engine([]))
    monkeypatch.setattr("pulse.tui.app.run_onboarding_app", lambda: 3)
    monkeypatch.setattr("pulse.tui.app.run_pulse_app", _must_not_open)

    assert main([]) == 3


@pytest.fixture
def daemon_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    meta = tmp_path / "daemon.json"
    monkeypatch.setattr(cli_daemon, "read_daemon_meta", lambda: _read(meta))
    return meta


def _read(meta: Path) -> dict[str, Any] | None:
    return json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else None


RUN_A = {"id": "a", "workflow_label": "Ship", "current_step_label": "Build", "active": True}
RUN_B = {"id": "b", "workflow_id": "fix", "active": True, "awaiting_prompt": True}


def test_status_of_a_live_daemon_without_endpoints_shows_defaults_and_runs(
    monkeypatch, daemon_meta: Path, capsys
):
    """Meta from an older daemon may lack fields; status still reports what it can."""
    daemon_meta.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_daemon, "is_daemon_alive", lambda: True)
    monkeypatch.setattr(cli_daemon, "active_runs", lambda: [RUN_A, RUN_B])

    assert run_daemon_command("status") == 0

    assert capsys.readouterr().out == (
        "pulse-engine: running\n"
        "  http: 127.0.0.1:8787\n"
        f"  run: Ship · Build · {status_labels.RUNNING}\n"
        f"  run: fix · {status_labels.AWAITING_YOU}\n"
    )


def test_start_when_already_running_does_not_spawn(monkeypatch, capsys):
    monkeypatch.setattr(cli_daemon, "is_daemon_alive", lambda: True)
    monkeypatch.setattr(cli_daemon, "EngineClient", _must_not_open)

    assert run_daemon_command("start") == 0

    assert capsys.readouterr().out == "pulse-engine is already running\n"


def test_start_brings_the_engine_up(monkeypatch, capsys):
    engine = _Engine([])
    monkeypatch.setattr(cli_daemon, "is_daemon_alive", lambda: False)
    _use_engine(monkeypatch, cli_daemon, engine)

    assert run_daemon_command("start") == 0

    assert capsys.readouterr().out == "pulse-engine started\n"
    assert engine.paths[0] == "/api/status"


def test_stop_without_live_runs_stops_quietly(monkeypatch, capsys):
    monkeypatch.setattr(cli_daemon, "active_runs", lambda: [])
    monkeypatch.setattr(cli_daemon, "stop_daemon", lambda: True)

    assert run_daemon_command("stop") == 0

    assert capsys.readouterr().out == "pulse-engine stopped\n"


@pytest.mark.parametrize(
    ("runs", "header"),
    [
        ([RUN_A], "[pulse] Warning: 1 run running — stopping the engine ends:"),
        ([RUN_A, RUN_B], "[pulse] Warning: 2 runs running — stopping the engine ends:"),
    ],
)
def test_stop_warns_about_each_run_it_will_end(
    monkeypatch, capsys, runs: list[dict[str, Any]], header: str
):
    """Stopping the engine kills live runs; the user must see which ones."""
    monkeypatch.setattr(cli_daemon, "active_runs", lambda: runs)
    monkeypatch.setattr(cli_daemon, "stop_daemon", lambda: True)

    assert run_daemon_command("stop") == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == header
    assert len([line for line in lines if line.startswith("  - ")]) == len(runs)
    assert lines[-1] == "pulse-engine stopped"


def test_stop_reports_a_daemon_that_survives_sigterm(monkeypatch, capsys):
    monkeypatch.setattr(cli_daemon, "active_runs", lambda: [])
    monkeypatch.setattr(cli_daemon, "stop_daemon", lambda: False)

    assert run_daemon_command("stop") == 1

    assert capsys.readouterr().out == (
        "[pulse] pulse-engine did not exit after SIGTERM; it is still running\n"
    )
