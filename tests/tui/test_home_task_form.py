"""The run form on the home screen: title, a slug that follows it, description, git options."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Input, OptionList, Static

import pulse.tui.screens.home as home_module
from pulse.client.protocol import RunForm
from pulse.tui import strings
from pulse.tui.engine import WorkspaceFiles
from pulse.tui.screens.home import HomeScreen
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.file_mention import FileMentionList
from pulse.tui.widgets.task_composer import TaskComposer
from tests.conftest import onboard_machine
from tests.tui.conftest import wait_until

# Mirrors the cap in `home_theme.py`: past it the box scrolls instead of
# pushing the git options and the hint off a 24-row terminal.
DESCRIPTION_MAX_ROWS = 10
DESCRIPTION_MIN_ROWS = 3


class _Harness(App[None]):
    CSS = COCKPIT_CSS

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[tuple[str, str, str, RunForm | None]] = []

    def compose(self) -> ComposeResult:
        yield Static("ok")

    def open_cockpit(
        self, workflow_id: str, prompt: str, *, branch: str = "", form: RunForm | None = None
    ) -> None:
        self.opened.append((workflow_id, prompt, branch, form))


def _project(monkeypatch, *, is_repo=True, worktree=True, commits=True, pull_request=False):
    monkeypatch.setattr(
        home_module.engine,
        "project_settings",
        lambda _path: SimpleNamespace(
            is_repo=is_repo,
            use_worktree=worktree,
            atomic_commits=commits,
            auto_pull_request=pull_request,
        ),
    )


@pytest.fixture
def free_branch(monkeypatch) -> list[str]:
    checked: list[str] = []

    def _check(_workspace, name):
        checked.append(name)
        return True, False

    monkeypatch.setattr(home_module.engine, "branch_check", _check)
    return checked


async def _open_form(app: _Harness, pilot, *, detailed: bool) -> HomeScreen:
    screen = HomeScreen()
    app.push_screen(screen)
    await pilot.pause()
    screen.on_option_selected(SimpleNamespace(option_id="session"))
    screen.on_option_selected(SimpleNamespace(option_id="workflow:quick-fix"))
    await pilot.pause()
    if detailed:
        await pilot.press("ctrl+o")
        await pilot.pause()
    return screen


async def _type(pilot, text: str) -> None:
    await pilot.press(*("space" if char == " " else char for char in text))


def _checked(screen: HomeScreen) -> tuple[bool, bool, bool]:
    return tuple(  # type: ignore[return-value]  # three ids, three flags
        screen.query_one(f"#git-{name}", Checkbox).value
        for name in ("use-worktree", "atomic-commits", "auto-pull-request")
    )


def _heading(screen: HomeScreen) -> list[str]:
    """The form's breadcrumb levels, without the workspace that follows them."""
    shown = str(screen.query_one("#task-heading", Static).render())
    return shown.split("  ·  ")[0].split(" › ")


def _run(test, *, detailed: bool = True) -> None:
    onboard_machine()

    async def body() -> None:
        app = _Harness()
        async with app.run_test(size=(80, 24)) as pilot:
            await test(app, pilot, await _open_form(app, pilot, detailed=detailed))

    asyncio.run(body())


def test_the_form_opens_as_a_plain_description_in_the_menu_place(monkeypatch):
    """By default the task is one description, as before the form had fields."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        assert screen.query_one("#home-options", OptionList).display is False
        assert screen.query_one(".home-brand", Static).display is False
        assert _heading(screen) == ["Nova sessão", "Correção rápida"]
        assert screen.query_one("#task-description", TaskComposer).has_focus
        for field in ("#task-title-box", "#task-slug-row", "#task-git-row"):
            assert screen.query_one(field).display is False, field

        await pilot.press("escape")
        await pilot.pause()
        assert screen.query_one("#task-form").display is False
        assert screen.query_one("#home-options", OptionList).has_focus

    _run(test, detailed=False)


def test_a_plain_description_starts_the_run_on_the_project_options(monkeypatch, free_branch):
    """No title, no form: the daemon applies the project's git options, as it always did."""
    _project(monkeypatch, worktree=False, commits=False)

    async def test(app, pilot, _screen) -> None:
        await _type(pilot, "exportar relatório")
        await pilot.press("enter")
        await pilot.pause()

        assert app.opened == [("quick-fix", "exportar relatório", "", None)]
        assert free_branch == []

    _run(test, detailed=False)


def test_a_blank_plain_description_keeps_the_box_open(monkeypatch):
    _project(monkeypatch)

    async def test(app, pilot, screen) -> None:
        await pilot.press("space", "enter")
        await pilot.pause()

        assert app.opened == []
        assert screen.query_one("#task-form").display is True

    _run(test, detailed=False)


def test_ctrl_o_reveals_the_fields_and_keeps_what_was_typed(monkeypatch):
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await _type(pilot, "detalhes")
        await pilot.press("ctrl+o")
        await pilot.pause()

        assert screen.query_one("#task-title", Input).has_focus
        assert screen.query_one("#task-git-row").display is True
        assert screen.query_one("#task-description", TaskComposer).text == "detalhes"

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert screen.query_one("#task-title-box").display is False
        assert screen.query_one("#task-description", TaskComposer).has_focus

    _run(test, detailed=False)


def test_the_chosen_mode_is_kept_for_the_next_task(monkeypatch):
    """Whoever wants the fields opens them once, not on every run."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await pilot.press("escape")
        screen.on_option_selected(SimpleNamespace(option_id="workflow:new-issue"))
        await pilot.pause()

        assert screen.query_one("#task-title", Input).has_focus
        assert screen.query_one("#task-git-row").display is True

    _run(test)


def test_the_slug_follows_the_title_until_the_user_edits_it(monkeypatch):
    """Typing the title names the branch; a slug the user wrote is never overwritten."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        slug = screen.query_one("#task-slug", Input)
        await _type(pilot, "Corrigir Login Já")
        await pilot.pause()
        assert slug.value == "corrigir-login-ja"

        slug.value = "fix-login"
        await pilot.pause()
        screen.query_one("#task-title", Input).focus()
        await _type(pilot, " agora")
        await pilot.pause()
        assert slug.value == "fix-login"

        slug.value = ""
        await pilot.pause()
        screen.query_one("#task-title", Input).focus()
        await _type(pilot, "!")
        await pilot.pause()
        assert slug.value == "corrigir-login-ja-agora"

    _run(test)


def test_enter_on_the_title_moves_on_instead_of_starting_the_run(monkeypatch):
    _project(monkeypatch)

    async def test(app, pilot, screen) -> None:
        await _type(pilot, "Corrigir login")
        await pilot.press("enter")
        await pilot.pause()

        assert app.opened == []
        assert screen.query_one("#task-slug", Input).has_focus

    _run(test)


def test_the_git_options_start_from_the_project_and_carry_their_chain(monkeypatch):
    """Switching a pull request on needs commits and a branch; switching the branch off
    leaves nothing to publish but keeps the commits.
    """
    _project(monkeypatch, worktree=False, commits=False)

    async def test(_app, pilot, screen) -> None:
        assert _checked(screen) == (False, False, False)

        screen.query_one("#git-auto-pull-request", Checkbox).toggle()
        await pilot.pause()
        assert _checked(screen) == (True, True, True)

        screen.query_one("#git-use-worktree", Checkbox).toggle()
        await pilot.pause()
        assert _checked(screen) == (False, True, False)

    _run(test)


def test_switching_commits_on_in_the_form_leaves_the_worktree_off(monkeypatch):
    """Autocommit stands alone: it commits on the project's branch without a worktree."""
    _project(monkeypatch, worktree=False, commits=False)

    async def test(_app, pilot, screen) -> None:
        screen.query_one("#git-atomic-commits", Checkbox).toggle()
        await pilot.pause()

        assert _checked(screen) == (False, True, False)

    _run(test)


def test_a_title_is_required_to_start(monkeypatch, free_branch):
    _project(monkeypatch)

    async def test(app, pilot, screen) -> None:
        screen.query_one("#task-description", TaskComposer).focus()
        await _type(pilot, "only details")
        await pilot.press("enter")
        await pilot.pause()

        assert app.opened == []
        error = screen.query_one("#task-error", Static)
        assert error.display is True
        assert str(error.render()) == strings.TASK_TITLE_REQUIRED
        assert screen.query_one("#task-title", Input).has_focus

    _run(test)


def test_a_taken_branch_keeps_the_form_open_with_the_reason(monkeypatch):
    _project(monkeypatch)
    monkeypatch.setattr(home_module.engine, "branch_check", lambda _workspace, _name: (True, True))

    async def test(app, pilot, screen) -> None:
        await _type(pilot, "Corrigir login")
        screen.query_one("#task-description", TaskComposer).focus()
        await pilot.press("enter")
        await pilot.pause()

        assert app.opened == []
        assert str(screen.query_one("#task-error", Static).render()) == strings.BRANCH_TAKEN

    _run(test)


def test_the_run_starts_with_the_brief_the_slug_and_the_chosen_options(monkeypatch, free_branch):
    _project(monkeypatch, worktree=True, commits=True, pull_request=False)

    async def test(app, pilot, screen) -> None:
        await _type(pilot, "Corrigir login")
        screen.query_one("#git-atomic-commits", Checkbox).toggle()
        await pilot.pause()
        description = screen.query_one("#task-description", TaskComposer)
        description.text = "erro 500\n\nKeyError: 'email'"
        description.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert free_branch == ["corrigir-login"]
        assert app.opened == [
            (
                "quick-fix",
                "Corrigir login\n\nerro 500\n\nKeyError: 'email'",
                "corrigir-login",
                RunForm(
                    title="Corrigir login",
                    description="erro 500\n\nKeyError: 'email'",
                    use_worktree=True,
                    atomic_commits=False,
                    auto_pull_request=False,
                ),
            )
        ]
        assert screen.query_one("#task-form").display is False

    _run(test)


def test_outside_a_repository_there_is_no_branch_to_name(monkeypatch, free_branch):
    """No slug, no git options: the run starts with every option off and no branch check."""
    _project(monkeypatch, is_repo=False)

    async def test(app, pilot, screen) -> None:
        assert screen.query_one("#task-slug-row").display is False
        assert screen.query_one("#task-git-row").display is False

        await _type(pilot, "Corrigir login")
        screen.query_one("#task-description", TaskComposer).focus()
        await pilot.press("enter")
        await pilot.pause()

        assert free_branch == []
        ((_workflow, _prompt, branch, form),) = app.opened
        assert branch == ""
        assert form is not None
        assert (form.use_worktree, form.atomic_commits, form.auto_pull_request) == (
            False,
            False,
            False,
        )

    _run(test)


def test_esc_discards_the_draft_so_the_next_workflow_starts_blank(monkeypatch):
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await _type(pilot, "rascunho")
        await pilot.press("escape")
        screen.on_option_selected(SimpleNamespace(option_id="workflow:new-issue"))
        await pilot.pause()

        assert screen.query_one("#task-title", Input).value == ""
        assert screen.query_one("#task-slug", Input).value == ""
        assert _heading(screen) == ["Nova sessão", "Nova spec"]

    _run(test)


def test_the_description_grows_with_the_task_up_to_a_cap(monkeypatch):
    """Roomy from the start, taller per line, capped so the options stay on screen."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        description = screen.query_one("#task-description", TaskComposer)
        assert description.size.height == DESCRIPTION_MIN_ROWS

        description.text = "\n".join(f"line {n}" for n in range(5))
        await pilot.pause()
        assert description.size.height == 5

        description.text = "\n".join(f"line {n}" for n in range(40))
        await pilot.pause()
        assert description.size.height == DESCRIPTION_MAX_ROWS

    _run(test)


def test_the_whole_form_fits_a_24_row_terminal(monkeypatch):
    _project(monkeypatch)

    async def test(_app, _pilot, screen) -> None:
        assert screen.query_one(".task-hint", Static).region.bottom <= 24 - 1

    _run(test)


def test_more_options_is_a_control_reached_with_tab_and_chosen_with_enter(monkeypatch):
    """The fields open from a visible control, not from a shortcut written in a sentence."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        toggle = screen.query_one("#task-options")
        assert "Mais opções" in str(toggle.render())

        await pilot.press("tab")
        assert toggle.has_focus
        await pilot.press("enter")
        await pilot.pause()

        assert screen.query_one("#task-title-box").display is True
        assert "Menos opções" in str(toggle.render())

    _run(test, detailed=False)


def test_clicking_more_options_opens_the_fields(monkeypatch):
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await pilot.click("#task-options")
        await pilot.pause()

        assert screen.query_one("#task-title-box").display is True

    _run(test, detailed=False)


def test_the_key_chips_name_the_keys_of_the_mode_on_screen(monkeypatch):
    """Plain mode teaches the line break; the full form teaches moving between fields."""
    _project(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        chips = screen.query_one(".task-hint", Static)
        assert str(chips.render()).split() == [
            "enter",
            "enviar",
            "ctrl+j",
            "nova",
            "linha",
            "@",
            "arquivo",
            "esc",
            "voltar",
        ]

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert str(chips.render()).split() == [
            "tab",
            "próximo",
            "campo",
            "espaço",
            "marcar",
            "@",
            "arquivo",
            "enter",
            "enviar",
            "esc",
            "voltar",
        ]

    _run(test, detailed=False)


def test_at_in_the_description_offers_the_workspace_files(monkeypatch, free_branch):
    """The form asks the daemon for the project's files; picking one types its path."""
    _project(monkeypatch)
    asked: list[Path] = []

    def _files(workspace: Path) -> WorkspaceFiles:
        asked.append(workspace)
        return WorkspaceFiles(tracked=("README.md", "pulse/tui/app.py"))

    monkeypatch.setattr(home_module.engine, "workspace_files", _files)

    async def test(app, pilot, screen) -> None:
        await wait_until(pilot, lambda: asked == [Path.cwd()])
        await pilot.press("at", "a", "p", "p")
        await wait_until(pilot, lambda: screen.query_one(FileMentionList).display)
        await pilot.press("enter")
        await pilot.pause()

        assert screen.query_one("#task-description", TaskComposer).text == "@pulse/tui/app.py "
        assert app.opened == []

    _run(test, detailed=False)


def test_without_the_daemon_files_the_at_sign_is_just_text(monkeypatch, free_branch):
    _project(monkeypatch, worktree=False, commits=False)

    def _refused(_workspace: Path) -> WorkspaceFiles:
        raise home_module.engine.EngineUnavailable("down")

    monkeypatch.setattr(home_module.engine, "workspace_files", _refused)

    async def test(app, pilot, screen) -> None:
        await pilot.press("at", "a")
        await pilot.pause()
        assert screen.query_one(FileMentionList).display is False

        await pilot.press("enter")
        await pilot.pause()
        assert app.opened == [("quick-fix", "@a", "", None)]

    _run(test, detailed=False)


def test_clicking_a_listed_file_types_its_path_and_keeps_the_typing_focus(monkeypatch, free_branch):
    """The list never takes the focus, so the form routes the click to the description."""
    _project(monkeypatch)
    asked: list[Path] = []

    def _files(workspace: Path) -> WorkspaceFiles:
        asked.append(workspace)
        return WorkspaceFiles(tracked=("README.md", "pulse/tui/app.py"))

    monkeypatch.setattr(home_module.engine, "workspace_files", _files)

    async def test(app, pilot, screen) -> None:
        await wait_until(pilot, lambda: asked == [Path.cwd()])
        await pilot.press("at", "p", "u")
        await wait_until(pilot, lambda: screen.query_one(FileMentionList).display)
        # The form's theme drops the list border, so row 0 is the first option.
        await pilot.click(FileMentionList, offset=(2, 0))
        await pilot.pause()

        description = screen.query_one("#task-description", TaskComposer)
        assert description.text == "@pulse/tui/app.py "
        assert description.has_focus
        assert app.opened == []

    _run(test, detailed=False)


NEW_FILE_FILES = WorkspaceFiles(tracked=("README.md",), untracked=("notas.md",))


def _offered(screen: HomeScreen) -> list[str]:
    listed = screen.query_one(FileMentionList)
    return [str(listed.get_option_at_index(index).id) for index in range(listed.option_count)]


def _serve_files(monkeypatch) -> list[Path]:
    asked: list[Path] = []

    def _files(workspace: Path) -> WorkspaceFiles:
        asked.append(workspace)
        return NEW_FILE_FILES

    monkeypatch.setattr(home_module.engine, "workspace_files", _files)
    return asked


@pytest.mark.parametrize(
    ("worktree", "expected"),
    [
        pytest.param(True, ["README.md"], id="worktree"),
        pytest.param(False, ["README.md", "notas.md"], id="in-place"),
    ],
)
def test_new_files_are_offered_only_where_the_agent_will_find_them(
    monkeypatch, free_branch, worktree, expected
):
    """A worktree run starts from a commit: a file git does not track yet is not there."""
    _project(monkeypatch, worktree=worktree, commits=worktree)
    asked = _serve_files(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await wait_until(pilot, lambda: asked == [Path.cwd()])
        await pilot.press("at")
        await wait_until(pilot, lambda: screen.query_one(FileMentionList).display)

        assert _offered(screen) == expected

    _run(test, detailed=False)


def test_turning_the_worktree_off_in_the_form_offers_new_files(monkeypatch, free_branch):
    """The run's own options decide, not the project's they started from."""
    _project(monkeypatch)
    asked = _serve_files(monkeypatch)

    async def test(_app, pilot, screen) -> None:
        await wait_until(pilot, lambda: asked == [Path.cwd()])
        description = screen.query_one("#task-description", TaskComposer)
        description.focus()
        await pilot.press("at")
        await wait_until(pilot, lambda: screen.query_one(FileMentionList).display)
        assert _offered(screen) == ["README.md"]
        await pilot.press("backspace")

        screen.query_one("#git-use-worktree", Checkbox).toggle()
        await pilot.pause()
        description.focus()
        await pilot.press("at")
        await wait_until(pilot, lambda: screen.query_one(FileMentionList).display)

        assert _checked(screen) == (False, True, False)
        assert _offered(screen) == ["README.md", "notas.md"]

    _run(test, detailed=True)
