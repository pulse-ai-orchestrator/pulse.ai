"""The definitions Pulse can run; none of them come from files."""

from __future__ import annotations

import re
from pathlib import Path

from pulse.domain.workflow import AgentDef, RepeatRule, StepDef, WorkflowDef
from pulse.store.db import connect, default_db_path
from pulse.store.workflow_defs import (
    delete_workflow,
    get_agent,
    get_workflow,
    list_workflows,
    save_agent,
    save_workflow,
)


def test_a_fresh_database_already_has_the_factory_loops():
    """Factory config seeds the database; it is not a catalog in code."""
    workflows = {item.id: item for item in list_workflows()}

    assert set(workflows) >= {
        "default",
        "new-issue",
        "quick-fix",
        "review",
        "setup-project",
        "analyze-codebase",
    }
    assert workflows["default"].is_default is True
    assert workflows["default"].steps[0].prompt_template == "{{user_prompt}}"
    assert [step.step_id for step in workflows["new-issue"].steps] == [
        "prd",
        "techspec",
        "tasks",
        "implement",
        "verify",
        "verify-fix",
        "review",
        "review-fix",
    ]
    assert [step.requires_approval for step in workflows["new-issue"].steps] == [
        True,
        True,
        True,
        False,
        True,
        False,
        True,
        False,
    ]
    assert get_agent("prd") is not None


def test_the_review_loop_runs_outside_the_spec_pipeline():
    """Same agents as the spec pipeline, different phase: no PRD or tasks here."""
    review = get_workflow("review")

    assert review is not None
    assert review.default_prompt, "reviews the current branch; there is nothing to ask"
    assert [step.agent_id for step in review.steps] == ["review", "review-fix"]
    assert [step.requires_approval for step in review.steps] == [True, False]
    fix = review.steps[1]
    assert fix.repeat == RepeatRule(back_to="review", max_rounds=3)
    for step in review.steps:
        assert ".pulse/reviews/" in step.prompt_template
        assert "<slug>/reviews/" not in step.prompt_template


def test_every_factory_step_renders_with_what_the_engine_offers():
    """A placeholder without a value is a `TemplateError` at run time, caught here first."""
    from pulse.orchestrator.render import render

    context = dict.fromkeys(
        (
            "user_prompt",
            "workspace",
            "workflow_id",
            "run_id",
            "step_id",
            "step_label",
            "previous_summary",
            "previous_status",
            "artifacts",
        ),
        "x",
    )
    first_step = dict(context, previous_summary="", previous_status="", artifacts="")

    for workflow in list_workflows():
        for step in workflow.steps:
            render(step.prompt_template, context)
            render(step.prompt_template, first_step)


def test_the_factory_pull_request_template_is_the_repository_template():
    """The seed, the engine fallback and the GitHub file are one template."""
    from pulse.orchestrator.pull_request_template import PULSE_PULL_REQUEST_TEMPLATE
    from pulse.store.factory import pull_request_template

    github = (
        Path(__file__).resolve().parents[2] / ".github" / "pull_request_template.md"
    ).read_text(encoding="utf-8")

    assert pull_request_template() == github
    assert PULSE_PULL_REQUEST_TEMPLATE == github


def test_every_factory_pull_request_template_renders_with_what_the_engine_offers():
    """The body is rendered at the end of a run; a placeholder the engine does not fill
    would leave the pull request unopened.
    """
    from pulse.orchestrator.delivery import pull_request_body

    for workflow in list_workflows():
        body = pull_request_body(
            workflow.pull_request_template,
            prompt="Corrigir o login",
            branch="corrigir-o-login",
            commits=["feat: add email validation"],
        )
        assert "Corrigir o login" in body
        assert "- feat: add email validation" in body
        assert "{{" not in body


def test_factory_agents_carry_their_playbook_and_defer_on_runtime():
    prd = get_agent("prd")

    assert prd is not None
    assert "Ambiguity Ledger" in prd.instructions
    assert prd.permission_policy == "deny_writes"
    assert (prd.runtime, prd.model) == ("", "")


def test_the_default_agent_defers_to_the_machine():
    """Empty field means "use the default"; a fixed runtime would freeze `pulse init`."""
    agent = get_agent("default")

    assert agent is not None
    assert agent.runtime == ""
    assert agent.model == ""


def test_domain_markdown_lives_only_in_the_factory_seed():
    """Domain `.md` files are seed data: only `store/factory` loads them.

    The engine must not know phases by name. A `.md` read once into the database
    is fine; one read at run time would reintroduce that coupling.
    """
    package = Path(__file__).resolve().parents[2] / "pulse"
    seed_dir = package / "store" / "factory"
    leftovers = [
        path.relative_to(package)
        for path in package.rglob("*")
        if path.is_file()
        and path.suffix != ".py"
        and "__pycache__" not in path.parts
        and seed_dir not in path.parents
    ]

    assert leftovers == []

    readers = [
        path.relative_to(package)
        for path in package.rglob("*.py")
        if seed_dir not in path.parents
        and re.search(
            r"pulse\.store\.factory|from pulse\.store import factory",
            path.read_text(encoding="utf-8"),
        )
    ]

    assert readers == [Path("store/db.py")]


def test_saving_a_workflow_replaces_its_steps():
    save_agent(AgentDef(id="tester", label="Tester"))
    first = WorkflowDef(
        id="demo",
        label="Demo",
        steps=(
            StepDef("demo", "a", 1, "A", "tester", "{{user_prompt}}", True),
            StepDef("demo", "b", 2, "B", "tester", "{{previous_summary}}", False),
        ),
    )
    save_workflow(first)

    save_workflow(
        WorkflowDef(
            id="demo",
            label="Demo v2",
            steps=(StepDef("demo", "a", 1, "A", "tester", "{{user_prompt}}", True),),
        )
    )

    loaded = get_workflow("demo")
    assert loaded is not None
    assert loaded.label == "Demo v2"
    assert [step.step_id for step in loaded.steps] == ["a"]


def test_steps_come_back_in_position_order():
    save_agent(AgentDef(id="tester", label="Tester"))
    save_workflow(
        WorkflowDef(
            id="demo",
            label="Demo",
            steps=(
                StepDef("demo", "third", 0, "3", "tester", "x", False),
                StepDef("demo", "first", 0, "1", "tester", "x", False),
                StepDef("demo", "second", 0, "2", "tester", "x", False),
            ),
        )
    )

    loaded = get_workflow("demo")
    assert loaded is not None
    assert [step.step_id for step in loaded.steps] == ["third", "first", "second"]


def test_deleting_a_workflow_takes_its_steps_along():
    save_agent(AgentDef(id="tester", label="Tester"))
    save_workflow(
        WorkflowDef(
            id="demo",
            label="Demo",
            steps=(StepDef("demo", "a", 1, "A", "tester", "x", False),),
        )
    )

    delete_workflow("demo")

    assert get_workflow("demo") is None
    assert "demo" not in {item.id for item in list_workflows()}


def test_unknown_ids_are_none_not_an_invented_default():
    assert get_workflow("nao-existe") is None
    assert get_agent("nao-existe") is None


def test_repo_inspecting_loops_ship_with_a_default_task():
    """Loops that do not depend on a user request are seeded with `default_prompt`."""
    workflows = {item.id: item for item in list_workflows()}

    assert workflows["analyze-codebase"].default_prompt == "Mapear codebase existente"
    assert workflows["setup-project"].default_prompt == "Novo projeto"
    assert workflows["new-issue"].default_prompt == ""
    assert workflows["quick-fix"].default_prompt == ""
    assert workflows["default"].default_prompt == ""


def test_db_seeded_before_the_column_gets_the_task_on_migration(tmp_path: Path):
    """Existing users must not keep seeing the text field.

    `ALTER` gives `''` to existing rows and seeding does not rerun on a seeded
    database, so the backfill closes that gap.
    """
    import sqlite3

    db_path = tmp_path / "antigo.db"
    connect(db_path).close()

    raw = sqlite3.connect(str(db_path))
    raw.execute("ALTER TABLE workflow_defs DROP COLUMN default_prompt")
    # A database from before the column also predates the schema version.
    raw.execute("PRAGMA user_version = 0")
    raw.commit()
    raw.close()

    connect(db_path).close()

    workflows = {item.id: item for item in list_workflows(db_path=db_path)}
    assert workflows["analyze-codebase"].default_prompt == "Mapear codebase existente"
    assert workflows["setup-project"].default_prompt == "Novo projeto"


def test_backfill_does_not_undo_user_edits(tmp_path: Path):
    from pulse.store import factory

    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE workflow_defs SET default_prompt = ? WHERE id = ?",
        ("Do meu jeito", "analyze-codebase"),
    )
    factory.backfill_default_prompts(connection)
    connection.commit()
    connection.close()

    workflows = {item.id: item for item in list_workflows(db_path=db_path)}
    assert workflows["analyze-codebase"].default_prompt == "Do meu jeito"


def test_unattended_loops_do_not_ask_for_approval():
    """Codebase analysis and project setup run from start to finish.

    They do not depend on a user request and none of their steps require approval.
    """
    workflows = {item.id: item for item in list_workflows()}

    for workflow_id in ("analyze-codebase", "setup-project"):
        approving = [
            step.step_id for step in workflows[workflow_id].steps if step.requires_approval
        ]
        assert approving == [], f"{workflow_id} still stops for approval at {approving}"

    for workflow_id, step_id in (
        ("analyze-codebase", "codebase-explore"),
        ("setup-project", "setup-interview"),
    ):
        step = next(s for s in workflows[workflow_id].steps if s.step_id == step_id)
        assert "Aprovar {{step_label}}" not in step.prompt_template

    assert [step.requires_approval for step in workflows["new-issue"].steps] == [
        True,
        True,
        True,
        False,
        True,
        False,
        True,
        False,
    ]


def test_old_db_drops_the_approval_request_on_open(tmp_path: Path):
    """Existing users keep the old row in the database, and `seed` does not rewrite it."""
    from pulse.store import factory

    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.executemany(
        """
        UPDATE workflow_steps
           SET requires_approval = 1, prompt_template = prompt_template || ?
         WHERE workflow_id = ? AND step_id = ?
        """,
        [
            (f"\n\n1. {factory.APPROVAL_MARK}\n", workflow_id, step_id)
            for workflow_id, step_id in factory.UNATTENDED_STEPS
        ],
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    workflows = {item.id: item for item in list_workflows(db_path=db_path)}
    for workflow_id, step_id in factory.UNATTENDED_STEPS:
        step = next(s for s in workflows[workflow_id].steps if s.step_id == step_id)
        assert step.requires_approval is False
        assert factory.APPROVAL_MARK not in step.prompt_template


def test_user_rewritten_template_is_not_touched(tmp_path: Path):
    """Without the factory block the row belongs to the user; the migration leaves it alone."""
    from pulse.store import factory

    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        """
        UPDATE workflow_steps SET prompt_template = ?
         WHERE workflow_id = 'analyze-codebase' AND step_id = 'codebase-explore'
        """,
        ("Explore do meu jeito.",),
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    workflows = {item.id: item for item in list_workflows(db_path=db_path)}
    step = next(s for s in workflows["analyze-codebase"].steps if s.step_id == "codebase-explore")
    assert step.prompt_template == "Explore do meu jeito."
    assert factory.APPROVAL_MARK


def test_seeded_db_gains_the_merge_phase_on_open(tmp_path: Path):
    """The merge layer must reach users who already have a database.

    `seed` is `INSERT OR IGNORE` and does not run on a seeded database; `is_seeded`
    counts factory ids and fails when the factory gains rows. Without it, new
    factory agents would only reach fresh installs.
    """

    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.execute("DELETE FROM workflow_steps WHERE step_id IN ('review', 'review-fix')")
    connection.execute("DELETE FROM agent_defs WHERE id IN ('review', 'review-fix')")
    connection.execute(
        """
        UPDATE workflow_steps SET prompt_template = ?
         WHERE workflow_id = 'new-issue' AND step_id = 'prd'
        """,
        ("PRD do meu jeito.",),
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    workflows = {item.id: item for item in list_workflows(db_path=db_path)}
    steps = {step.step_id: step for step in workflows["new-issue"].steps}
    assert (steps["review"].position, steps["review-fix"].position) == (7, 8)
    assert steps["review"].requires_approval is True
    assert steps["review-fix"].requires_approval is False
    assert get_agent("review", db_path=db_path) is not None
    assert get_agent("review-fix", db_path=db_path) is not None
    assert steps["prd"].prompt_template == "PRD do meu jeito."


def test_seeded_db_gains_the_verify_loop_before_review_on_open(tmp_path: Path):
    """A database seeded before `verify` existed must run its loop between implement and review.

    Inserting the steps at their factory positions would tie them with `review`,
    and `ORDER BY position, step_id` would then run them after the fix loop.
    """
    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.execute("DELETE FROM workflow_steps WHERE step_id IN ('verify', 'verify-fix')")
    connection.execute("DELETE FROM agent_defs WHERE id = 'verify'")
    connection.execute(
        "UPDATE workflow_steps SET position = position - 2 "
        "WHERE workflow_id = 'new-issue' AND step_id IN ('review', 'review-fix')"
    )
    connection.execute(
        "UPDATE workflow_steps SET label = 'Meu review' "
        "WHERE workflow_id = 'new-issue' AND step_id = 'review'"
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    workflow = get_workflow("new-issue", db_path=db_path)
    assert workflow is not None
    assert [(step.step_id, step.position) for step in workflow.steps[3:]] == [
        ("implement", 4),
        ("verify", 5),
        ("verify-fix", 6),
        ("review", 7),
        ("review-fix", 8),
    ]
    assert workflow.steps[4].requires_approval is True
    assert workflow.steps[6].label == "Meu review"
    assert get_agent("verify", db_path=db_path) is not None


VALIDATION_IN_IMPLEMENT = "### 9. Feature-level validation (after the LAST task)"


def test_feature_validation_runs_in_its_own_step_not_in_the_last_task():
    """Each implement item is one task; the feature check needs a session that wrote none.

    With the playbook in `implement`, whichever fan-out item finished last also
    judged the whole feature, so the author was the verifier.
    """
    implement = get_agent("implement")
    verify = get_agent("verify")

    assert implement is not None
    assert verify is not None
    assert VALIDATION_IN_IMPLEMENT not in implement.instructions
    assert "# validate.md" not in implement.instructions
    assert "validation.md" in verify.instructions
    assert "Spec-Anchored Acceptance Criteria" in verify.instructions


def test_old_db_implement_drops_the_last_task_validation_on_open(tmp_path: Path):
    """`seed` never rewrites `agent_defs`, so old rows would keep validating in the last task."""
    db_path = tmp_path / "antigo.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE agent_defs SET instructions = instructions || ? WHERE id = 'implement'",
        (f"\n\n{VALIDATION_IN_IMPLEMENT}\n\nDispatch a fresh Verifier.\n",),
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    implement = get_agent("implement", db_path=db_path)
    assert implement is not None
    assert VALIDATION_IN_IMPLEMENT not in implement.instructions
    assert implement.instructions == get_agent("implement").instructions


def test_user_rewritten_implement_instructions_are_not_touched(tmp_path: Path):
    """Without the factory section the row belongs to the user."""
    db_path = tmp_path / "editado.db"
    connection = connect(db_path)
    connection.execute(
        "UPDATE agent_defs SET instructions = 'Implemente do meu jeito.' WHERE id = 'implement'"
    )
    connection.commit()
    connection.close()

    connect(db_path).close()

    implement = get_agent("implement", db_path=db_path)
    assert implement is not None
    assert implement.instructions == "Implemente do meu jeito."


def test_artifact_writers_do_not_run_with_deny_writes():
    """`deny_writes` rejects `write`/`edit` regardless of the path.

    The review phase exists to produce `reviews/round-NNN.md`; under the spec
    phases' policy the file would never reach disk or the artifacts pane. As
    [pulse.replies.permission] states, a step that writes is `ask` or `auto_approve`.
    """
    from pulse.replies.permission import decide_permission

    params = {
        "toolCall": {"kind": "write"},
        "options": [
            {"optionId": "allow-once", "kind": "allow_once"},
            {"optionId": "reject-once", "kind": "reject_once"},
        ],
    }

    for agent_id in ("verify", "review", "review-fix"):
        agent = get_agent(agent_id)
        assert agent is not None
        assert decide_permission(params, policy=agent.permission_policy) != {
            "outcome": {"outcome": "selected", "optionId": "reject-once"}
        }, f"{agent_id} cannot write what its phase exists to produce"


def test_only_review_offers_skip():
    """Skipping a spec is out of scope: PRD/Techspec/Tasks keep three options.

    Label and engine must agree: `classify_outcome` maps the choice to `skipped`
    by substring, so a label without "Pular" would promise what the engine won't do.
    """
    from pulse.replies.approval import ApprovalOutcome, classify_outcome

    workflows = {item.id: item for item in list_workflows()}
    offering = [
        step.step_id
        for workflow in workflows.values()
        for step in workflow.steps
        if step.requires_approval and "Pular" in step.prompt_template
    ]

    assert offering == ["review", "review"]

    step = next(s for s in workflows["new-issue"].steps if s.step_id == "review")
    option = next(
        line.strip() for line in step.prompt_template.splitlines() if line.strip().startswith("C)")
    )
    assert classify_outcome(f"→ {option}") == ApprovalOutcome.SKIP


def test_merge_layer_is_a_capped_loop():
    """Review, fix, review again until nothing else is requested.

    The cap matches the playbook's convergence contract (round 3 closes, round 4
    does not exist); otherwise the engine would stop where the text promises to go on.
    """
    steps = {step.step_id: step for step in get_workflow("new-issue").steps}

    assert steps["review-fix"].repeat == RepeatRule(back_to="review", max_rounds=3)
    assert steps["review"].position < steps["review-fix"].position
    repeating = [
        step.step_id for workflow in list_workflows() for step in workflow.steps if step.repeat
    ]
    assert repeating == ["verify-fix", "review-fix", "review-fix"]

    for workflow_id in ("new-issue", "review"):
        steps = {step.step_id: step for step in get_workflow(workflow_id).steps}
        assert steps["review-fix"].repeat == RepeatRule(back_to="review", max_rounds=3)
        assert "repeats" in steps["review"].prompt_template.lower()
        assert "next: repeat" in steps["review-fix"].prompt_template
        assert "next: close" in steps["review"].prompt_template
        assert "next: close" not in steps["review-fix"].prompt_template


def test_feature_layer_is_a_capped_loop_fixed_with_the_implement_playbook():
    """Verify, fix its gaps, verify again — the fix never judges its own repair.

    The fix reuses `implement` (unit tests, surgical changes) in its own phase,
    so a gap is repaired by the same playbook that should have avoided it.
    """
    workflow = get_workflow("new-issue")
    assert workflow is not None
    steps = {step.step_id: step for step in workflow.steps}
    fix = steps["verify-fix"]

    assert [step.step_id for step in workflow.steps][4:] == [
        "verify",
        "verify-fix",
        "review",
        "review-fix",
    ]
    assert fix.repeat == RepeatRule(back_to="verify", max_rounds=3)
    assert (fix.agent_id, fix.requires_approval, fix.commit_type) == ("implement", False, "fix")
    assert steps["implement"].opens_request is True
    assert steps["verify"].opens_request is False
    assert "validation.md" in fix.prompt_template
    assert "next: repeat" in fix.prompt_template
    assert "next: close" not in fix.prompt_template
    assert "next: close" in steps["verify"].prompt_template
    assert "`accepted`" in steps["verify"].prompt_template, "B can accept gaps without a fix"


def test_verify_counts_rounds_from_this_runs_files_not_from_fixed_entries():
    """A fix pass that repairs nothing marks no entry `fixed`.

    Keying the round on a `fixed` entry made that pass look like round 1, so
    verify rewrote `validation.md` from scratch and reopened accepted gaps.
    """
    verify = {step.step_id: step for step in get_workflow("new-issue").steps}["verify"]

    assert "`validation.md` is not in the list of files this run" in verify.prompt_template
    assert "`validation.md` is in that list → round N+1" in verify.prompt_template
    assert "no fix plan in it with `**Status**: fixed` → round 1" not in verify.prompt_template


def test_verify_may_mutate_only_its_scratch_copy():
    """The approval include forbids edits outside `.pulse/specs/`, yet the sensor injects faults.

    Without a named exception an agent obeying the FORBIDDEN list skips the
    sensor and reports a fallback on every run.
    """
    verify = {step.step_id: step for step in get_workflow("new-issue").steps}["verify"]
    agent = get_agent("verify")

    assert agent is not None
    assert "the one exception to the FORBIDDEN list" in verify.prompt_template
    assert "git worktree remove --force <scratch>" in agent.instructions


def test_review_starts_from_what_verify_left_open():
    """Gaps the verify loop did not close must reach the merge layer, not vanish."""
    new_issue = {step.step_id: step for step in get_workflow("new-issue").steps}
    standalone = {step.step_id: step for step in get_workflow("review").steps}

    assert "still\n`**Status**: open`" in new_issue["review"].prompt_template
    assert "**Status**: open" not in standalone["review"].prompt_template


def _looping_workflow(repeat: RepeatRule | None) -> WorkflowDef:
    save_agent(AgentDef(id="tester", label="Tester"))
    return WorkflowDef(
        id="looping",
        label="Looping",
        steps=tuple(
            StepDef(
                workflow_id="looping",
                step_id=step_id,
                position=position,
                label=step_id,
                agent_id="tester",
                prompt_template="{{user_prompt}}",
                requires_approval=False,
                repeat=repeat if step_id == "fix" else None,
            )
            for position, step_id in enumerate(("review", "fix"), start=1)
        ),
    )


def test_a_repeat_rule_survives_a_save_and_a_load():
    """The rule is two columns in SQLite and one value in the definition."""
    rule = RepeatRule(back_to="review", max_rounds=3)
    save_workflow(_looping_workflow(rule))

    loaded = get_workflow("looping")

    assert loaded is not None
    assert [step.repeat for step in loaded.steps] == [None, rule]


def test_a_stored_rule_that_cannot_loop_loads_as_no_loop():
    """A hand-edited `repeat_max` below two used to be ignored by the engine; it still is."""

    save_workflow(_looping_workflow(RepeatRule(back_to="review", max_rounds=3)))
    connection = connect(default_db_path())
    connection.execute(
        "UPDATE workflow_steps SET repeat_max = 1 WHERE workflow_id = ? AND step_id = ?",
        ("looping", "fix"),
    )
    connection.commit()
    connection.close()

    loaded = get_workflow("looping")

    assert loaded is not None
    assert [step.repeat for step in loaded.steps] == [None, None]
    assert loaded.loops() == {}
