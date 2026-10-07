"""The engine: which agent runs now, and what happens when a step does not close."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.conftest import make_workflow

from pulse.domain import run as run_model
from pulse.orchestrator import engine
from pulse.orchestrator.engine import run_workflow
from pulse.runcontrol import RUN_STOPPED, RunControl
from pulse.store import runs as run_store
from pulse.tui.hydrate import _step_seconds


class _Stream:
    cockpit = True

    def __init__(self) -> None:
        self.phases: list[str] = []
        self.messages: list[str] = []
        self.statuses: list[dict] = []

    def begin_phase(self, title: str) -> None:
        self.phases.append(title)

    def info(self, title: str) -> None:
        self.messages.append(title)

    def error(self, title: str, reason: str = "") -> None:
        self.messages.append(title)

    def apply_phase_statuses(self, **kwargs) -> None:
        self.statuses.append(kwargs)


class _Prompt:
    """Answers the retry menu with the same choice every time."""

    def __init__(self, choice: str = "stop") -> None:
        self.choice = choice
        self.asked: list[str] = []
        self.prompts: list[str] = []

    def select_choice(self, prompt, choices, *, title=""):
        self.asked.append(title)
        self.prompts.append(prompt)
        return self.choice

    def ask_text(self, prompt, *, title=""):
        return ""


class _Runner:
    """A fake `AcpSessionRunner`: only what the engine calls."""

    def __init__(self, results: list[dict], *, control: RunControl | None = None) -> None:
        self._results = list(results)
        self.prompts: list[str] = []
        self.agents: list[str] = []
        self.control = control or RunControl()
        self.last_session_id = "sess-1"
        self._stream = _Stream()
        self._prompt_handler = _Prompt()
        self.closed = False
        self.revivals = 0

    def bind_run(self, run_id: str, waits: object = None) -> None:
        self.run_id = run_id

    def start(self) -> None:
        pass

    def initialize(self) -> None:
        pass

    def authenticate(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def use_agent(self, agent_id: str, policy: str) -> None:
        self.agents.append(agent_id)

    def run_isolated_phase(self, *, initial_prompt: str, **_kwargs) -> dict:
        self.prompts.append(initial_prompt)
        return self._next({"approved": True})

    def run_isolated_prompt(self, *, prompt_text: str, build_continuation=None, **_kwargs) -> dict:
        """Mimic the real runner's turn loop, including the continuation.

        Without this, the agent's chance to unblock itself would not be exercised
        by any test: the engine only offers it through this callback.
        """
        self.prompts.append(prompt_text)
        result = self._next({"stopReason": "end_turn"})
        parts = [str(result.get("phaseSummary", ""))]
        turn = 0
        while build_continuation is not None:
            follow_up = str(build_continuation(result=result, turn=turn) or "").strip()
            if not follow_up:
                break
            self.prompts.append(follow_up)
            result = self._next({"stopReason": "end_turn"})
            parts.append(str(result.get("phaseSummary", "")))
            result["phaseSummary"] = "\n\n".join(part for part in parts if part)
            turn += 1
        return result

    def _next(self, default: dict) -> dict:
        """Next queued result, or the exception the session would raise."""
        result = self._results.pop(0) if self._results else default
        if isinstance(result, BaseException):
            raise result
        return result

    def ensure_process(self) -> bool:
        self.revivals += 1
        return True


@pytest.fixture
def wired(monkeypatch, tmp_path: Path):
    """Engine with resolved config and no terminal: just the step loop."""

    class Resolved:
        workspace_dir = tmp_path
        permission_policy = "ask"
        acp_command = ["agent", "acp"]
        model = "auto"
        agent_name = "cursor"

    monkeypatch.setattr(engine, "is_interactive", lambda: False)
    monkeypatch.setattr(engine, "check_runtime_ready", lambda _runtime: None)
    monkeypatch.setattr(engine, "resolve_config", lambda **_kwargs: Resolved())
    return Resolved


def _install(monkeypatch, runner: _Runner) -> None:
    monkeypatch.setattr(engine, "AcpSessionRunner", lambda *_a, **_k: runner)


def _approved(summary: str = "") -> dict:
    return {"approved": True, "outcome": "approve", "phaseSummary": summary}


def _delivered(summary: str = "feito") -> dict:
    """Turn of a non-approval step that declared delivery."""
    return {
        "stopReason": "end_turn",
        "phaseSummary": f"{summary}\n\n```pulse:outcome\nstatus: done\n```",
    }


def _blocked(reason: str, *, needs: str = "") -> dict:
    """Turn in which the agent declares it could not deliver."""
    lines = ["status: blocked", f"reason: {reason}"]
    if needs:
        lines.append(f"needs: {needs}")
    body = "\n".join(lines)
    return {
        "stopReason": "end_turn",
        "phaseSummary": f"tentei e não deu\n\n```pulse:outcome\n{body}\n```",
    }


def test_steps_run_in_order_and_each_one_is_recorded(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois"), ("three", "Três")])
    runner = _Runner([_approved(), _approved(), _approved()])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="fazer algo",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner.agents == ["tester", "tester", "tester"]
    record = run_store.list_runs(tmp_path)[0]
    assert [(step.step_id, step.status) for step in record.steps] == [
        ("one", "done"),
        ("two", "done"),
        ("three", "done"),
    ]
    assert record.status == "completed"


def test_the_prompt_template_is_rendered_with_run_values(wired, monkeypatch, tmp_path: Path):
    make_workflow(
        "demo",
        steps=[("one", "Um")],
        prompt_template="tarefa: {{user_prompt}} em {{workspace}} (step {{step_id}})",
    )
    runner = _Runner([_approved()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="corrigir login",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert runner.prompts == [f"tarefa: corrigir login em {tmp_path} (step one)"]


def test_a_step_sees_what_the_previous_one_produced(wired, monkeypatch, tmp_path: Path):
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois")],
        prompt_template="{{#if previous_summary}}antes: {{previous_summary}}{{/if}}siga",
    )
    runner = _Runner([_approved("escrevi o plano"), _approved()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert runner.prompts[0] == "siga"
    assert runner.prompts[1] == "antes: escrevi o planosiga"


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ({"approved": True, "outcome": "approve", "phaseSummary": "o review"}, "done"),
        ({"approved": False, "outcome": "skip", "phaseSummary": "o review"}, "skipped"),
    ],
)
def test_a_step_sees_how_the_previous_one_closed(
    wired, monkeypatch, tmp_path: Path, outcome: dict, expected: str
):
    """Skipped and done must not reach the next step indistinguishable.

    Without the status, the next step would get the same summary in both cases
    and build on top of a delivery the user just dismissed.
    """
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois")],
        prompt_template="anterior: {{previous_status}}",
    )
    runner = _Runner([outcome, _approved()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert runner.prompts[0] == "anterior: "
    assert runner.prompts[1] == f"anterior: {expected}"


def test_a_step_that_is_not_approved_stops_the_run(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner([{"approved": False, "outcome": "continue"}])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 1
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("one").status == "failed"
    assert record.step("two").status == "pending", "the next step never ran"


def test_retry_runs_the_same_step_again(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um")])
    runner = _Runner([{"approved": False, "outcome": "continue"}, _approved()])
    runner._prompt_handler.choice = "retry"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert len(runner.prompts) == 2
    assert run_store.list_runs(tmp_path)[0].step("one").status == "done"


def test_a_timeout_offers_retry_instead_of_killing_the_run(
    wired, monkeypatch, tmp_path: Path
):
    """A timed-out session is a failed attempt, not the end of the run."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner(
        [TimeoutError("o agente ficou 600s sem dar sinal em `session/prompt`"), _approved(), _approved()]
    )
    runner._prompt_handler.choice = "retry"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner._prompt_handler.asked == ["Step Um falhou"]
    assert runner.revivals == 1
    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["done", "done"]


def test_a_dead_session_that_the_user_gives_up_on_fails_the_step(
    wired, monkeypatch, tmp_path: Path
):
    """`Parar` closes the run the normal way: failed step, no exception."""
    make_workflow("demo", steps=[("one", "Um")])
    runner = _Runner([RuntimeError("o processo do agente encerrou")])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 1
    assert runner.revivals == 0
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("one").status == "failed"
    assert record.status == "failed"


def test_skip_settles_the_step_without_failing_the_run(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner([{"approved": False, "outcome": "skip"}, _approved()])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("one").status == "skipped"
    assert record.step("two").status == "done"


def test_a_step_without_approval_closes_when_the_agent_declares_the_outcome(
    wired, monkeypatch, tmp_path: Path
):
    make_workflow("demo", steps=[("one", "Um")], requires_approval=False)
    runner = _Runner([_delivered("pronto")])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert run_store.list_runs(tmp_path)[0].step("one").status == "done"


def test_ending_the_turn_is_no_longer_enough_for_a_step_to_count_as_done(
    wired, monkeypatch, tmp_path: Path
):
    """The old rule (`end_turn` means success) was the whole hole.

    An agent answering "I can't" ended the turn like any other, the step
    became `done` and the next one ran on top of nothing.
    """
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = _Runner(
        [
            {"stopReason": "end_turn", "phaseSummary": "não consigo: falta a credencial"},
            {"stopReason": "end_turn", "phaseSummary": "continuo sem conseguir"},
        ]
    )
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == engine.RUN_BLOCKED
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("one").status == "blocked"
    assert record.step("two").status == "pending", "the cascade stops at the blocked step"
    assert record.status == "blocked", "a block is not a failure"


def test_a_declared_block_stops_the_run_instead_of_cascading(
    wired, monkeypatch, tmp_path: Path
):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = _Runner([_blocked("falta a credencial do banco", needs="user")])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == engine.RUN_BLOCKED
    assert runner._prompt_handler.asked == ["Um está bloqueado"]
    assert runner._prompt_handler.prompts == ["falta a credencial do banco"], (
        "the reason the agent declared is what the user reads"
    )
    assert len(runner.prompts) == 1, "`needs: user` does not spend a self-resolution turn"
    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["blocked", "pending"]


def test_a_blocked_step_gets_one_shot_at_unblocking_itself(
    wired, monkeypatch, tmp_path: Path
):
    """What the agent can fix itself does not wake anyone up.

    Without `needs`, the engine hands the block back to the agent once, in the
    same session so it does not start from scratch, before escalating.
    """
    make_workflow("demo", steps=[("one", "Um")], requires_approval=False)
    runner = _Runner(
        [_blocked("o arquivo de config não existe"), _delivered("criei o config e segui")]
    )
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner._prompt_handler.asked == [], "nobody was interrupted"
    assert len(runner.prompts) == 2
    assert "Bloqueio declarado" in runner.prompts[1]
    assert "o arquivo de config não existe" in runner.prompts[1]
    assert run_store.list_runs(tmp_path)[0].step("one").status == "done"


def test_the_agent_gets_only_one_shot_before_the_person_is_called(
    wired, monkeypatch, tmp_path: Path
):
    make_workflow("demo", steps=[("one", "Um")], requires_approval=False)
    runner = _Runner([_blocked("falta X"), _blocked("continua faltando X")])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == engine.RUN_BLOCKED
    assert len(runner.prompts) == 2, "two attempts, not a ping-pong"
    assert runner._prompt_handler.prompts == ["continua faltando X"]


def test_a_forgotten_outcome_block_is_asked_for_before_it_becomes_a_block(
    wired, monkeypatch, tmp_path: Path
):
    """Forgetting the block is the most common case, and the cheapest to fix.

    Otherwise every distracted agent would become an on-screen question, the
    exact friction that would make the protocol not worth it.
    """
    make_workflow("demo", steps=[("one", "Um")], requires_approval=False)
    runner = _Runner(
        [{"stopReason": "end_turn", "phaseSummary": "terminei tudo"}, _delivered()]
    )
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner._prompt_handler.asked == []
    assert "Desfecho do step" in runner.prompts[1]
    assert run_store.list_runs(tmp_path)[0].step("one").status == "done"


def test_skipping_a_blocked_step_records_it_as_skipped_not_done(
    wired, monkeypatch, tmp_path: Path
):
    """The explicit skip is the difference: it used to happen disguised as `done`."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = _Runner([_blocked("falta acesso", needs="user"), _delivered()])
    runner._prompt_handler.choice = "skip"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["skipped", "done"]


def test_a_step_that_did_not_deliver_does_not_feed_the_next_one(
    wired, monkeypatch, tmp_path: Path
):
    """The poisoned summary: the next step must not receive "I couldn't".

    It gets the summary of the last step that actually delivered (here, the
    first), not the one that got stuck and was skipped.
    """
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois"), ("three", "Três")],
        requires_approval=False,
        prompt_template="{{#if previous_summary}}antes: {{previous_summary}}{{/if}}siga",
    )
    runner = _Runner(
        [
            _delivered("escrevi o plano"),
            _blocked("não consegui migrar o schema", needs="user"),
            _delivered(),
        ]
    )
    runner._prompt_handler.choice = "skip"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert "não consegui migrar o schema" not in runner.prompts[2]
    assert runner.prompts[2].startswith("antes: escrevi o plano")


def test_requires_outcome_off_brings_the_old_behaviour_back(
    wired, monkeypatch, tmp_path: Path
):
    """The escape hatch, for workflows that have not adopted the protocol yet."""
    make_workflow(
        "demo", steps=[("one", "Um")], requires_approval=False, requires_outcome=False
    )
    runner = _Runner([{"stopReason": "end_turn", "phaseSummary": "pronto"}])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner.prompts == ["x"], "without the protocol, the prompt stays as the author wrote it"
    assert run_store.list_runs(tmp_path)[0].step("one").status == "done"


def test_an_approval_step_keeps_the_person_as_the_only_gate(
    wired, monkeypatch, tmp_path: Path
):
    """A step has a single gate: where there is approval, the user attests."""
    make_workflow("demo", steps=[("one", "Um")], requires_approval=True)
    runner = _Runner([_approved("entreguei")])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner.prompts == ["x"], "no outcome request where approval already exists"


def test_with_nobody_to_ask_a_blocked_run_stops_instead_of_going_on(
    wired, monkeypatch, tmp_path: Path
):
    """CLI, closed cockpit, daemon run: the safe default is to stop."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = _Runner([_blocked("falta acesso", needs="user")])
    runner._prompt_handler = object()
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == engine.RUN_BLOCKED
    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["blocked", "pending"]


def test_resuming_picks_up_at_the_first_unfinished_step(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    first = _Runner([_approved(), {"approved": False, "outcome": "continue"}])
    first._prompt_handler.choice = "stop"
    _install(monkeypatch, first)
    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=first._stream,
        prompt_handler=first._prompt_handler,
        render_header=False,
    )
    run_id = run_store.list_runs(tmp_path)[0].id

    second = _Runner([_approved()])
    _install(monkeypatch, second)
    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=second._stream,
        prompt_handler=second._prompt_handler,
        render_header=False,
        resume_run_id=run_id,
    )

    assert code == 0
    assert len(second.prompts) == 1, "the already-finished step does not run again"
    assert len(run_store.list_runs(tmp_path)) == 1, "resuming does not create another run"


def test_resume_is_the_only_way_back_into_a_run(wired, monkeypatch, tmp_path: Path):
    """There is no restart from scratch: `run_workflow` does not even take the parameter.

    A run whose steps all closed has nothing to run when reopened; whoever wants
    the whole pipeline again starts a new run.
    """
    import inspect

    assert "restart" not in inspect.signature(run_workflow).parameters

    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    first = _Runner([_approved(), _approved()])
    _install(monkeypatch, first)
    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=first._stream,
        prompt_handler=first._prompt_handler,
        render_header=False,
    )
    run_id = run_store.list_runs(tmp_path)[0].id

    second = _Runner([_approved(), _approved()])
    _install(monkeypatch, second)
    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=second._stream,
        prompt_handler=second._prompt_handler,
        render_header=False,
        resume_run_id=run_id,
    )

    assert code == 0
    assert second.prompts == [], "everything was already done: nothing runs again"


def test_stopping_between_steps_ends_the_run_as_stopped(wired, monkeypatch, tmp_path: Path):
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    control = RunControl()
    runner = _Runner([_approved()], control=control)
    _install(monkeypatch, runner)

    original = runner.run_isolated_phase

    def stop_after_first(**kwargs):
        result = original(**kwargs)
        control.stop()
        return result

    runner.run_isolated_phase = stop_after_first

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
        control=control,
    )

    assert code == RUN_STOPPED
    record = run_store.list_runs(tmp_path)[0]
    assert record.status == "stopped"
    assert record.step("one").status == "done", "what already closed stays closed"
    assert record.step("two").status == "pending"


def test_a_broken_template_fails_the_step_instead_of_prompting_a_hole(
    wired, monkeypatch, tmp_path: Path
):
    """A placeholder without a value is an error: a truncated instruction would go out silently."""
    make_workflow("demo", steps=[("one", "Um")], prompt_template="{{nao_existe}}")
    runner = _Runner([])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 1
    assert runner.prompts == []


def test_an_unexpected_error_also_offers_retry(wired, monkeypatch, tmp_path: Path):
    """Not only timeouts and dead processes: any crash inside the step asks.

    The caught types used to be (Timeout, Runtime, OSError); a `ValueError` from
    an already-closed stdin killed the run with no menu and left the step
    recorded as running.
    """
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner([ValueError("I/O operation on closed file"), _approved(), _approved()])
    runner._prompt_handler.choice = "retry"
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert runner._prompt_handler.asked == ["Step Um falhou"]
    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["done", "done"]


def test_a_step_that_failed_is_never_left_as_running(wired, monkeypatch, tmp_path: Path):
    """The database must not keep "running" after the run ended.

    That state made the run come back from history offering neither resume nor
    restart: no step was pending, just one stuck midway.
    """
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner([RuntimeError("o processo do agente encerrou")])
    runner._prompt_handler.choice = "stop"
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert [step.status for step in record.steps] == ["failed", "pending"]
    assert record.step("one").ended_at, "failure also stops the step clock"


def test_stopping_inside_a_step_leaves_it_pending_and_resume_only_redoes_it(
    wired, monkeypatch, tmp_path: Path
):
    """Stopping midway through step 2: it goes back to pending and only it is redone.

    This is the whole stop/resume contract: the interrupted step neither finished
    nor failed, and step 1, which closed, must not run again on resume.
    """
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois"), ("three", "Três")])
    control = RunControl()
    runner = _Runner([_approved(), {"stopReason": "cancelled"}], control=control)
    _install(monkeypatch, runner)

    original = runner.run_isolated_phase

    def stop_during_second(**kwargs):
        if len(runner.prompts) == 1:
            control.stop()
        return original(**kwargs)

    runner.run_isolated_phase = stop_during_second

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
        control=control,
    )

    assert code == RUN_STOPPED
    assert runner._prompt_handler.asked == [], "stopping does not go through the retry menu"
    record = run_store.list_runs(tmp_path)[0]
    run_id = record.id
    assert record.status == "stopped"
    assert [step.status for step in record.steps] == ["done", "pending", "pending"]

    second = _Runner([_approved(), _approved()])
    _install(monkeypatch, second)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=second._stream,
        prompt_handler=second._prompt_handler,
        render_header=False,
        resume_run_id=run_id,
    )

    assert code == 0
    assert len(second.prompts) == 2, "only the two pending steps run; the closed one does not come back"
    record = run_store.load_run(run_id)
    assert [step.status for step in record.steps] == ["done", "done", "done"]


def _repeating(summary: str = "corrigi") -> dict:
    """Turn of a step that delivered and asks for another loop round."""
    return {
        "stopReason": "end_turn",
        "phaseSummary": f"{summary}\n\n```pulse:outcome\nstatus: done\nnext: repeat\n```",
    }


def test_a_step_can_send_the_run_back_to_repeat_the_stretch(wired, monkeypatch, tmp_path):
    """The loop: review, fix, review again, until nobody asks for more."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner(
        [_delivered(), _repeating(), _delivered(), _repeating(), _delivered(), _delivered()]
    )
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["review", "fix"]
    assert all(step.status == "done" for step in record.steps)
    assert record.step("review").rounds == 3
    assert record.step("fix").rounds == 1


def test_without_a_request_the_loop_runs_only_once(wired, monkeypatch, tmp_path):
    """`repeat_from` is a permission, not an obligation: no request, no repeat."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_delivered(), _delivered()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["review", "fix"]
    assert record.step("review").rounds == 1


def test_the_round_cap_ends_the_loop(wired, monkeypatch, tmp_path):
    """Without a cap, an agent that always asks for one more leaves the run endless."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 2),
    )
    runner = _Runner([_delivered(), _repeating(), _delivered(), _repeating()])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["review", "fix"]
    assert record.step("review").rounds == 2, "stopped at the second, as the cap dictates"
    assert record.status == "completed"


def test_the_loop_ends_on_its_opener_never_on_its_closer(wired, monkeypatch, tmp_path):
    """Review -> fix -> review: at the cap, fix does not run after the last review.

    The closer asks for another round because it changed something nobody checked.
    Letting it run in the last round would end the run on an unchecked fix.
    """
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner(
        [
            _delivered("r1"),
            _repeating("f1"),
            _delivered("r2"),
            _repeating("f2"),
            _delivered("r3"),
            _repeating("f3 — não deveria rodar"),
        ]
    )
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert len(runner.prompts) == 5
    assert len(runner._results) == 1
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("review").rounds == 3
    assert all(step.status == "done" for step in record.steps)
    assert any("a última" in message for message in runner._stream.messages)


def test_the_cap_counts_recorded_rounds_on_resume(wired, monkeypatch, tmp_path):
    """Resuming mid-loop does not give back rounds already spent."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    control = RunControl()
    first = _Runner([_delivered(), _repeating(), _delivered()], control=control)
    original = engine._run_step

    def stop_before_second_fix(**kwargs):
        if kwargs["step"].step_id == "fix" and kwargs["run"].step("review").rounds == 2:
            control.stop()
            return RUN_STOPPED, False
        return original(**kwargs)

    monkeypatch.setattr(engine, "_run_step", stop_before_second_fix)
    _install(monkeypatch, first)
    assert (
        run_workflow(
            workflow_id="demo",
            user_prompt="x",
            stream=first._stream,
            prompt_handler=first._prompt_handler,
            render_header=False,
        )
        == RUN_STOPPED
    )
    run_id = run_store.list_runs(tmp_path)[0].id
    monkeypatch.setattr(engine, "_run_step", original)

    second = _Runner([_repeating(), _delivered(), _repeating("não deveria rodar")])
    _install(monkeypatch, second)
    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=second._stream,
        prompt_handler=second._prompt_handler,
        render_header=False,
        resume_run_id=run_id,
    )

    assert code == 0
    assert len(second.prompts) == 2
    assert len(second._results) == 1
    assert run_store.load_run(run_id).step("review").rounds == 3


def test_round_time_adds_up_instead_of_resetting(wired, monkeypatch, tmp_path):
    """Each round reopens the clock, but time spent by earlier rounds is kept."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_delivered(), _repeating(), _delivered(), _delivered()])
    _install(monkeypatch, runner)

    start = datetime(2026, 10, 6, tzinfo=UTC)
    seconds = iter(range(0, 10_000, 10))
    monkeypatch.setattr(
        run_model,
        "utc_now",
        lambda: (start + timedelta(seconds=next(seconds))).isoformat(),
    )

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    review = record.step("review")
    assert review.rounds == 2
    assert review.carried_seconds > 0
    assert review.started_at and review.ended_at
    assert _step_seconds(review) > review.carried_seconds


def _clean(summary: str = "nada a corrigir", *, approval: bool = False) -> dict:
    """Turn of the loop opener that found nothing to fix: no approval."""
    result = {
        "stopReason": "end_turn",
        "phaseSummary": f"{summary}\n\n```pulse:outcome\nstatus: done\nnext: close\n```",
    }
    if approval:
        result.update(approved=False, outcome="unknown")
    return result


def test_clean_review_ends_the_loop_without_asking_approval(wired, monkeypatch, tmp_path):
    """The loop ends on the reviewer: a review without findings does not call fix."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix"), ("after", "Depois")],
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_clean(approval=True), _approved("depois")])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert len(runner.prompts) == 2, "review and the step after the loop; fix does not run"
    record = run_store.list_runs(tmp_path)[0]
    assert record.status == "completed"
    assert [step.status for step in record.steps] == ["done", "skipped", "done"]
    assert any("laço encerrado" in message for message in runner._stream.messages)


def test_clean_review_in_a_later_round_keeps_the_fix_that_already_ran(
    wired, monkeypatch, tmp_path
):
    """Review -> fix -> clean review: the round-1 fix delivered and stays `done`."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_delivered("r1"), _repeating("f1"), _clean("r2")])
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 0
    assert len(runner.prompts) == 3
    record = run_store.list_runs(tmp_path)[0]
    assert record.step("review").rounds == 2
    assert [step.status for step in record.steps] == ["done", "done"]


def test_only_the_loop_opener_can_waive_approval(wired, monkeypatch, tmp_path):
    """Outside a loop opener, `next: close` does not count as approval."""
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")])
    runner = _Runner([_clean(approval=True)])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert record.step("one").status == "failed"
    assert record.step("two").status == "pending"
    assert any("sem o bloco de aprovação" in prompt for prompt in runner._prompt_handler.prompts)


def test_repeat_request_is_ignored_where_the_workflow_declared_no_loop(
    wired, monkeypatch, tmp_path
):
    """An agent cannot create a loop where the definition did not open one."""
    make_workflow(
        "demo",
        steps=[("one", "Um"), ("two", "Dois")],
        requires_approval=False,
    )
    runner = _Runner([_repeating(), _repeating()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["one", "two"]


def test_steps_after_the_loop_do_not_count_rounds(wired, monkeypatch, tmp_path):
    """The counter belongs to the loop range, not to everything after it."""
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix"), ("ship", "Ship")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_delivered(), _repeating(), _delivered(), _delivered(), _delivered()])
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["review", "fix", "ship"]
    assert record.step("review").rounds == 2
    assert record.step("ship").rounds == 1


def test_loop_rounds_stay_under_the_same_step(wired, monkeypatch, tmp_path):
    """One row per step in the panel, with log and artifacts from every round.

    This is what makes `Review` show `round-001.md` and `round-002.md` together:
    `visible_artifacts()` filters by `phase_id`, so rounds only appear together
    if they share the `step_id`.
    """
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix")],
        requires_approval=False,
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_delivered(), _repeating(), _delivered(), _delivered()])
    _install(monkeypatch, runner)

    rounds: list[int] = []
    original = engine._run_step

    def spy(**kwargs):
        if kwargs["step"].step_id == "review":
            rounds.append(len(rounds) + 1)
            run_store.record_artifact(
                kwargs["run"].id,
                f"reviews/round-00{len(rounds)}.md",
                step_id="review",
            )
        return original(**kwargs)

    monkeypatch.setattr(engine, "_run_step", spy)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    record = run_store.list_runs(tmp_path)[0]
    assert [step.step_id for step in record.steps] == ["review", "fix"]
    assert record.step("review").rounds == 2

    artifacts = run_store.list_artifacts(record.id)
    assert artifacts == [
        {"path": "reviews/round-001.md", "step_id": "review"},
        {"path": "reviews/round-002.md", "step_id": "review"},
    ]


def test_the_wait_in_the_retry_menu_stays_inside_the_step_window(
    wired, monkeypatch, tmp_path: Path
):
    """`_fail` stamps `ended_at` before the menu, and menu wait time is discounted.

    If the user gives up, the end must be restamped after the menu; otherwise the
    discount falls outside the window and the duration disappears from history.
    """
    make_workflow("demo", steps=[("one", "Um")])
    clock = [datetime(2026, 1, 1, tzinfo=UTC)]
    monkeypatch.setattr(run_model, "utc_now", lambda: clock[0].isoformat())

    runner = _Runner([RuntimeError("o processo do agente encerrou")])
    stamped_before_menu: list[str] = []

    def stop_after_ten_minutes(prompt, choices, *, title=""):
        stamped_before_menu.append(run_store.list_runs(tmp_path)[0].step("one").ended_at)
        clock[0] += timedelta(minutes=10)
        return "stop"

    runner._prompt_handler.select_choice = stop_after_ten_minutes
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == 1
    step = run_store.list_runs(tmp_path)[0].step("one")
    assert stamped_before_menu and stamped_before_menu[0]
    assert datetime.fromisoformat(step.ended_at) - datetime.fromisoformat(
        stamped_before_menu[0]
    ) == timedelta(minutes=10)


def test_stopping_while_the_blocked_menu_is_open_stops_the_run(
    wired, monkeypatch, tmp_path: Path
):
    """Stopping with the menu open cancels the question, which returns `None`.

    That is a user stop: the run becomes `stopped` and the step goes back to
    pending for whoever resumes, instead of becoming `blocked`.
    """
    make_workflow("demo", steps=[("one", "Um"), ("two", "Dois")], requires_approval=False)
    runner = _Runner([_blocked("falta a credencial do banco", needs="user")])

    def stop_while_waiting(prompt, choices, *, title=""):
        runner.control.stop()
        return None

    runner._prompt_handler.select_choice = stop_while_waiting
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == RUN_STOPPED
    record = run_store.list_runs(tmp_path)[0]
    assert record.status == "stopped"
    assert record.step("one").status == "pending"


def test_stopping_while_typing_guidance_does_not_reopen_the_menu(
    wired, monkeypatch, tmp_path: Path
):
    make_workflow("demo", steps=[("one", "Um")], requires_approval=False)
    runner = _Runner([RuntimeError("o processo do agente encerrou")])
    runner._prompt_handler.choice = "guidance"

    def stop_while_typing(prompt, *, title=""):
        runner.control.stop()
        return None

    runner._prompt_handler.ask_text = stop_while_typing
    _install(monkeypatch, runner)

    code = run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert code == RUN_STOPPED
    assert len(runner._prompt_handler.asked) == 1, "the menu does not come back after stopping"


def test_the_panel_never_sees_a_closed_loop_the_database_lacks(wired, monkeypatch, tmp_path):
    """Closing the loop is saved before the panel hears of it.

    Otherwise a crash between the two leaves history showing `fix` pending while
    the screen showed it skipped, and a resume would run a step the loop waived.
    """
    make_workflow(
        "demo",
        steps=[("review", "Review"), ("fix", "Fix"), ("after", "Depois")],
        repeat=("fix", "review", 3),
    )
    runner = _Runner([_clean(approval=True), _approved("depois")])
    stored_when_shown: list[str] = []
    show = runner._stream.apply_phase_statuses

    def snapshot(**kwargs) -> None:
        if "fix" in kwargs["skipped_ids"] and not stored_when_shown:
            stored_when_shown.append(run_store.list_runs(tmp_path)[0].step("fix").status)
        show(**kwargs)

    runner._stream.apply_phase_statuses = snapshot
    _install(monkeypatch, runner)

    run_workflow(
        workflow_id="demo",
        user_prompt="x",
        stream=runner._stream,
        prompt_handler=runner._prompt_handler,
        render_header=False,
    )

    assert stored_when_shown == ["skipped"]
