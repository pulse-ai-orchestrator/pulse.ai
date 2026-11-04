from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any

from pulse.acp.client import probe_acp_connection
from pulse.config import load_global_config, load_project_config
from pulse.config.resolved import ResolvedConfig, resolve_config
from pulse.doctor.checks import CheckResult, run_doctor_checks
from pulse.store.paths import GLOBAL_DB_FILE, safe_cwd


def _status_icon(status: str) -> str:
    if status == "ok":
        return "✓"
    if status == "warn":
        return "!"
    return "✗"


def print_doctor_report(
    checks: list[CheckResult],
    *,
    acp_probe_message: str | None = None,
) -> None:
    for check in checks:
        detail = f" — {check.detail}" if check.detail else ""
        print(f"{_status_icon(check.status)} {check.message}{detail}")
    if acp_probe_message:
        print(f"  ACP test: {acp_probe_message}")


def doctor_payload(checks: list[CheckResult]) -> dict[str, Any]:
    return {"ok": not failed(checks), "checks": [asdict(check) for check in checks]}


def print_doctor_json(checks: list[CheckResult]) -> None:
    print(json.dumps(doctor_payload(checks)))


def _global_config_check() -> CheckResult | None:
    config = load_global_config()
    if config is None:
        return None
    detail = f"model={config.model}, permissions={config.permission_policy}"
    if config.agents:
        detail += f", agents={len(config.agents)}"
    if config.workflows:
        detail += f", workflows={len(config.workflows)}"
    return CheckResult(
        name="Global config",
        status="ok",
        message=f"Config in {GLOBAL_DB_FILE}",
        detail=detail,
    )


def _project_config_check() -> CheckResult | None:
    project = load_project_config()
    if project is None:
        return None
    overrides = [
        f"{label}={value}"
        for label, value in (
            ("agent", project.default_agent),
            ("model", project.model),
            ("permissions", project.permission_policy),
            ("workspace", project.workspace),
        )
        if value
    ]
    if project.workflows:
        overrides.append(f"workflows={len(project.workflows)}")
    return CheckResult(
        name="Project config",
        status="ok",
        message=f"Config in {project.source_file}",
        detail=", ".join(overrides) or "no overrides",
    )


def _acp_probe_check(resolved: ResolvedConfig, *, blocked: bool) -> tuple[CheckResult, str | None]:
    """The ACP check and the line summing it up; a failing check makes the probe pointless."""
    active = resolved.runtime.id
    if blocked:
        skipped = CheckResult(
            name="ACP",
            status="warn",
            message="ACP test skipped",
            detail=f"Fix the `{active}` runtime and its authentication first",
        )
        return skipped, None
    print(f"Testing the ACP connection with `{active}`…", file=sys.stderr)
    probe = probe_acp_connection(command=list(resolved.acp_command), cwd=str(safe_cwd()))
    probed = CheckResult(
        name="ACP",
        status="ok" if probe.success else "fail",
        message=probe.message,
        detail=probe.response_text[:120] if probe.response_text else None,
    )
    return probed, probe.message if probe.success else probe.error or probe.message


def failed(checks: list[CheckResult]) -> bool:
    return any(check.status == "fail" for check in checks)


def run_doctor(*, test_acp: bool = False, as_json: bool = False) -> int:
    resolved = resolve_config()
    checks = run_doctor_checks(resolved.runtime.id)
    checks.extend(
        check for check in (_global_config_check(), _project_config_check()) if check is not None
    )
    acp_message: str | None = None
    if test_acp:
        acp_check, acp_message = _acp_probe_check(resolved, blocked=failed(checks))
        checks.append(acp_check)
    if as_json:
        print_doctor_json(checks)
    else:
        print_doctor_report(checks, acp_probe_message=acp_message)
    return 1 if failed(checks) else 0
