from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pulse.tui.adapters.cockpit_sink import CockpitSink
from pulse.tui.state import CockpitState, LogKind, PhaseStatus
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.log_stream import LogStream
from tests.conftest import configure_from_db, make_workflow

SHAPES: dict[str, list[tuple[str, str]]] = {
    "single": [("only", "Único")],
    "pair": [("plan", "Planejar"), ("build", "Construir")],
    "many": [
        ("one", "Primeiro"),
        ("two", "Segundo"),
        ("three", "Terceiro"),
        ("four", "Quarto"),
    ],
}
WORKFLOWS = tuple(SHAPES)


def _configure(workflow_id: str) -> CockpitState:
    make_workflow(workflow_id, steps=SHAPES[workflow_id])
    state = CockpitState()
    configure_from_db(state, workflow_id)
    return state


def _titles(workflow_id: str) -> list[str]:
    return [label for _step_id, label in SHAPES[workflow_id]]


TOOL_SAMPLES: tuple[tuple[str, dict, LogKind, str], ...] = (
    (
        "read",
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "t-read",
            "title": "Read File",
            "kind": "read",
            "status": "pending",
            "rawInput": {"path": "/repo/pulse/cli.py"},
        },
        LogKind.READ,
        "pulse/cli.py",
    ),
    (
        "edit",
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "t-edit",
            "title": "Edit File",
            "kind": "edit",
            "status": "pending",
            "rawInput": {"path": "/repo/docs/PRD.md"},
        },
        LogKind.EDIT,
        "PRD.md",
    ),
    (
        "write",
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "t-write",
            "title": "Write File",
            "kind": "write",
            "status": "pending",
            "rawInput": {"path": "/repo/docs/STATE.md"},
        },
        LogKind.WRITE,
        "STATE.md",
    ),
    (
        "search",
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "t-search",
            "title": "Find",
            "kind": "search",
            "status": "pending",
            "rawInput": {"pattern": "dashboard", "path": "/repo/docs"},
        },
        LogKind.SEARCH,
        "dashboard",
    ),
    (
        "shell",
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "t-shell",
            "title": "Shell",
            "kind": "execute",
            "status": "pending",
            "rawInput": {"command": "pytest -q"},
        },
        LogKind.SHELL,
        "pytest -q",
    ),
)


def _plain_tool_line(kind: str, target: str) -> str:
    """A settled call reads as one line: check, kind padded to a column, target."""
    return f"✓ {kind:<7} {target}"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _render_plain(state: CockpitState) -> str:
    stream = LogStream(state)
    stream._spin_frame = 0
    return stream._render_entries(state).plain


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_sidebar_comes_from_the_database(workflow_id: str):
    state = _configure(workflow_id)
    assert [(phase.id, phase.label) for phase in state.phases] == SHAPES[workflow_id]


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_phase_titles_mark_running_across_workflows(workflow_id: str):
    state = _configure(workflow_id)
    titles = _titles(workflow_id)
    for index, title in enumerate(titles):
        sink = CockpitSink(state, cwd="/repo")
        sink.begin_phase(title)
        assert state.phases[index].status == PhaseStatus.RUNNING, (
            f"{workflow_id}/{title} should mark phase[{index}] running"
        )
        for prev in range(index):
            assert state.phases[prev].status == PhaseStatus.DONE
        for nxt in range(index + 1, len(state.phases)):
            assert state.phases[nxt].status == PhaseStatus.PENDING


def test_resume_jump_to_last_phase_marks_prior_done():
    state = _configure("many")
    sink = CockpitSink(state, cwd="/repo")
    sink.apply_phase_statuses(done_ids=("one",), skipped_ids=("two", "three"))
    sink.begin_phase("Quarto")
    assert [phase.status for phase in state.phases] == [
        PhaseStatus.DONE,
        PhaseStatus.SKIPPED,
        PhaseStatus.SKIPPED,
        PhaseStatus.RUNNING,
    ]


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
@pytest.mark.parametrize("sample", TOOL_SAMPLES, ids=[s[0] for s in TOOL_SAMPLES])
def test_tool_kinds_pending_then_gray_block(workflow_id: str, sample: tuple):
    _name, call_payload, expected_kind, target_snip = sample
    state = _configure(workflow_id)
    sink = CockpitSink(state, cwd="/repo")
    sink.begin_phase(_titles(workflow_id)[0])

    call = dict(call_payload)
    call["toolCallId"] = f"{workflow_id}-{call['toolCallId']}"
    sink.handle_update({"update": call})
    entry = state.entries[-1]
    assert entry.kind == expected_kind
    assert entry.pending is True
    assert target_snip in entry.title or target_snip in entry.detail

    plain = _render_plain(state)
    assert expected_kind.value in plain
    assert target_snip in plain or "carregando" in plain or "…" in plain
    kind_line = next(line for line in plain.splitlines() if expected_kind.value in line)
    assert target_snip in kind_line or "carregando" in kind_line or "…" in kind_line

    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": call["toolCallId"],
                "status": "in_progress",
            }
        }
    )
    assert state.entries[-1].pending is True

    completed: dict = {
        "sessionUpdate": "tool_call_update",
        "toolCallId": call["toolCallId"],
        "status": "completed",
    }
    if expected_kind == LogKind.SEARCH:
        completed["rawOutput"] = {"totalFiles": 2}
        completed["locations"] = [
            "/repo/docs/a.md",
            "/repo/docs/b.md",
        ]
    sink.handle_update({"update": completed})
    assert state.entries[-1].pending is False

    plain_done = _render_plain(state)
    done_line = next(line for line in plain_done.splitlines() if f"✓ {expected_kind.value}" in line)
    assert target_snip in done_line
    if expected_kind == LogKind.SEARCH:
        assert "2 files" in plain_done or "in docs" in plain_done


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_assistant_gutter_across_workflows(workflow_id: str):
    state = _configure(workflow_id)
    sink = CockpitSink(state, cwd="/repo")
    sink.begin_phase(_titles(workflow_id)[0])
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {
                    "type": "text",
                    "text": "Vou usar `PRD` e marcar **large** no STATE.",
                },
            }
        }
    )
    plain = _render_plain(state)
    assert "Assistente" in plain
    assert "│" in plain
    assert "PRD" in plain
    assert "large" in plain
    assert "**" not in plain
    assert "`" not in plain


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_placeholder_keeps_spinner_until_path(workflow_id: str, tmp_path: Path, monkeypatch):
    import json
    import sqlite3

    session_id = f"sess-{workflow_id}"
    root = tmp_path / "acp-sessions" / session_id
    root.mkdir(parents=True)
    db = root / "store.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    con.commit()
    con.close()
    monkeypatch.setattr("pulse.tui.cursor_store._ACP_SESSIONS", tmp_path / "acp-sessions")
    monkeypatch.setattr("pulse.tui.cursor_store._CHATS", tmp_path / "chats")

    state = _configure(workflow_id)
    sink = CockpitSink(state, cwd="/repo", session_id=session_id)
    sink.begin_phase(_titles(workflow_id)[0])
    tool_id = f"{workflow_id}-placeholder\nfc_1"

    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_id,
                "title": "Read File",
                "kind": "read",
                "status": "pending",
                "rawInput": {},
            }
        }
    )
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_id,
                "status": "completed",
            }
        }
    )
    assert state.entries[-1].pending is True
    plain = _render_plain(state)
    assert "carregando…" in plain or "…" in plain
    assert "✓ Read" not in plain

    con = sqlite3.connect(db)
    blob = {
        "role": "assistant",
        "content": [
            {
                "type": "tool-call",
                "toolCallId": tool_id,
                "toolName": "Read",
                "args": {"path": f"/repo/{workflow_id}/file.md"},
            }
        ],
    }
    con.execute("INSERT INTO blobs(id, data) VALUES (?, ?)", ("1", json.dumps(blob).encode()))
    con.commit()
    con.close()

    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Seguindo."},
            }
        }
    )
    entry = next(item for item in state.entries if item.tool_id == tool_id)
    assert entry.pending is False
    assert entry.title.endswith("file.md")
    plain_done = _render_plain(state)
    assert _plain_tool_line("Read", f"{workflow_id}/file.md") in plain_done


@pytest.mark.parametrize("workflow_id", WORKFLOWS)
def test_textual_render_smoke_all_workflows(workflow_id: str):
    async def run() -> None:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal

        from pulse.tui.widgets.phase_sidebar import PhaseSidebar

        holder: dict = {}

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                state = _configure(workflow_id)
                holder["state"] = state
                holder["sink"] = CockpitSink(state, cwd="/repo")
                with Horizontal():
                    yield PhaseSidebar(state, id="phase-sidebar")
                    yield LogStream(state, id="log-stream")

            def on_mount(self) -> None:
                sink: CockpitSink = holder["sink"]
                sink.begin_phase(_titles(workflow_id)[0])
                sink.handle_update(
                    {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {
                                "type": "text",
                                "text": f"Rodando `{workflow_id}` com **cuidado**.",
                            },
                        }
                    }
                )
                for _name, payload, _kind, _snip in TOOL_SAMPLES[:3]:
                    call = dict(payload)
                    call["toolCallId"] = f"smoke-{workflow_id}-{call['toolCallId']}"
                    sink.handle_update({"update": call})
                    sink.handle_update(
                        {
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": call["toolCallId"],
                                "status": "completed",
                            }
                        }
                    )
                self.query_one(PhaseSidebar).sync_from_state(holder["state"])
                self.query_one(LogStream).sync_from_state(holder["state"], force=True)

        app = Harness()
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            content = str(app.query_one("#stream-content").render())
            phases = str(app.query_one("#phase-content").render())
            assert "Assistente" in content
            assert "│" in content
            assert "Read" in content
            assert "Edit" in content
            assert "Write" in content
            assert "✓ Read" in content
            assert "\n  " in content or "  pulse/" in content or "cli.py" in content
            assert any(phase.label in phases for phase in holder["state"].phases)
            assert "executando" in phases or "pendente" in phases

    asyncio.run(run())


def test_search_detail_gray_block_layout():
    state = _configure("many")
    sink = CockpitSink(state, cwd="/repo")
    sink.begin_phase("Primeiro")
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": "search-layout",
                "title": "Find",
                "kind": "search",
                "rawInput": {"pattern": "dashboard", "path": "/repo/docs"},
            }
        }
    )
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "search-layout",
                "status": "completed",
                "rawOutput": {"totalFiles": 3},
                "locations": [
                    "/repo/docs/a.md",
                    "/repo/docs/b.md",
                    "/repo/docs/c.md",
                ],
            }
        }
    )
    plain = _render_plain(state)
    lines = [line for line in plain.splitlines() if line.strip()]
    head = next(index for index, line in enumerate(lines) if "✓ Search" in line)
    assert lines[head].endswith(_plain_tool_line("Search", "“dashboard”"))
    detail = lines[head + 1 : head + 3]
    assert "in docs" in detail[0]
    assert "3 files" in detail[0]
    target_column = lines[head].index("“dashboard”")
    assert all(_indent(line) == target_column for line in detail), "details hang under the target"


def test_log_stream_renders_only_selected_step():
    state = _configure("many")
    sink = CockpitSink(state, cwd="/repo")
    sink.begin_phase("Primeiro")
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Escrevendo spec"},
            }
        }
    )
    sink.begin_phase("Segundo")
    sink.handle_update(
        {
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Escrevendo design"},
            }
        }
    )
    design_plain = _render_plain(state)
    assert "Escrevendo design" in design_plain
    assert "Escrevendo spec" not in design_plain

    state.select_phase(0)
    spec_plain = _render_plain(state)
    assert "Escrevendo spec" in spec_plain
    assert "Escrevendo design" not in spec_plain
    assert "Nenhuma atividade neste step." not in spec_plain

    state.select_phase(3)
    empty_plain = _render_plain(state)
    assert "Aguardando atividade do agente…" in empty_plain


def test_loop_shows_one_line_with_counter_not_one_per_round():
    """Three review rounds are one `Review ×3` line, not `Review (2ª rodada)`.

    The counter sits on the step that opens the loop, since it has one artifact
    per round to open; the closing step shows no counter, which would be noise.
    """

    async def run() -> None:
        from textual.app import App, ComposeResult

        from pulse.tui.widgets.phase_sidebar import PhaseSidebar

        holder: dict = {}

        class Harness(App[None]):
            CSS = COCKPIT_CSS

            def compose(self) -> ComposeResult:
                state = _configure("many")
                holder["state"] = state
                yield PhaseSidebar(state, id="phase-sidebar")

            def on_mount(self) -> None:
                state = holder["state"]
                state.apply_phase_statuses(
                    steps=[
                        {"id": "review", "label": "Review", "rounds": 3},
                        {"id": "fix", "label": "Fix review", "rounds": 1},
                    ],
                    done_ids=["review", "fix"],
                )
                self.query_one(PhaseSidebar).sync_from_state(state)

        app = Harness()
        async with app.run_test(size=(60, 24)) as pilot:
            await pilot.pause()
            phases = str(app.query_one("#phase-content").render())

            assert "Review ×3" in phases
            assert "Fix review" in phases
            assert "Fix review ×" not in phases
            assert "rodada" not in phases
            assert "review#2" not in phases

    asyncio.run(run())
