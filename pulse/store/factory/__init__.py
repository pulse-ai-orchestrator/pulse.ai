"""Factory configuration: the rows Pulse ships knowing how to run.

Not a code catalog: nothing here is read during a run; the engine
([pulse.orchestrator.engine]) only knows `workflow_defs`, `workflow_steps` and
`agent_defs`. This package runs once on first DB open, converts the factory
`.md` files into rows, and gets out of the way.

The `.md` playbooks stay as files so they can be reviewed in diffs. The DB
stores resolved text: `<!-- include: name -->` directives from `shared/` are
expanded at seed time so each row is self-contained.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

INCLUDE = re.compile(r"^[ \t]*<!--[ \t]*include:[ \t]*([a-z0-9-]+)[ \t]*-->[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class FactoryStep:
    agent_id: str
    label: str
    requires_approval: bool
    fan_out: bool = False
    step_id: str = ""
    repeat_from: str = ""
    repeat_max: int = 0
    phase: str = ""
    commit_type: str = ""
    opens_request: bool = False

    def id(self) -> str:
        return self.step_id or self.agent_id


@dataclass(frozen=True)
class FactoryWorkflow:
    id: str
    label: str
    description: str
    steps: tuple[FactoryStep, ...]
    is_default: bool = False
    default_prompt: str = ""


AGENT_LABELS: dict[str, str] = {
    "prd": "PRD",
    "techspec": "Techspec",
    "tasks": "Tasks",
    "implement": "Implementar",
    "verify": "Verificar",
    "review": "Review",
    "review-fix": "Fix review",
    "quick-plan": "Quick plan",
    "quick-implement": "Quick implement",
    "setup-interview": "Setup — entrevista",
    "setup-artifacts": "Setup — artefatos",
    "codebase-explore": "Explorar codebase",
    "codebase-docs": "Docs de codebase",
}

WORKFLOWS: tuple[FactoryWorkflow, ...] = (
    FactoryWorkflow(
        id="new-issue",
        label="Nova spec",
        description="da ideia ao código revisado",
        steps=(
            FactoryStep("prd", "PRD", True),
            FactoryStep("techspec", "Techspec", True),
            FactoryStep("tasks", "Tasks", True),
            FactoryStep(
                "implement",
                "Implementar",
                False,
                fan_out=True,
                commit_type="feat",
                opens_request=True,
            ),
            FactoryStep("verify", "Verificar", True, commit_type="docs"),
            FactoryStep(
                "implement",
                "Corrigir lacunas",
                False,
                step_id="verify-fix",
                repeat_from="verify",
                repeat_max=3,
                phase="FIX",
                commit_type="fix",
            ),
            FactoryStep("review", "Review", True),
            FactoryStep(
                "review-fix",
                "Fix review",
                False,
                repeat_from="review",
                repeat_max=3,
                commit_type="fix",
            ),
        ),
    ),
    FactoryWorkflow(
        id="quick-fix",
        label="Correção rápida",
        description="mudança pequena, até 3 arquivos",
        steps=(
            FactoryStep("quick-plan", "Plano", True),
            FactoryStep("quick-implement", "Implementar", False, commit_type="fix"),
        ),
    ),
    FactoryWorkflow(
        id="review",
        label="Review",
        description="branch atual contra a main",
        steps=(
            FactoryStep("review", "Review", True, phase="STANDALONE"),
            FactoryStep(
                "review-fix",
                "Fix review",
                False,
                repeat_from="review",
                repeat_max=3,
                phase="STANDALONE",
                commit_type="fix",
            ),
        ),
        default_prompt="Revisar a branch atual",
    ),
    FactoryWorkflow(
        id="setup-project",
        label="Setup do projeto",
        description="gera os artefatos base",
        steps=(
            FactoryStep("setup-interview", "Entrevista", False),
            FactoryStep("setup-artifacts", "Artefatos", False),
        ),
        default_prompt="Novo projeto",
    ),
    FactoryWorkflow(
        id="analyze-codebase",
        label="Analisar codebase",
        description="documenta o repositório",
        steps=(
            FactoryStep("codebase-explore", "Exploração", False),
            FactoryStep("codebase-docs", "Documentação", False),
        ),
        default_prompt="Mapear codebase existente",
    ),
    FactoryWorkflow(
        id="default",
        label="Executar",
        description="tarefa livre, sem etapas",
        steps=(FactoryStep("default", "Executar", True, step_id="run"),),
        is_default=True,
    ),
)


def factory_dir() -> Path:
    return Path(__file__).resolve().parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def pull_request_template() -> str:
    """PR/MR body a factory workflow opens: `{{prompt}}`, `{{branch}}`, `{{commits}}`."""
    return _read(factory_dir() / "pull_request.md")


def _expand_includes(text: str) -> str:
    shared = factory_dir() / "shared"

    def _replace(match: re.Match[str]) -> str:
        return _read(shared / f"{match.group(1)}.md").rstrip("\n")

    return INCLUDE.sub(_replace, text)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Shallow YAML frontmatter of an `AGENT.md` and the body after it."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].lstrip("\n")


@dataclass(frozen=True)
class FactoryAgent:
    id: str
    label: str
    permission_policy: str
    instructions: str
    prompt_template: str


@cache
def load_phase(agent_id: str, phase: str = "PHASE") -> str:
    """A step's `prompt_template`: the `<phase>.md` in the agent's folder.

    Cached because an agent may appear in more than one step.
    """
    return _expand_includes(_read(factory_dir() / "agents" / agent_id / f"{phase}.md")).strip()


@lru_cache(maxsize=1)
def load_agents() -> tuple[FactoryAgent, ...]:
    """Read the factory `.md` files (cached; only seeding needs them).

    Frontmatter `runtime` and `model` are left out of the row: an empty value in
    `agent_defs` means "use the machine default", and a concrete value would
    freeze the `pulse init` choice. Per-agent pinning lives in `agent_settings`.
    """
    agents: list[FactoryAgent] = []
    root = factory_dir() / "agents"
    for agent_id, label in AGENT_LABELS.items():
        directory = root / agent_id
        meta, body = parse_frontmatter(_read(directory / "AGENT.md"))
        agents.append(
            FactoryAgent(
                id=agent_id,
                label=label,
                permission_policy=meta.get("permission_policy", ""),
                instructions=body.strip(),
                prompt_template=load_phase(agent_id),
            )
        )
    return tuple(agents)


def seed(connection: sqlite3.Connection) -> None:
    """Write the factory configuration. `INSERT OR IGNORE`: never undoes edits.

    An agent or step deleted from the DB is restored on the next open, since
    intentional deletions are not tracked.
    """
    agents = [
        (agent.id, agent.label, agent.permission_policy, agent.instructions)
        for agent in load_agents()
    ]
    agents.append(("default", "Agente", "", ""))
    connection.executemany(
        """
        INSERT OR IGNORE INTO agent_defs
            (id, label, runtime, model, permission_policy, instructions)
        VALUES (?, ?, '', '', ?, ?)
        """,
        agents,
    )

    def template(step: FactoryStep) -> str:
        if step.agent_id == "default":
            return "{{user_prompt}}"
        return load_phase(step.agent_id, step.phase or "PHASE")

    _make_room_for_new_steps(connection)
    connection.executemany(
        """
        INSERT OR IGNORE INTO workflow_defs
          (id, label, description, is_default, default_prompt, pull_request_template)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                item.id,
                item.label,
                item.description,
                int(item.is_default),
                item.default_prompt,
                pull_request_template(),
            )
            for item in WORKFLOWS
        ],
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO workflow_steps
          (workflow_id, step_id, position, label, agent_id, prompt_template,
           requires_approval, fan_out, repeat_from, repeat_max, commit_type,
           opens_request)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                workflow.id,
                step.id(),
                position,
                step.label,
                step.agent_id,
                template(step),
                int(step.requires_approval),
                int(step.fan_out),
                step.repeat_from,
                int(step.repeat_max),
                step.commit_type,
                int(step.opens_request),
            )
            for workflow in WORKFLOWS
            for position, step in enumerate(workflow.steps, start=1)
        ],
    )


def _make_room_for_new_steps(connection: sqlite3.Connection) -> None:
    """Shift existing steps so a factory step new to a seeded workflow lands in order.

    `INSERT OR IGNORE` at the factory position would tie with the step already
    there, and `ORDER BY position, step_id` would then run them alphabetically.
    All shifts run before the insert and accumulate, so several missing steps
    each land at their factory position.
    """
    for workflow in WORKFLOWS:
        present = {
            row[0]
            for row in connection.execute(
                "SELECT step_id FROM workflow_steps WHERE workflow_id = ?", (workflow.id,)
            )
        }
        if not present:
            continue
        for position, step in enumerate(workflow.steps, start=1):
            if step.id() in present:
                continue
            connection.execute(
                """
                UPDATE workflow_steps SET position = position + 1
                 WHERE workflow_id = ? AND position >= ?
                """,
                (workflow.id, position),
            )


def inherit_policy_on_default_agent(connection: sqlite3.Connection) -> None:
    """Make DBs seeded with `ask` on the `default` agent inherit the policy.

    A hardcoded `ask` overrode machine and project policy in
    `_resolve_pulse_agent`. Idempotent: after the first open no row matches.
    """
    connection.execute(
        "UPDATE agent_defs SET permission_policy = '' "
        "WHERE id = 'default' AND permission_policy = 'ask'"
    )


def backfill_commit_types(connection: sqlite3.Connection) -> None:
    """Fill `commit_type` where the column was just added and is still empty.

    `seed` does not rewrite existing rows, so a later edit of the column stays.
    """
    rows = [
        (step.commit_type, workflow.id, step.id())
        for workflow in WORKFLOWS
        for step in workflow.steps
        if step.commit_type
    ]
    connection.executemany(
        """
        UPDATE workflow_steps
           SET commit_type = ?
         WHERE workflow_id = ? AND step_id = ? AND commit_type = ''
        """,
        rows,
    )


def backfill_opens_request(connection: sqlite3.Connection) -> None:
    """Turn on `opens_request` where the column was just added and is still off.

    `seed` does not rewrite existing rows, so an upgrade would leave the factory
    step that opens the request unable to open it. A later edit stays: this runs
    only on the migration that adds the column.
    """
    rows = [
        (workflow.id, step.id())
        for workflow in WORKFLOWS
        for step in workflow.steps
        if step.opens_request
    ]
    connection.executemany(
        """
        UPDATE workflow_steps
           SET opens_request = 1
         WHERE workflow_id = ? AND step_id = ? AND opens_request = 0
        """,
        rows,
    )


def backfill_pull_request_templates(connection: sqlite3.Connection) -> None:
    """Fill `pull_request_template` where the column was just added and is still empty."""
    template = pull_request_template()
    connection.executemany(
        "UPDATE workflow_defs SET pull_request_template = ? "
        "WHERE id = ? AND pull_request_template = ''",
        [(template, item.id) for item in WORKFLOWS],
    )


def backfill_default_prompts(connection: sqlite3.Connection) -> None:
    """Fill `default_prompt` in DBs seeded before the column existed.

    The `ALTER` gives existing rows `''` and `seed` does not rerun. Only empty
    values are touched, so user-edited loops are preserved.
    """
    connection.executemany(
        "UPDATE workflow_defs SET default_prompt = ? WHERE id = ? AND default_prompt = ''",
        [(item.default_prompt, item.id) for item in WORKFLOWS if item.default_prompt],
    )


APPROVAL_MARK = "Aprovar {{step_label}} e avançar?"

UNATTENDED_STEPS: tuple[tuple[str, str], ...] = (
    ("setup-project", "setup-interview"),
    ("analyze-codebase", "codebase-explore"),
)


def drop_approval_from_unattended_steps(connection: sqlite3.Connection) -> None:
    """Remove the approval request from these steps in already-seeded DBs.

    `seed` never rewrites existing rows, so only rows still carrying the factory
    approval block are updated; user-rewritten templates are left alone. Runs on
    every DB open, so it exits early via `SELECT` before calling `load_agents`.
    """
    # Only the `?` placeholders are interpolated; every value is bound.
    placeholders = ",".join("?" * len(UNATTENDED_STEPS))
    pending = connection.execute(
        f"""
        SELECT count(*) FROM workflow_steps
         WHERE step_id IN ({placeholders}) AND instr(prompt_template, ?) > 0
        """,  # noqa: S608  # only `?` placeholders are interpolated
        (*(step_id for _workflow_id, step_id in UNATTENDED_STEPS), APPROVAL_MARK),
    ).fetchone()[0]
    if not pending:
        return

    templates = {agent.id: agent.prompt_template for agent in load_agents()}
    connection.executemany(
        """
        UPDATE workflow_steps
           SET requires_approval = 0, prompt_template = ?
         WHERE workflow_id = ? AND step_id = ? AND instr(prompt_template, ?) > 0
        """,
        [
            (templates[step_id], workflow_id, step_id, APPROVAL_MARK)
            for workflow_id, step_id in UNATTENDED_STEPS
        ],
    )


LAST_TASK_VALIDATION_MARK = "### 9. Feature-level validation (after the LAST task)"


def drop_validation_from_implement(connection: sqlite3.Connection) -> None:
    """Stop old `implement` rows from validating the feature in the last task.

    The feature check moved to the `verify` step, but `seed` never rewrites
    `agent_defs`. A row still carrying the factory section is reset to the
    factory text, other edits in it included; a row without the section belongs
    to the user and stays. Runs on every open: exits early via `SELECT`.
    """
    pending = connection.execute(
        "SELECT count(*) FROM agent_defs WHERE id = 'implement' AND instr(instructions, ?) > 0",
        (LAST_TASK_VALIDATION_MARK,),
    ).fetchone()[0]
    if not pending:
        return
    implement = next(agent for agent in load_agents() if agent.id == "implement")
    connection.execute(
        """
        UPDATE agent_defs SET instructions = ?
         WHERE id = 'implement' AND instr(instructions, ?) > 0
        """,
        (implement.instructions, LAST_TASK_VALIDATION_MARK),
    )


UNCAPPED_STEP_MARK = "There is no cap on rounds."
UNCAPPED_AGENT_MARK = "There is no cap on the number of rounds."


def refresh_uncapped_clarify_loops(connection: sqlite3.Connection) -> None:
    """Reset rows that still tell the agent its questions have no round limit.

    The approval loop stops at a turn cap; an agent told otherwise asked one
    question per round, hit the cap, and its retry asked everything again. `seed`
    never rewrites rows, so a factory row still carrying the old sentence is reset
    to the factory text, other edits in it included; a row without the sentence
    belongs to the user and stays. Runs on every open: exits early via `SELECT`.
    """
    steps = connection.execute(
        "SELECT workflow_id, step_id FROM workflow_steps WHERE instr(prompt_template, ?) > 0",
        (UNCAPPED_STEP_MARK,),
    ).fetchall()
    agents = connection.execute(
        "SELECT id FROM agent_defs WHERE instr(instructions, ?) > 0",
        (UNCAPPED_AGENT_MARK,),
    ).fetchall()
    if not steps and not agents:
        return

    factory_steps = {(item.id, step.id()): step for item in WORKFLOWS for step in item.steps}
    for row in steps:
        step = factory_steps.get((row[0], row[1]))
        if step is None:
            continue
        connection.execute(
            "UPDATE workflow_steps SET prompt_template = ? WHERE workflow_id = ? AND step_id = ?",
            (load_phase(step.agent_id, step.phase or "PHASE"), row[0], row[1]),
        )
    instructions = {agent.id: agent.instructions for agent in load_agents()}
    connection.executemany(
        "UPDATE agent_defs SET instructions = ? WHERE id = ?",
        [(instructions[row[0]], row[0]) for row in agents if row[0] in instructions],
    )


def _count_present(
    connection: sqlite3.Connection, table: str, column: str, ids: tuple[str, ...]
) -> int:
    # `table` and `column` are literals from `is_seeded`, never input.
    placeholders = ",".join("?" * len(ids))
    query = f"SELECT count(*) FROM {table} WHERE {column} IN ({placeholders})"  # noqa: S608
    return int(connection.execute(query, ids).fetchone()[0])


def is_seeded(connection: sqlite3.Connection) -> bool:
    """Whether every factory row is already present.

    Called on every `connect`, so it only counts factory ids instead of
    rereading the playbooks; user-created rows are ignored.
    """
    agent_ids = (*AGENT_LABELS, "default")
    if _count_present(connection, "agent_defs", "id", agent_ids) != len(agent_ids):
        return False
    workflow_ids = tuple(item.id for item in WORKFLOWS)
    if _count_present(connection, "workflow_defs", "id", workflow_ids) != len(workflow_ids):
        return False
    steps = sum(len(item.steps) for item in WORKFLOWS)
    return _count_present(connection, "workflow_steps", "workflow_id", workflow_ids) == steps
