from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from pulse.domain.ports import JsonObject
from pulse.replies.acp_payloads import items_of, truthy_text
from pulse.replies.wording import DEFAULT_QUESTIONNAIRE_TITLE

_HEADER_PATTERN = re.compile(
    r"(?:^|\n)(Preciso de algumas informações[^\n]*|I need some information[^\n]*)",
    re.IGNORECASE,
)
_FENCED_BLOCK = re.compile(r"```(?:text)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_QUESTION_LINE = re.compile(r"^(\d+)\.\s+(.+)$")
_OPTION_LINE = re.compile(r"^([A-Z])\)\s+(.+)$")
QUESTIONNAIRE_START = re.compile(
    r"```text"
    r"|```[ \t]*\n[ \t]*(?:\d+\.[ \t]|Preciso de algumas informações|I need some information)"
    r"|Preciso de algumas informações|I need some information before continuing"
    r"|Apresentando todas as perguntas",
    re.IGNORECASE,
)
_ANSWER_MARK = "→ "


@dataclass(frozen=True)
class TextQuestion:
    id: str
    prompt: str
    options: tuple[tuple[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TextQuestionnaire:
    title: str
    questions: tuple[TextQuestion, ...]
    raw: str = ""


def _strip_answer_footer(block: str) -> str:
    return re.sub(r"\nResposta:\s*$", "", block.strip(), flags=re.IGNORECASE).strip()


def extract_questionnaire_block(text: str) -> str | None:
    if not text.strip():
        return None

    fenced = _FENCED_BLOCK.search(text)
    if fenced:
        block = _strip_answer_footer(fenced.group(1).strip())
        if _has_question_structure(block):
            return block

    header = _HEADER_PATTERN.search(text)
    if not header:
        return None

    start = header.start(1)
    tail = text[start:]
    answer_match = re.search(r"\nResposta:\s*(?:\n|$)", tail, re.IGNORECASE)
    if answer_match:
        block = tail[: answer_match.start()].strip()
    else:
        block = tail.strip()

    block = _strip_answer_footer(block)
    if _has_question_structure(block):
        return block
    return None


def strip_questionnaire_block(text: str) -> tuple[str, bool]:
    """The agent's speech without the questionnaire, and whether there was one.

    The question block is rendered as a dock and as Q/A bubbles in the log, so
    keeping it would show the questions twice on a reopened run.
    """
    start = QUESTIONNAIRE_START.search(text)
    if start is None:
        return text.strip(), False
    return text[: start.start()].strip(), True


def split_questionnaire_answers(
    questionnaire: TextQuestionnaire,
    answers_text: str,
) -> list[tuple[str, str]]:
    """Undo [format_questionnaire_answers] into (question, answer) pairs.

    The daemon-side logger only has the combined answer text to rebuild the dialog.
    """
    replies = [
        line.strip()[len(_ANSWER_MARK) :].strip()
        for line in str(answers_text or "").splitlines()
        if line.strip().startswith(_ANSWER_MARK)
    ]
    pairs: list[tuple[str, str]] = []
    for index, question in enumerate(questionnaire.questions):
        if index >= len(replies):
            break
        pairs.append((question.prompt, replies[index]))
    return pairs


@dataclass
class _QuestionDraft:
    """A numbered question while its lines are read: prompt lines, then options."""

    number: str
    prompt_lines: list[str]
    options: list[tuple[str, str]] = field(default_factory=list)

    def absorb(self, line: str) -> None:
        option = _OPTION_LINE.match(line)
        if option:
            self.options.append((option.group(1), option.group(2).strip()))
        elif not self.options:
            self.prompt_lines.append(line)

    def finish(self) -> TextQuestion | None:
        prompt = " ".join(line.strip() for line in self.prompt_lines if line.strip())
        if not prompt:
            return None
        return TextQuestion(
            id=f"q{self.number}",
            prompt=f"{self.number}. {prompt}",
            options=tuple(self.options),
        )


def _question_lines(block: str) -> Iterator[str]:
    """The block's meaningful lines, up to the `Resposta:` footer."""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or _HEADER_PATTERN.match(line):
            continue
        if line.lower().startswith("resposta:"):
            return
        yield line


def _parse_questions(block: str) -> list[TextQuestion]:
    drafts: list[_QuestionDraft] = []
    for line in _question_lines(block):
        numbered = _QUESTION_LINE.match(line)
        if numbered:
            drafts.append(_QuestionDraft(numbered.group(1), [numbered.group(2).strip()]))
        elif drafts:
            drafts[-1].absorb(line)
    finished = (draft.finish() for draft in drafts)
    return [question for question in finished if question is not None]


def parse_text_questionnaire(text: str) -> TextQuestionnaire | None:
    block = extract_questionnaire_block(text)
    if not block:
        return None
    questions = _parse_questions(block)
    if not questions:
        return None
    title_match = _HEADER_PATTERN.search(block)
    title = title_match.group(1).strip() if title_match else DEFAULT_QUESTIONNAIRE_TITLE
    return TextQuestionnaire(title=title, questions=tuple(questions), raw=block)


def serialize_questionnaire(questionnaire: TextQuestionnaire) -> JsonObject:
    return {
        "title": questionnaire.title,
        "raw": questionnaire.raw,
        "questions": [
            {
                "id": question.id,
                "prompt": question.prompt,
                "options": [{"id": letter, "label": label} for letter, label in question.options],
            }
            for question in questionnaire.questions
        ],
    }


def questionnaire_from_payload(payload: Mapping[str, object]) -> TextQuestionnaire | None:
    """Undo [serialize_questionnaire]; the raw block wins when it still parses."""
    raw = truthy_text(payload.get("raw"))
    parsed = parse_text_questionnaire(raw) if raw else None
    if parsed is not None:
        return parsed
    questions: list[TextQuestion] = []
    for item in items_of(payload.get("questions")):
        question = _question_from_payload(item, fallback_id=f"q{len(questions) + 1}")
        if question is not None:
            questions.append(question)
    if not questions:
        return None
    title = truthy_text(payload.get("title") or DEFAULT_QUESTIONNAIRE_TITLE).strip()
    return TextQuestionnaire(
        title=title or DEFAULT_QUESTIONNAIRE_TITLE, questions=tuple(questions), raw=raw
    )


def _question_from_payload(item: object, *, fallback_id: str) -> TextQuestion | None:
    if not isinstance(item, Mapping):
        return None
    prompt = truthy_text(item.get("prompt")).strip()
    if not prompt:
        return None
    options = (_option_from_payload(option) for option in items_of(item.get("options")))
    return TextQuestion(
        id=truthy_text(item.get("id") or fallback_id),
        prompt=prompt,
        options=tuple(option for option in options if option is not None),
    )


def _option_from_payload(option: object) -> tuple[str, str] | None:
    """An option as `{"id"|"letter", "label"}` or as a `[letter, label]` pair."""
    if isinstance(option, Mapping):
        letter = truthy_text(option.get("id") or option.get("letter")).strip()
        label = truthy_text(option.get("label")).strip()
        return (letter, label) if letter and label else None
    pair = items_of(option)
    if len(pair) >= 2:
        return (str(pair[0]), str(pair[1]))
    return None


_ANSWERS_HEADER = "Respostas coletadas via questionário interativo do Pulse:"
# Asking one question per round spends the approval loop's turns on a single
# decision each; a step with many open decisions then hits the turn cap.
_ANSWERS_FOOTER = (
    "Continue o fluxo com base nestas respostas. "
    "Se ainda faltarem decisões, faça no mesmo bloco todas as perguntas que já "
    "consegue ver, em vez de uma por rodada."
)


def format_questionnaire_answers(
    questionnaire: TextQuestionnaire,
    answers: list[tuple[TextQuestion, str]],
) -> str:
    lines = [_ANSWERS_HEADER, ""]
    for question, answer in answers:
        lines.append(question.prompt)
        lines.append(f"→ {answer}")
        lines.append("")
    lines.append(_ANSWERS_FOOTER)
    return "\n".join(lines)


def answered_questions(answers_text: str) -> str:
    """The question and answer lines of [format_questionnaire_answers], without its frame.

    A retry repeats every earlier round; the header and the closing instruction
    would repeat with each of them.
    """
    frame = {_ANSWERS_HEADER, _ANSWERS_FOOTER}
    kept = [line for line in answers_text.splitlines() if line.strip() not in frame]
    return "\n".join(kept).strip()


def _has_question_structure(block: str) -> bool:
    has_question = any(_QUESTION_LINE.match(line.strip()) for line in block.splitlines())
    has_option = any(_OPTION_LINE.match(line.strip()) for line in block.splitlines())
    return has_question and has_option
