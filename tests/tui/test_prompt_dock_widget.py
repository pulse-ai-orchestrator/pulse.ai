"""The prompt dock on its own: every answer kind reaches the run exactly once."""

from __future__ import annotations

import asyncio
from typing import Any

from pulse.tui import strings
from pulse.tui.adapters.prompt_bridge import PromptKind, PromptRequest
from pulse.tui.theme import COCKPIT_CSS
from pulse.tui.widgets.prompt_dock import PromptDock


def _request(kind: PromptKind, **fields: Any) -> PromptRequest:
    values: dict[str, Any] = {
        "kind": kind,
        "title": "Questionnaire",
        "prompt": "Pick one",
        "choices": [],
        "future": None,
    }
    values.update(fields)
    return PromptRequest(**values)


def _harness(request: PromptRequest, answers: list[object | None]):
    from textual.app import App, ComposeResult

    class Harness(App[None]):
        CSS = COCKPIT_CSS

        def compose(self) -> ComposeResult:
            yield PromptDock(request, answers.append, id="dock")

    return Harness()


def test_multi_select_toggles_marks_and_confirms_the_marked_set():
    """Selecting an option twice unmarks it; letters do not answer a multi-select."""
    request = _request(
        PromptKind.MULTI_SELECT,
        choices=[("a", "A) Alpha"), ("b", "B) Beta"), ("c", "C) Gamma")],
    )
    answers: list[object | None] = []

    async def run() -> None:
        from textual.widgets import Button, OptionList

        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            dock = app.query_one(PromptDock)
            options = app.query_one("#prompt-options", OptionList)
            assert options.has_focus
            assert str(dock.query_one(".prompt-hint").render()) == strings.PROMPT_HINT_MULTI_SELECT
            assert str(app.query_one("#ok", Button).label) == strings.CONFIRM

            await pilot.press("a")
            await pilot.pause()
            assert answers == [], "a letter would toggle an invisible mark"

            for index in (0, 1, 0, 2):
                options.highlighted = index
                options.action_select()
                await pilot.pause()

            await pilot.click("#ok")
            await pilot.pause()

            assert len(answers) == 1
            assert sorted(answers[0]) == ["b", "c"]  # type: ignore[arg-type]  # list from the dock

    asyncio.run(run())


def test_cancel_button_answers_none():
    """Cancelling is an answer too: the run must not wait forever on a closed dock."""
    request = _request(PromptKind.MULTI_SELECT, choices=[("a", "A) Alpha")])
    answers: list[object | None] = []

    async def run() -> None:
        from textual.widgets import Button

        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.query_one("#cancel", Button).press()
            await pilot.pause()

    asyncio.run(run())

    assert answers == [None]


def test_confirm_starts_on_yes_under_the_default_title_and_answers_true():
    """An untitled question still gets a heading; Enter on the focused button approves."""
    request = _request(PromptKind.CONFIRM, title="", prompt="Allow write?")
    answers: list[object | None] = []

    async def run() -> None:
        from textual.widgets import Button

        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            dock = app.query_one(PromptDock)
            assert app.query_one("#yes", Button).has_focus
            assert str(dock.query_one(".prompt-title").render()) == strings.PROMPT_TITLE.format(
                title=strings.PROMPT_DEFAULT_TITLE
            )
            assert str(dock.query_one(".prompt-text").render()) == "Allow write?"

            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(run())

    assert answers == [True]


def test_select_ignores_keys_that_are_not_on_screen_and_maps_blank_ids_to_none():
    """Only the letters shown pick an option; an option without an id answers nothing."""
    request = _request(
        PromptKind.SELECT,
        choices=[("keep", "A) Keep"), ("", "B) Nothing")],
    )
    answers: list[object | None] = []

    async def run() -> None:
        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("z")
            await pilot.pause()
            assert answers == []

            await pilot.press("b")
            await pilot.pause()

    asyncio.run(run())

    assert answers == [None]


def test_text_prompt_starts_empty_without_default_and_submits_the_typed_value():
    request = _request(PromptKind.TEXT, prompt="Describe it")
    answers: list[object | None] = []

    async def run() -> None:
        from textual.widgets import Input

        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            field = app.query_one("#prompt-input", Input)
            assert field.has_focus
            assert field.value == ""
            assert field.placeholder == strings.PROMPT_INPUT_PLACEHOLDER

            await pilot.press("o", "k")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(run())

    assert answers == ["ok"]


def test_escape_cancels_once_and_leaves_the_app_responsive():
    """The dock's own flag shadowed Textual's `_closed`: answering detached it and Esc hung."""
    request = _request(PromptKind.TEXT, prompt="Why?")
    answers: list[object | None] = []

    async def run() -> None:
        app = _harness(request, answers)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one(PromptDock).is_attached

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert answers == [None]
