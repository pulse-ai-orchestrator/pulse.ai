"""Workflow, step and agent definitions: the single source of what Pulse runs.

There is no catalog in code; factory definitions are seeded by
[pulse.store.db] the first time the database is opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pulse.domain.workflow import AgentDef, RepeatRule, StepDef, WorkflowDef
from pulse.store.db import connect, default_db_path


def _agent(row: sqlite3.Row) -> AgentDef:
    return AgentDef(
        id=str(row["id"]),
        label=str(row["label"]),
        runtime=str(row["runtime"] or ""),
        model=str(row["model"] or ""),
        permission_policy=str(row["permission_policy"] or ""),
        instructions=str(row["instructions"] or ""),
    )


def _step(row: sqlite3.Row) -> StepDef:
    return StepDef(
        workflow_id=str(row["workflow_id"]),
        step_id=str(row["step_id"]),
        position=int(row["position"]),
        label=str(row["label"]),
        agent_id=str(row["agent_id"]),
        prompt_template=str(row["prompt_template"] or ""),
        requires_approval=bool(row["requires_approval"]),
        fan_out=bool(row["fan_out"]),
        requires_outcome=bool(row["requires_outcome"]),
        repeat=RepeatRule.from_columns(str(row["repeat_from"] or ""), int(row["repeat_max"] or 0)),
        commit_type=str(row["commit_type"] or ""),
        opens_request=bool(row["opens_request"]),
    )


def _workflow(row: sqlite3.Row, steps: tuple[StepDef, ...]) -> WorkflowDef:
    return WorkflowDef(
        id=str(row["id"]),
        label=str(row["label"]),
        description=str(row["description"] or ""),
        is_default=bool(row["is_default"]),
        default_prompt=str(row["default_prompt"] or ""),
        pull_request_template=str(row["pull_request_template"] or ""),
        steps=steps,
    )


def list_workflows(*, db_path: Path | None = None) -> list[WorkflowDef]:
    connection = connect(db_path or default_db_path())
    try:
        rows = connection.execute(
            "SELECT * FROM workflow_defs ORDER BY is_default DESC, label"
        ).fetchall()
        return [_workflow(row, _steps_for(connection, str(row["id"]))) for row in rows]
    finally:
        connection.close()


def get_workflow(workflow_id: str, *, db_path: Path | None = None) -> WorkflowDef | None:
    connection = connect(db_path or default_db_path())
    try:
        row = connection.execute(
            "SELECT * FROM workflow_defs WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            return None
        return _workflow(row, _steps_for(connection, workflow_id))
    finally:
        connection.close()


def _steps_for(connection: sqlite3.Connection, workflow_id: str) -> tuple[StepDef, ...]:
    rows = connection.execute(
        "SELECT * FROM workflow_steps WHERE workflow_id = ? ORDER BY position, step_id",
        (workflow_id,),
    ).fetchall()
    return tuple(_step(row) for row in rows)


def get_agent(agent_id: str, *, db_path: Path | None = None) -> AgentDef | None:
    connection = connect(db_path or default_db_path())
    try:
        row = connection.execute("SELECT * FROM agent_defs WHERE id = ?", (agent_id,)).fetchone()
    finally:
        connection.close()
    return _agent(row) if row is not None else None


def list_agents(*, db_path: Path | None = None) -> list[AgentDef]:
    connection = connect(db_path or default_db_path())
    try:
        rows = connection.execute("SELECT * FROM agent_defs ORDER BY label").fetchall()
    finally:
        connection.close()
    return [_agent(row) for row in rows]


def save_agent(agent: AgentDef, *, db_path: Path | None = None) -> None:
    connection = connect(db_path or default_db_path())
    try:
        connection.execute(
            """
            INSERT INTO agent_defs (id, label, runtime, model, permission_policy, instructions)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              label = excluded.label,
              runtime = excluded.runtime,
              model = excluded.model,
              permission_policy = excluded.permission_policy,
              instructions = excluded.instructions
            """,
            (
                agent.id,
                agent.label,
                agent.runtime,
                agent.model,
                agent.permission_policy,
                agent.instructions,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def save_workflow(workflow: WorkflowDef, *, db_path: Path | None = None) -> None:
    """Save the definition and replace its steps.

    Steps are rewritten wholesale, not merged, so a removed step disappears
    instead of lingering as a silent orphan.
    """
    connection = connect(db_path or default_db_path())
    try:
        connection.execute(
            """
            INSERT INTO workflow_defs (id, label, description, is_default, pull_request_template)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              label = excluded.label,
              description = excluded.description,
              is_default = excluded.is_default,
              pull_request_template = excluded.pull_request_template
            """,
            (
                workflow.id,
                workflow.label,
                workflow.description,
                int(workflow.is_default),
                workflow.pull_request_template,
            ),
        )
        connection.execute("DELETE FROM workflow_steps WHERE workflow_id = ?", (workflow.id,))
        connection.executemany(
            """
            INSERT INTO workflow_steps
              (workflow_id, step_id, position, label, agent_id, prompt_template,
               requires_approval, fan_out, requires_outcome, repeat_from, repeat_max,
               commit_type, opens_request)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    workflow.id,
                    step.step_id,
                    index,
                    step.label,
                    step.agent_id,
                    step.prompt_template,
                    int(step.requires_approval),
                    int(step.fan_out),
                    int(step.requires_outcome),
                    step.repeat.back_to if step.repeat else "",
                    step.repeat.max_rounds if step.repeat else 0,
                    step.commit_type,
                    int(step.opens_request),
                )
                for index, step in enumerate(workflow.steps, start=1)
            ],
        )
        connection.commit()
    finally:
        connection.close()


def delete_workflow(workflow_id: str, *, db_path: Path | None = None) -> None:
    connection = connect(db_path or default_db_path())
    try:
        connection.execute("DELETE FROM workflow_steps WHERE workflow_id = ?", (workflow_id,))
        connection.execute("DELETE FROM workflow_defs WHERE id = ?", (workflow_id,))
        connection.commit()
    finally:
        connection.close()
