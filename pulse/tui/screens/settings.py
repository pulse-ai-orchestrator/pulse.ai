from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.worker import Worker, get_current_worker

from pulse.domain.git_options import GitOptions
from pulse.tui import engine, strings
from pulse.tui.engine import AgentField, EngineError, Fields, ProjectSettings
from pulse.tui.key_hints import key_line
from pulse.tui.menu_rows import MenuRow, breadcrumb
from pulse.tui.settings_rows import (
    Toggle,
    Tone,
    check_line,
    feedback,
    toggle_state,
    toggle_value,
)
from pulse.tui.widgets.menu_list import MenuList

# The field row each picker edits, so leaving a picker lands back on its row.
_PICKER_FIELD = {"pick_agent": "agent", "pick_model": "model", "pick_permission": "permission"}
_Place = tuple[str, str, str | None]
_FIELD_TITLES = {
    "agent": strings.SETTINGS_FIELD_RUNTIME,
    "model": strings.SETTINGS_FIELD_MODEL,
    "permission": strings.SETTINGS_FIELD_PERMISSIONS,
}


def _git_rows(settings: ProjectSettings) -> list[MenuRow]:
    chain = GitOptions.chained(
        use_worktree=settings.use_worktree,
        atomic_commits=settings.atomic_commits,
        auto_pull_request=settings.auto_pull_request,
    )
    pull_request_available = chain.use_worktree and chain.atomic_commits
    return [
        _toggle_row(
            "worktree",
            strings.SETTINGS_WORKTREE_LABEL,
            toggle_state(settings.use_worktree, available=True),
            strings.SETTINGS_WORKTREE_DESCRIPTION,
        ),
        _toggle_row(
            "atomic",
            strings.SETTINGS_ATOMIC_LABEL,
            toggle_state(settings.atomic_commits, available=True),
            strings.SETTINGS_ATOMIC_DESCRIPTION,
        ),
        _toggle_row(
            "pull_request",
            strings.SETTINGS_PR_LABEL,
            toggle_state(settings.auto_pull_request, available=pull_request_available),
            strings.SETTINGS_PR_DESCRIPTION
            if pull_request_available
            else strings.SETTINGS_PR_NEEDS_COMMITS,
        ),
    ]


def _toggle_row(option_id: str, label: str, state: Toggle, description: str) -> MenuRow:
    return MenuRow(
        option_id,
        label,
        toggle_value(state),
        description,
        muted=state is Toggle.UNAVAILABLE,
    )


class SettingsScreen(Screen[None]):
    BINDINGS = [
        ("escape", "go_back", strings.BACK),
        ("q", "go_back", strings.BACK),
        ("b", "go_back", strings.BACK),
        # Agent CLIs flip a setting with space as well as Enter.
        Binding("space", "select", show=False),
    ]

    def __init__(self, *, cwd: Path | None = None) -> None:
        super().__init__()
        self._cwd = (cwd or Path.cwd()).resolve()
        self._mode = "root"
        self._workflow_id: str | None = None
        self._target = "agent"
        self._settings: ProjectSettings | None = None
        self._trail: tuple[str, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-content"):
            yield Static(id="settings-header")
            yield Static("", id="settings-status")
            yield MenuList(id="settings-options")
            yield Static("", id="settings-report")
        yield Static(id="settings-keys")

    def on_mount(self) -> None:
        self._set_report("")
        self._show_root()

    def action_go_back(self) -> None:
        if self._mode == "root":
            self.app.pop_screen()
            return
        try:
            self._show_previous_menu()
        except EngineError as error:
            self._set_report(error.describe(), Tone.ERROR)

    def action_select(self) -> None:
        self.query_one("#settings-options", OptionList).action_select()

    def _show_previous_menu(self) -> None:
        field = _PICKER_FIELD.get(self._mode)
        if field is not None:
            if self._target == "global":
                self._show_global_fields(focus=f"g_{field}")
                return
            if self._workflow_id:
                self._show_workflow_fields(focus=f"wf_{field}")
                return
        if self._mode == "workflow_fields":
            self._show_pulse_agents(focus=f"workflow:{self._workflow_id}")
            return
        focus = {"global_fields": "global", "pick_workflow": "agents", "doctor": "doctor"}
        self._show_root(focus=focus.get(self._mode))

    def _show_view(self, trail: tuple[str, ...], hint: str) -> None:
        self._trail = trail
        header = breadcrumb(strings.SETTINGS_TITLE, trail, self._cwd.name)
        self.query_one("#settings-header", Static).update(header)
        self._set_status(hint)
        keys = strings.SETTINGS_KEYS_ROOT if not trail else strings.SETTINGS_KEYS_MENU
        self.query_one("#settings-keys", Static).update(key_line(keys))

    def _set_status(self, text: str) -> None:
        self.query_one("#settings-status", Static).update(Text(text))

    def _set_report(self, text: str | Text, tone: Tone = Tone.NOTE) -> None:
        widget = self.query_one("#settings-report", Static)
        widget.update(text if isinstance(text, Text) else feedback(text, tone))
        widget.display = bool(text)

    def _set_rows(self, rows: list[MenuRow], *, focus: str | None = None) -> None:
        widget = self.query_one("#settings-options", MenuList)
        widget.show_rows(rows, focus=focus)
        if rows:
            widget.focus()

    def _show_root(self, *, focus: str | None = None) -> None:
        self._mode = "root"
        self._workflow_id = None
        self._set_report("")
        self._show_view((), strings.SETTINGS_ROOT_HINT)
        try:
            settings = self._load()
        except EngineError as error:
            self._set_report(error.describe(), Tone.ERROR)
            self._set_rows([MenuRow("back", strings.BACK_ARROW)])
            return
        defaults = settings.defaults
        rows = [
            MenuRow(
                "global",
                strings.SETTINGS_GLOBAL_LABEL,
                strings.SETTINGS_AGENT_VALUE.format(runtime=defaults.runtime, model=defaults.model),
                strings.SETTINGS_GLOBAL_DESCRIPTION,
            ),
            MenuRow(
                "agents",
                strings.SETTINGS_AGENTS_LABEL,
                strings.SETTINGS_AGENTS_COUNT.format(count=len(settings.agents)),
                strings.SETTINGS_AGENTS_DESCRIPTION,
            ),
        ]
        if settings.is_repo:
            rows.extend(_git_rows(settings))
        rows.append(
            MenuRow(
                "doctor", strings.SETTINGS_DOCTOR_LABEL, "", strings.SETTINGS_DOCTOR_DESCRIPTION
            )
        )
        self._set_rows(rows, focus=focus)

    def _load(self) -> ProjectSettings:
        """The project's settings as the daemon resolves them; reread after every write."""
        self._settings = engine.project_settings(self._cwd)
        return self._settings

    def _current(self) -> ProjectSettings:
        return self._settings if self._settings is not None else self._load()

    def _toggle_atomic(self) -> None:
        enabled = not self._current().atomic_commits
        engine.set_atomic_commits(self._cwd, enabled=enabled)
        self._show_root()
        self._set_report(
            strings.SETTINGS_ATOMIC_ENABLED if enabled else strings.SETTINGS_ATOMIC_DISABLED,
            Tone.DONE,
        )

    def _toggle_pull_request(self) -> None:
        current = self._current()
        if not current.use_worktree or not current.atomic_commits:
            self._set_report(strings.SETTINGS_PR_NEEDS_COMMITS)
            return
        enabled = not current.auto_pull_request
        engine.set_pull_request(self._cwd, enabled=enabled)
        self._show_root()
        self._set_report(
            strings.SETTINGS_PR_ENABLED if enabled else strings.SETTINGS_PR_DISABLED, Tone.DONE
        )

    def _toggle_worktree(self) -> None:
        enabled = not self._current().use_worktree
        engine.set_worktree(self._cwd, enabled=enabled)
        self._show_root()
        self._set_report(
            strings.SETTINGS_WORKTREE_ENABLED if enabled else strings.SETTINGS_WORKTREE_DISABLED,
            Tone.DONE,
        )

    @on(OptionList.OptionSelected, "#settings-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option_id or "")
        if option_id == "back":
            self.action_go_back()
            return
        action, separator, value = option_id.partition(":")
        route = self._option_routes().get((self._mode, action + separator))
        if route is None:
            return
        try:
            route(value)
        except EngineError as error:
            self._set_report(error.describe(), Tone.ERROR)

    def _option_routes(self) -> dict[tuple[str, str], Callable[[str], object]]:
        """What each option does, keyed by the menu showing it and its id.

        Pick options carry their value after the `:` (`model:<name>`); the
        route receives that value, the other routes ignore it.
        """
        open_fields: dict[str, Callable[[str], object]] = {
            "agent": lambda _: self._show_agents(),
            "model": lambda _: self._open_models(),
            "permission": lambda _: self._show_permissions(),
        }
        return {
            ("root", "global"): lambda _: self._show_global_fields(),
            ("root", "agents"): lambda _: self._show_pulse_agents(),
            ("root", "worktree"): lambda _: self._toggle_worktree(),
            ("root", "atomic"): lambda _: self._toggle_atomic(),
            ("root", "pull_request"): lambda _: self._toggle_pull_request(),
            ("root", "doctor"): lambda _: self._run_doctor(),
            **{("global_fields", f"g_{field}"): route for field, route in open_fields.items()},
            **{("workflow_fields", f"wf_{field}"): route for field, route in open_fields.items()},
            ("pick_model", "model:"): self._save_model,
            ("pick_permission", "policy:"): self._save_permission,
            ("pick_workflow", "workflow:"): self._show_agent_fields,
            ("pick_agent", "agent:"): self._save_workflow_agent,
        }

    def _show_agent_fields(self, agent_id: str) -> None:
        self._workflow_id = agent_id
        self._show_workflow_fields()

    def _open_models(self) -> None:
        self._set_status(strings.SETTINGS_LOADING_MODELS)
        self._load_models(self._current_fields().runtime, self._place())

    @work(thread=True, exclusive=True, group="models")
    def _load_models(self, runtime: str, place: _Place) -> None:
        worker = get_current_worker()
        try:
            models = engine.models(self._cwd, runtime)
        except EngineError as error:
            message = error.describe()
            self._apply_if_current(worker, place, lambda: self._set_report(message, Tone.ERROR))
            return

        def apply() -> None:
            self._mode = "pick_model"
            current = self._current_fields().model
            self._show_picker("model", strings.SETTINGS_PICK_MODEL)
            self._set_rows(
                [MenuRow(f"model:{item}", item, current=item == current) for item in models]
            )

        self._apply_if_current(worker, place, apply)

    def _place(self) -> _Place:
        return (self._mode, self._target, self._workflow_id)

    def _apply_if_current(
        self, worker: Worker[None], place: _Place, apply: Callable[[], None]
    ) -> None:
        def guarded() -> None:
            if worker.is_cancelled or not self.is_mounted or self._place() != place:
                return
            apply()

        with contextlib.suppress(RuntimeError):
            self.app.call_from_thread(guarded)

    def _show_permissions(self) -> None:
        self._mode = "pick_permission"
        current = self._current_fields().permission_policy
        self._show_picker("permission", strings.SETTINGS_PICK_POLICY)
        self._set_rows(
            [
                MenuRow(
                    f"policy:{key}",
                    strings.PERMISSION_LABELS.get(key, key),
                    current=key == current,
                )
                for key in self._current().permission_policies
            ]
        )

    def _show_picker(self, field: str, hint: str) -> None:
        self._set_report("")
        self._show_view((*self._fields_trail(), _FIELD_TITLES[field]), hint)

    def _fields_trail(self) -> tuple[str, ...]:
        if self._target == "global":
            return (strings.SETTINGS_GLOBAL_LABEL,)
        return (strings.SETTINGS_AGENTS_LABEL, self._agent_label())

    def _show_global_fields(self, *, focus: str | None = None) -> None:
        """Settings that apply to every agent."""
        engine.open_project(self._cwd)
        self._target = "global"
        self._workflow_id = None
        self._mode = "global_fields"
        defaults = self._load().defaults
        self._set_report("")
        self._show_view(self._fields_trail(), strings.SETTINGS_GLOBAL_HINT)
        self._set_rows(_field_rows("g", defaults), focus=focus)

    def _show_pulse_agents(self, *, focus: str | None = None) -> None:
        engine.open_project(self._cwd)
        self._target = "agent"
        self._mode = "pick_workflow"
        self._set_report("")
        self._show_view((strings.SETTINGS_AGENTS_LABEL,), strings.SETTINGS_PICK_AGENT)
        self._set_rows(
            [
                MenuRow(
                    f"workflow:{agent.id}",
                    agent.label,
                    strings.SETTINGS_AGENT_VALUE.format(
                        runtime=agent.fields.runtime, model=agent.fields.model
                    ),
                )
                for agent in self._load().agents
            ],
            focus=focus,
        )

    def _show_workflow_fields(self, *, focus: str | None = None) -> None:
        self._mode = "workflow_fields"
        self._load()
        self._set_report("")
        self._show_view(self._fields_trail(), strings.SETTINGS_AGENT_HINT)
        self._set_rows(_field_rows("wf", self._current_fields()), focus=focus)

    def _agent_label(self) -> str:
        agent = self._current().agent(self._workflow_id or "")
        return agent.label if agent is not None else (self._workflow_id or strings.AGENT)

    def _current_fields(self) -> Fields:
        """Runtime, model and policy of the target being edited."""
        settings = self._current()
        if self._target == "global":
            return settings.defaults
        agent = settings.agent(self._workflow_id or "")
        return agent.fields if agent is not None else Fields("", "", "")

    def _save(self, field: AgentField, value: str) -> None:
        """Write the picked value for the target being edited, then show its fields again."""
        row = _PICKER_FIELD[self._mode]
        if self._target == "global":
            engine.save_default(self._cwd, field, value)
            self._show_global_fields(focus=f"g_{row}")
            return
        if not self._workflow_id:
            self._show_root()
            return
        engine.save_agent_field(self._cwd, self._workflow_id, field, value)
        self._show_workflow_fields(focus=f"wf_{row}")

    def _show_agents(self) -> None:
        self._mode = "pick_agent"
        current = self._current_fields().runtime
        self._show_picker("agent", strings.SETTINGS_PICK_RUNTIME)
        self._set_rows(
            [
                MenuRow(f"agent:{name}", name, binary, current=name == current)
                for name, binary in self._current().runtimes
            ]
        )

    def _save_model(self, model: str) -> None:
        self._save("model", model)

    def _save_permission(self, policy: str) -> None:
        self._save("permission_policy", policy)

    def _save_workflow_agent(self, runtime: str) -> None:
        self._save("runtime", runtime)

    def _run_doctor(self) -> None:
        self._mode = "doctor"
        self._show_view((strings.ENVIRONMENT,), strings.SETTINGS_LOADING_DOCTOR)
        self._set_report("")
        self._set_rows([MenuRow("back", strings.BACK_ARROW)])
        self._load_doctor(self._place())

    @work(thread=True, exclusive=True, group="doctor")
    def _load_doctor(self, place: _Place) -> None:
        worker = get_current_worker()
        try:
            checks = engine.doctor_checks()
            config = engine.config(self._cwd)
        except EngineError as error:
            message = error.describe()
            self._apply_if_current(worker, place, lambda: self._set_report(message, Tone.ERROR))
            return

        lines = [check_line(check.status, check.message) for check in checks]
        machine = config.get("global")
        if machine:
            lines.append(
                check_line(
                    "ok", strings.SETTINGS_DOCTOR_GLOBAL_CONFIG.format(model=machine.get("model"))
                )
            )
        project = config.get("project")
        if project:
            lines.append(
                check_line(
                    "ok",
                    strings.SETTINGS_DOCTOR_PROJECT_CONFIG.format(
                        source=project.get("source_file")
                    ),
                )
            )

        report: str | Text = Text("\n").join(lines) if lines else strings.SETTINGS_DOCTOR_NO_CHECKS

        def apply() -> None:
            self._set_status(strings.SETTINGS_DOCTOR_HINT)
            self._set_report(report)

        self._apply_if_current(worker, place, apply)


def _field_rows(prefix: str, fields: Fields) -> list[MenuRow]:
    """Runtime, model and policy rows of a settings target, ids prefixed by `prefix`."""
    policy = fields.permission_policy
    return [
        MenuRow(f"{prefix}_agent", strings.SETTINGS_FIELD_RUNTIME, fields.runtime),
        MenuRow(f"{prefix}_model", strings.SETTINGS_FIELD_MODEL, fields.model),
        MenuRow(
            f"{prefix}_permission",
            strings.SETTINGS_FIELD_PERMISSIONS,
            strings.PERMISSION_LABELS.get(policy, policy),
        ),
    ]
