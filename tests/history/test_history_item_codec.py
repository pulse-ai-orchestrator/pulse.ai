"""`HistoryItem` travels from `/api/history` to the history screen through one codec."""

from __future__ import annotations

import pytest

from pulse.domain.run import StepStatus
from pulse.history.models import HistoryItem, HistoryStatus, HistoryStep


def _item() -> HistoryItem:
    return HistoryItem(
        run_id="run-1",
        workflow_id="demo",
        workflow_label="Demo",
        title="Adicionar login",
        prompt="Adicionar login",
        status=HistoryStatus.AWAITING_INPUT,
        updated_at="2026-10-08T10:00:00+00:00",
        steps=[
            HistoryStep(id="plan", label="Plan", status=StepStatus.DONE, acp_session_id="s-1"),
            HistoryStep(id="build", label="Build", status=StepStatus.PENDING),
        ],
        artifacts=["PLANO.md"],
        branch="pulse/demo-run1",
        worktree_path="/wt/run-1",
        duration_seconds=872.0,
    )


def test_a_history_item_survives_the_wire_unchanged() -> None:
    """The step's ACP session too: the history log is read back by it."""
    assert HistoryItem.from_dict(_item().to_dict()) == _item()


@pytest.mark.parametrize("bad", ["14:32", -1, True, float("nan"), float("inf")])
def test_a_missing_or_unusable_duration_is_left_out(bad: object) -> None:
    """An older daemon omits the field; a bad value must not become a duration."""
    data = _item().to_dict()
    data.pop("duration_seconds")
    assert HistoryItem.from_dict(data).duration_seconds is None
    assert HistoryItem.from_dict({**data, "duration_seconds": bad}).duration_seconds is None


def test_an_unknown_status_reads_back_as_pending() -> None:
    data = {**_item().to_dict(), "status": "exploded", "steps": [{"id": "s", "status": "?"}]}

    item = HistoryItem.from_dict(data)

    assert item.status is HistoryStatus.PENDING
    assert item.steps == [HistoryStep(id="s", label="", status=StepStatus.PENDING)]
