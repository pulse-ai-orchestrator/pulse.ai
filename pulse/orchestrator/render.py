"""Prompt template rendering.

The text comes from the step's `prompt_template` column; Pulse only fills in
run values. Placeholders use `{{key}}`, since agent text often has literal `{`.
"""

from __future__ import annotations

import re

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.IGNORECASE)

CONDITIONAL = re.compile(
    r"\{\{#if\s+([a-z0-9_]+)\s*\}\}\n?(.*?)\{\{/if\}\}\n?",
    re.IGNORECASE | re.DOTALL,
)


class TemplateError(RuntimeError):
    """Template requires a value Pulse does not have."""


def render(text: str, context: dict[str, str]) -> str:
    """Replace `{{key}}` with its value. An unknown key is an error, not a gap.

    Silently dropping a placeholder would send the agent a truncated instruction.
    """
    missing: list[str] = []

    def _conditional(match: re.Match[str]) -> str:
        key, body = match.group(1), match.group(2)
        return body if context.get(key, "").strip() else ""

    text = CONDITIONAL.sub(_conditional, text)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            missing.append(key)
            return match.group(0)
        return context[key]

    result = PLACEHOLDER.sub(_replace, text)
    if missing:
        raise TemplateError("placeholder without a value: " + ", ".join(sorted(set(missing))))
    return result


def fill_present(text: str, context: dict[str, str]) -> str:
    """Replace `{{key}}` when `context` has it. A key it lacks stays written.

    A project's own template is not a Pulse template: an unknown placeholder
    must not stop the request from opening.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        if key not in context:
            return match.group(0)
        return context[key]

    return PLACEHOLDER.sub(_replace, text)
