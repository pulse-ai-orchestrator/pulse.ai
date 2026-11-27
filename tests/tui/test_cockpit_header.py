"""The run's status, total time and progress, as the cockpit header shows them."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from pulse.domain.control import RUN_BLOCKED, RUN_STOPPED
from pulse.domain.run import RunStatus
from pulse.history.events import PhaseItem
from pulse.history.status_labels import STATUS_COLORS, STATUS_TINTS, status_color
from pulse.tui.palette import BORDER
from pulse.tui.state import CockpitState, PhaseStatus
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.app_header import AppHeader, format_clock, progress_meter

STEPS = [("one", "Um"), ("two", "Dois"), ("three", "Três")]


def _state(*statuses: PhaseStatus) -> CockpitState:
    state = CockpitState()
    state.configure_workflow("demo", label="Demo", steps=STEPS[: len(statuses)])
    for phase, status in zip(state.phases, statuses, strict=True):
        phase.status = status
    return state


def _closed(seconds: float, *, waited: float = 0.0) -> PhaseItem:
    return PhaseItem(
        id="x",
        label="x",
        status=PhaseStatus.DONE,
        started_at=100.0,
        ended_at=100.0 + seconds,
        waiting_total=waited,
    )


def test_a_question_outranks_every_other_run_status():
    """The user is the bottleneck: the header must say so even while a step runs."""
    state = _state(PhaseStatus.DONE, PhaseStatus.RUNNING)
    state.phases[1].begin_waiting(now=10.0)

    assert state.run_status() is RunStatus.AWAITING_INPUT


@pytest.mark.parametrize(
    ("statuses", "exit_code", "expected"),
    [
        ((PhaseStatus.DONE, PhaseStatus.RUNNING), None, RunStatus.RUNNING),
        ((PhaseStatus.DONE, PhaseStatus.DONE), 0, RunStatus.COMPLETED),
        ((PhaseStatus.DONE, PhaseStatus.SKIPPED), None, RunStatus.COMPLETED),
        ((PhaseStatus.DONE, PhaseStatus.FAILED), None, RunStatus.FAILED),
        ((PhaseStatus.DONE, PhaseStatus.PENDING), 1, RunStatus.FAILED),
        ((PhaseStatus.BLOCKED, PhaseStatus.PENDING), None, RunStatus.BLOCKED),
        ((PhaseStatus.DONE, PhaseStatus.PENDING), RUN_BLOCKED, RunStatus.BLOCKED),
        ((PhaseStatus.DONE, PhaseStatus.PENDING), None, RunStatus.PENDING),
    ],
)
def test_the_run_status_is_read_from_the_steps_and_the_exit_code(
    statuses: tuple[PhaseStatus, ...], exit_code: int | None, expected: RunStatus
):
    """A run reopened from history has no exit code, so the steps alone must name it."""
    state = _state(*statuses)
    state.exit_code = exit_code

    assert state.run_status() is expected


def test_a_stopped_run_says_stopped_not_failed():
    state = _state(PhaseStatus.DONE, PhaseStatus.RUNNING)
    state.mark_finished(RUN_STOPPED)

    assert state.run_status() is RunStatus.STOPPED


def test_a_run_with_no_steps_is_pending_not_completed():
    """Zero of zero steps is not a delivery."""
    assert CockpitState().run_status() is RunStatus.PENDING


def test_the_run_total_sums_each_step_net_of_waiting_on_the_user():
    state = CockpitState()
    state.phases = [
        _closed(90.0, waited=30.0),
        _closed(45.0),
        PhaseItem(id="later", label="later"),
    ]

    assert state.elapsed_seconds() == pytest.approx(105.0)


def test_a_step_that_never_started_has_no_clock():
    assert PhaseItem(id="x", label="x").elapsed_seconds(now=500.0) is None


def test_the_total_clock_keeps_one_width_past_the_hour():
    assert format_clock(0) == "00:00:00"
    assert format_clock(36 * 60 + 17) == "00:36:17"
    assert format_clock(10 * 3600 + 5) == "10:00:05"
    assert format_clock(-3) == "00:00:00"


def test_the_progress_meter_paints_one_segment_per_step_in_its_status_color():
    phases = [
        PhaseItem(id="a", label="a", status=PhaseStatus.DONE),
        PhaseItem(id="b", label="b", status=PhaseStatus.RUNNING),
        PhaseItem(id="c", label="c", status=PhaseStatus.PENDING),
    ]

    meter = progress_meter(phases, cells=12)

    assert meter.plain == "━━━ " * 3
    colors = [str(span.style) for span in meter.spans]
    assert colors == [status_color("done"), status_color("running"), BORDER]


def test_a_fan_out_wider_than_the_meter_is_sampled_not_overflowed():
    phases = [PhaseItem(id=f"t{n}", label="t", status=PhaseStatus.DONE) for n in range(40)]

    assert progress_meter(phases, cells=24).plain == "━" * 24


def test_every_status_color_has_its_own_tint():
    """A missing tint would quietly fall back to the pending gray behind a bright badge."""
    assert set(STATUS_COLORS.values()) <= set(STATUS_TINTS)


def test_the_header_shows_status_badge_progress_and_total():
    state = _state(PhaseStatus.DONE, PhaseStatus.RUNNING, PhaseStatus.PENDING)
    state.phases[0].started_at, state.phases[0].ended_at = 0.0, 125.0
    state.phases[1].started_at = 10.0
    state.phases[1].begin_waiting(now=70.0)
    state.set_branch("pulse/demo")
    state.set_model("opus")

    async def run() -> dict[str, str]:
        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                yield AppHeader()

        app = Harness()
        async with app.run_test(size=(140, 10)) as pilot:
            app.query_one(AppHeader).sync_from_state(state)
            await pilot.pause()
            return {
                key: str(app.query_one(f"#{key}", Static).render())
                for key in ("run-badge", "run-clock", "run-status", "run-where")
            }

    shown = asyncio.run(run())

    assert shown["run-badge"].strip() == "◆ PRECISA DE VOCÊ"
    assert shown["run-clock"].strip() == "TOTAL 00:03:05"
    assert shown["run-status"] == "1/3 etapas · 33%"
    assert shown["run-where"] == "branch pulse/demo · opus"
