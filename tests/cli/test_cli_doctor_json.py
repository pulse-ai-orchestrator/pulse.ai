"""`pulse doctor --json`: one JSON object on stdout and the same exit code as the text report.

Scripts and CI parse stdout as a whole, so nothing but the object may reach it,
and the object carries only the check fields: never credentials or environment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import pulse.cli.main as cli_main
from pulse.acp.client import AcpProbeResult
from pulse.cli.main import main
from pulse.client.engine_client import EngineClient
from pulse.client.protocol import ENGINE_PROTOCOL
from pulse.doctor import check_auth, report
from pulse.doctor.checks import CheckResult

LEAK_CANARY = "canary-value-that-must-never-be-printed"


def _engine(
    monkeypatch: pytest.MonkeyPatch,
    checks: list[dict[str, Any]],
    probe: dict[str, Any] | None = None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"ok": True, "protocol": ENGINE_PROTOCOL})
        if request.url.path == "/api/doctor":
            return httpx.Response(200, json={"checks": checks})
        if request.url.path == "/api/doctor/acp-probe":
            return httpx.Response(200, json=probe)
        return httpx.Response(404, json={"detail": "unknown"})

    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: EngineClient(transport=httpx.MockTransport(handler))
    )


@pytest.fixture
def local_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[CheckResult]:
    monkeypatch.chdir(tmp_path)
    found = [CheckResult(name="Runtime", status="ok", message="agent found", detail="v1")]
    monkeypatch.setattr(report, "run_doctor_checks", lambda _runtime: list(found))
    return found


def test_the_engine_report_is_one_json_object_with_only_the_check_fields(monkeypatch, capsys):
    _engine(
        monkeypatch,
        [
            {"name": "claude", "status": "ok", "message": "found", "detail": "npx"},
            {"name": "git", "status": "warn", "message": "missing", "env": {"HOME": "/x"}},
        ],
    )

    assert main(["doctor", "--json"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "checks": [
            {"name": "claude", "status": "ok", "message": "found", "detail": "npx"},
            {"name": "git", "status": "warn", "message": "missing", "detail": None},
        ],
    }


def test_a_failed_engine_check_is_not_ok_and_exits_1(monkeypatch, capsys):
    _engine(monkeypatch, [{"name": "claude", "status": "fail", "message": "not installed"}])

    assert main(["doctor", "--json"]) == 1

    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_a_failed_engine_acp_probe_becomes_a_failed_check_without_its_raw_answer(
    monkeypatch, capsys
):
    _engine(
        monkeypatch,
        [{"name": "claude", "status": "ok", "message": "found"}],
        probe={
            "ok": False,
            "message": "ACP failed",
            "error": "auth required",
            "response_text": LEAK_CANARY,
            "available_models": ["sonnet"],
        },
    )

    assert main(["doctor", "--json", "--test-acp"]) == 1

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["checks"][-1] == {
        "name": "ACP",
        "status": "fail",
        "message": "ACP failed",
        "detail": "auth required",
    }
    assert LEAK_CANARY not in out


def test_a_passing_engine_acp_probe_keeps_the_report_ok(monkeypatch, capsys):
    _engine(monkeypatch, [], probe={"ok": True, "message": "session opened", "error": None})

    assert main(["doctor", "--json", "--test-acp"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "checks": [{"name": "ACP", "status": "ok", "message": "session opened", "detail": None}],
    }


def test_a_dead_engine_falls_back_to_the_local_json_and_warns_on_stderr(
    monkeypatch, capsys, local_checks
):
    """The fallback warning is for people; a script must still parse stdout."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    monkeypatch.setattr(
        cli_main, "EngineClient", lambda: EngineClient(transport=httpx.MockTransport(handler))
    )

    assert main(["doctor", "--json"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "ok": True,
        "checks": [
            {"name": "Runtime", "status": "ok", "message": "agent found", "detail": "v1"},
        ],
    }
    assert "using the local doctor" in captured.err


def test_the_local_json_report_fails_with_exit_1(capsys, local_checks):
    local_checks[0] = CheckResult(name="Runtime", status="fail", message="agent missing")

    assert main(["doctor", "--local", "--json"]) == 1

    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "checks": [
            {"name": "Runtime", "status": "fail", "message": "agent missing", "detail": None},
        ],
    }


def test_the_local_acp_probe_keeps_stdout_pure_json(monkeypatch, capsys, local_checks):
    """The probe announces itself while it runs; that line must not break the JSON."""

    def probe(*, command: list[str], cwd: str) -> AcpProbeResult:
        return AcpProbeResult(success=True, message="ACP ok", response_text="pong")

    monkeypatch.setattr(report, "probe_acp_connection", probe)

    assert main(["doctor", "--local", "--json", "--test-acp"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["checks"][-1] == {
        "name": "ACP",
        "status": "ok",
        "message": "ACP ok",
        "detail": "pong",
    }
    assert "Testing the ACP connection" in captured.err


def test_an_api_key_in_the_environment_never_reaches_the_local_json(
    monkeypatch, capsys, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", LEAK_CANARY)
    monkeypatch.setattr(report, "run_doctor_checks", lambda _runtime: [check_auth("claude")])

    assert main(["doctor", "--local", "--json"]) == 0

    captured = capsys.readouterr()
    message = json.loads(captured.out)["checks"][0]["message"]
    assert message == "ANTHROPIC_API_KEY set in the environment"
    assert LEAK_CANARY not in captured.out + captured.err
