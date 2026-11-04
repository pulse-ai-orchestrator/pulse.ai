from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

from pulse import __version__
from pulse.cli.daemon_command import run_daemon_command
from pulse.client.engine_client import EngineClient
from pulse.config import global_config_exists
from pulse.config.commands import run_config_command
from pulse.doctor import CheckResult, failed, print_doctor_json, run_doctor
from pulse.tui.brand import BANNER, PULSE_LINE, PULSE_WAVE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse",
        description="Terminal-first orchestrator of AI agent workflows.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pulse {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init",
        help="Onboarding wizard",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Reconfigure even when a config exists",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check the environment",
    )
    doctor_parser.add_argument(
        "--test-acp",
        action="store_true",
        help="Include the ACP connection test",
    )
    doctor_parser.add_argument(
        "--local",
        action="store_true",
        help="Run the checks locally, without the daemon",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as a single JSON object",
    )

    config_parser = subparsers.add_parser(
        "config",
        help="Show or create the project config",
    )
    config_parser.add_argument(
        "config_action",
        nargs="?",
        default="show",
        choices=["show", "init"],
        help="show: effective config; init: register the project in SQLite",
    )
    config_parser.add_argument(
        "--workflow",
        default=None,
        help="Show the effective config of a workflow",
    )

    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Control the Pulse Engine",
    )
    daemon_parser.add_argument(
        "daemon_action",
        choices=["start", "stop", "status"],
        help="start | stop | status",
    )
    return parser


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _print_plain_welcome() -> None:
    print(BANNER.strip("\n"))
    print(PULSE_LINE)
    print(PULSE_WAVE)
    print(f"Pulse v{__version__}")
    print("Run `pulse` in an interactive terminal to open the TUI.")


def _engine_check(item: dict[str, Any]) -> CheckResult:
    detail = item.get("detail")
    return CheckResult(
        name=str(item.get("name", "")),
        status=str(item.get("status", "")),
        message=str(item.get("message", "")),
        detail=str(detail) if detail else None,
    )


def _probe_check(probe: dict[str, Any]) -> CheckResult:
    error = probe.get("error")
    return CheckResult(
        name="ACP",
        status="ok" if probe.get("ok") else "fail",
        message=str(probe.get("message")),
        detail=str(error) if error else None,
    )


def _print_engine_checks(checks: list[CheckResult]) -> None:
    for check in checks:
        mark = {"ok": "ok", "warn": "warn"}.get(check.status, "FAIL")
        print(f"[{mark}] {check.name}: {check.message}")


def _doctor_via_engine(*, test_acp: bool, as_json: bool) -> int:
    client = EngineClient()
    try:
        client.ensure_daemon()
        checks = [_engine_check(item) for item in client.doctor().get("checks") or []]
        if test_acp:
            checks.append(_probe_check(client.post("/api/doctor/acp-probe", {})))
    except (RuntimeError, OSError, httpx.HTTPError, ValueError) as error:
        print(
            f"[pulse] Engine unavailable ({error}); using the local doctor",
            file=sys.stderr if as_json else sys.stdout,
        )
        return run_doctor(test_acp=test_acp, as_json=as_json)
    finally:
        client.close()
    if as_json:
        print_doctor_json(checks)
    else:
        _print_engine_checks(checks)
    return 1 if failed(checks) else 0


def _start_engine() -> None:
    """Start the daemon before any screen: screens read it on the event loop and never start it.

    A failed start is a warning, not an abort; each screen says the engine is unavailable.
    """
    client = EngineClient()
    try:
        client.ensure_daemon()
    except (RuntimeError, OSError) as error:
        print(f"[pulse] Warning: could not start the engine ({error})")
    finally:
        client.close()


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        from pulse.tui.app import run_onboarding_app

        _start_engine()
        return run_onboarding_app(force=args.force)
    if args.command == "doctor":
        if args.local:
            return run_doctor(test_acp=args.test_acp, as_json=args.json)
        return _doctor_via_engine(test_acp=args.test_acp, as_json=args.json)
    if args.command == "config":
        return run_config_command(
            action=args.config_action,
            workflow=args.workflow,
        )
    if args.command == "daemon":
        return run_daemon_command(args.daemon_action)

    if not _is_interactive():
        _print_plain_welcome()
        return 0

    _start_engine()
    if not global_config_exists():
        from pulse.tui.app import run_onboarding_app

        code = run_onboarding_app()
        if code != 0:
            return code

    from pulse.tui.app import run_pulse_app

    return run_pulse_app()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return _dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
