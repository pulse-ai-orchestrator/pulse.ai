"""Reading the questionnaire an agent writes as text, and writing the answers back.

The agent's text is untrusted: only a block with numbered questions *and*
lettered options is a questionnaire, and everything around it stays speech.
A block that does parse must keep every question, option and number exactly,
or the user answers a question the agent did not ask.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.replies.text_questionnaire import (
    TextQuestion,
    TextQuestionnaire,
    answered_questions,
    extract_questionnaire_block,
    format_questionnaire_answers,
    parse_text_questionnaire,
    questionnaire_from_payload,
    serialize_questionnaire,
    split_questionnaire_answers,
    strip_questionnaire_block,
)
from pulse.replies.wording import DEFAULT_QUESTIONNAIRE_TITLE

FENCED = (
    "Some context first.\n"
    "```text\n"
    "I need some information before continuing.\n"
    "\n"
    "1. Which stack?\n"
    "A) Python\n"
    "B)   Go  \n"
    "\n"
    "2. Deploy\n"
    "where?\n"
    "A) Cloud\n"
    "Resposta:\n"
    "```\n"
    "Trailing speech."
)
FENCED_BLOCK = (
    "I need some information before continuing.\n"
    "\n"
    "1. Which stack?\n"
    "A) Python\n"
    "B)   Go  \n"
    "\n"
    "2. Deploy\n"
    "where?\n"
    "A) Cloud"
)
STACK = TextQuestion("q1", "1. Which stack?", (("A", "Python"), ("B", "Go")))
DEPLOY = TextQuestion("q2", "2. Deploy where?", (("A", "Cloud"),))


# --- extracting the block ---------------------------------------------------


def test_fenced_block_is_extracted_without_the_answer_footer() -> None:
    assert extract_questionnaire_block(FENCED) == FENCED_BLOCK


def test_fenced_questionnaire_parses_every_question_and_option() -> None:
    assert parse_text_questionnaire(FENCED) == TextQuestionnaire(
        title="I need some information before continuing.",
        questions=(STACK, DEPLOY),
        raw=FENCED_BLOCK,
    )


def test_untagged_fence_with_lower_case_footer_is_extracted() -> None:
    text = "```\n1. Pick one\nA) Yes\nB) No\nresposta:   \n```"

    assert extract_questionnaire_block(text) == "1. Pick one\nA) Yes\nB) No"


def test_header_block_ends_at_the_answer_footer() -> None:
    text = (
        "Before.\n"
        "Preciso de algumas informações:\n"
        "1. Name?\n"
        "A) Yes\n"
        "Resposta:\n"
        "3. Not part of it\n"
        "B) No"
    )

    assert extract_questionnaire_block(text) == "Preciso de algumas informações:\n1. Name?\nA) Yes"


def test_header_block_without_footer_runs_to_the_end() -> None:
    text = "Intro\nI need some information please\n1. Name?\nA) Yes\n  "

    assert extract_questionnaire_block(text) == "I need some information please\n1. Name?\nA) Yes"


def test_header_block_with_a_trailing_footer_drops_it() -> None:
    text = "I need some information\n1. Name?\nA) Yes\nResposta:"

    assert extract_questionnaire_block(text) == "I need some information\n1. Name?\nA) Yes"


def test_header_block_ends_at_a_lower_case_footer_too() -> None:
    text = "I need some information\n1. Name?\nA) Yes\nresposta:\nAfter the footer."

    assert extract_questionnaire_block(text) == "I need some information\n1. Name?\nA) Yes"


def test_fence_without_questions_falls_back_to_the_header_block() -> None:
    text = "```\nprint('hello')\n```\nI need some information now\n1. Name?\nA) Yes"

    assert extract_questionnaire_block(text) == "I need some information now\n1. Name?\nA) Yes"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n  ",
        "Just speech, no questions.",
        "```\n1. A question without options\n```",
        "```\nA) An option without a question\n```",
        "I need some information\n1. A question without options",
        "I need some information\nA) An option without a question",
        "1. Numbered\nA) Lettered, but no fence and no header",
    ],
)
def test_text_without_numbered_questions_and_options_is_not_a_questionnaire(text: str) -> None:
    """Free speech that happens to look like a list must not open a dock."""
    assert extract_questionnaire_block(text) is None
    assert parse_text_questionnaire(text) is None


# --- parsing questions ------------------------------------------------------


def test_block_without_header_gets_the_default_title() -> None:
    text = "```\n12. Pick one\nA) Yes\n```"

    assert parse_text_questionnaire(text) == TextQuestionnaire(
        title=DEFAULT_QUESTIONNAIRE_TITLE,
        questions=(TextQuestion("q12", "12. Pick one", (("A", "Yes"),)),),
        raw="12. Pick one\nA) Yes",
    )


def test_lines_after_a_mid_block_answer_footer_are_ignored() -> None:
    text = "```\n1. First?\nA) Yes\nResposta: A\n2. Second?\nB) No\n```"

    parsed = parse_text_questionnaire(text)

    assert parsed is not None
    assert parsed.questions == (TextQuestion("q1", "1. First?", (("A", "Yes"),)),)


def test_prompt_lines_join_until_the_first_option_and_later_prose_is_dropped() -> None:
    text = (
        "```\n"
        "Lines before any question are not part of one.\n"
        "1. Which\n"
        "a) lower case is prose\n"
        "stack?\n"
        "A) Python\n"
        "note between options\n"
        "B) Go\n"
        "```"
    )

    parsed = parse_text_questionnaire(text)

    assert parsed is not None
    assert parsed.questions == (
        TextQuestion(
            "q1", "1. Which a) lower case is prose stack?", (("A", "Python"), ("B", "Go"))
        ),
    )


def test_a_repeated_header_line_is_not_part_of_a_prompt() -> None:
    text = "```\n1. Name?\nI need some information again\nA) Yes\n```"

    parsed = parse_text_questionnaire(text)

    assert parsed is not None
    assert parsed.questions == (TextQuestion("q1", "1. Name?", (("A", "Yes"),)),)


def test_question_without_options_is_kept_beside_one_with_options() -> None:
    text = "```\n1. Your name?\n2. Stack?\nA) Python\n```"

    parsed = parse_text_questionnaire(text)

    assert parsed is not None
    assert parsed.questions == (
        TextQuestion("q1", "1. Your name?", ()),
        TextQuestion("q2", "2. Stack?", (("A", "Python"),)),
    )


# --- stripping the block from speech ----------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Plain speech.  ", ("Plain speech.", False)),
        ("```python\nprint(1)\n```", ("```python\nprint(1)\n```", False)),
        ("I need some information", ("I need some information", False)),
        ("Hello\n```text\n1. Q\nA) x", ("Hello", True)),
        ("Hello\n```TEXT\nanything", ("Hello", True)),
        ("Intro\n``` \t\n  1.\tQ", ("Intro", True)),
        ("Intro\n```\nPreciso de algumas informações", ("Intro", True)),
        ("Intro\n```\nI need some information", ("Intro", True)),
        ("Intro  Preciso de algumas informações agora", ("Intro", True)),
        ("Intro I need some information before continuing.", ("Intro", True)),
        ("Intro. apresentando todas as perguntas:", ("Intro.", True)),
        ("```\n1. Q", ("", True)),
    ],
)
def test_strip_keeps_only_the_speech_before_the_questionnaire(
    text: str, expected: tuple[str, bool]
) -> None:
    assert strip_questionnaire_block(text) == expected


# --- answers ----------------------------------------------------------------


def test_answers_are_formatted_as_prompt_then_arrow_answer() -> None:
    questionnaire = TextQuestionnaire(title="T", questions=(STACK, DEPLOY))

    text = format_questionnaire_answers(questionnaire, [(STACK, "A) Python"), (DEPLOY, "Cloud")])

    assert text == (
        "Respostas coletadas via questionário interativo do Pulse:\n"
        "\n"
        "1. Which stack?\n"
        "→ A) Python\n"
        "\n"
        "2. Deploy where?\n"
        "→ Cloud\n"
        "\n"
        "Continue o fluxo com base nestas respostas. "
        "Se ainda faltarem decisões, faça no mesmo bloco todas as perguntas que já "
        "consegue ver, em vez de uma por rodada."
    )


def test_formatted_answers_ask_for_the_next_questions_in_one_batch() -> None:
    """One question per round spends the approval loop's turn cap on one decision each."""
    text = format_questionnaire_answers(TextQuestionnaire(title="T", questions=()), [])

    assert "uma pergunta por vez" not in text
    assert "no mesmo bloco todas as perguntas" in text


def test_answered_questions_drop_the_frame_and_keep_every_pair() -> None:
    questionnaire = TextQuestionnaire(title="T", questions=(STACK, DEPLOY))
    text = format_questionnaire_answers(questionnaire, [(STACK, "A) Python"), (DEPLOY, "Cloud")])

    assert answered_questions(text) == ("1. Which stack?\n→ A) Python\n\n2. Deploy where?\n→ Cloud")


@pytest.mark.parametrize(
    ("answers_text", "expected"),
    [
        ("", ""),
        ("  \n\n  ", ""),
        ("1. Free text?\n→ Outro — tanto faz\n", "1. Free text?\n→ Outro — tanto faz"),
        (
            "  Respostas coletadas via questionário interativo do Pulse:  \n1. Q?\n→ A",
            "1. Q?\n→ A",
        ),
        (
            "Respostas coletadas via questionário interativo do Pulse: extra\n1. Q?\n→ A",
            "Respostas coletadas via questionário interativo do Pulse: extra\n1. Q?\n→ A",
        ),
    ],
)
def test_answered_questions_drop_only_whole_frame_lines(answers_text: str, expected: str) -> None:
    assert answered_questions(answers_text) == expected


def test_formatted_answers_split_back_into_question_and_answer_pairs() -> None:
    questionnaire = TextQuestionnaire(title="T", questions=(STACK, DEPLOY))
    text = format_questionnaire_answers(questionnaire, [(STACK, "A) Python"), (DEPLOY, "Cloud")])

    assert split_questionnaire_answers(questionnaire, text) == [
        ("1. Which stack?", "A) Python"),
        ("2. Deploy where?", "Cloud"),
    ]


@pytest.mark.parametrize(
    ("answers_text", "expected"),
    [
        ("", []),
        ("no arrows here", []),
        (
            "  →   spaced out  \n→ second\n→ third",
            [("1. Which stack?", "spaced out")] + [("2. Deploy where?", "second")],
        ),
        ("→ only one", [("1. Which stack?", "only one")]),
        ("x → not at line start\n→ real", [("1. Which stack?", "real")]),
    ],
)
def test_split_pairs_answers_by_position_and_stops_at_the_shorter_side(
    answers_text: str, expected: list[tuple[str, str]]
) -> None:
    questionnaire = TextQuestionnaire(title="T", questions=(STACK, DEPLOY))

    assert split_questionnaire_answers(questionnaire, answers_text) == expected


# --- payload round trip -----------------------------------------------------


def test_serialize_writes_title_raw_and_every_option() -> None:
    questionnaire = TextQuestionnaire(title="T", questions=(STACK, DEPLOY), raw="raw block")

    assert serialize_questionnaire(questionnaire) == {
        "title": "T",
        "raw": "raw block",
        "questions": [
            {
                "id": "q1",
                "prompt": "1. Which stack?",
                "options": [{"id": "A", "label": "Python"}, {"id": "B", "label": "Go"}],
            },
            {"id": "q2", "prompt": "2. Deploy where?", "options": [{"id": "A", "label": "Cloud"}]},
        ],
    }


def test_payload_raw_block_wins_over_the_question_list() -> None:
    payload = {
        "title": "Ignored",
        "raw": FENCED_BLOCK,
        "questions": [{"id": "x", "prompt": "Ignored?"}],
    }

    assert questionnaire_from_payload(payload) == TextQuestionnaire(
        title="I need some information before continuing.",
        questions=(STACK, DEPLOY),
        raw=FENCED_BLOCK,
    )


def test_payload_question_list_is_read_when_raw_does_not_parse() -> None:
    payload = {
        "title": "  Setup  ",
        "raw": "not a questionnaire",
        "questions": [
            {
                "prompt": "  Stack?  ",
                "options": [
                    {"id": " A ", "label": " Python "},
                    {"id": "", "letter": "B", "label": "Go"},
                    ["C", "Rust", "extra"],
                    [4, 5],
                    ["D"],
                    {"id": "E"},
                    {"label": "No letter"},
                    "F) prose",
                ],
            },
            "junk",
            {"id": "blank", "prompt": "   "},
            {"id": "custom", "prompt": "Name?"},
            {"prompt": "Where?", "options": "A) Cloud"},
        ],
    }

    assert questionnaire_from_payload(payload) == TextQuestionnaire(
        title="Setup",
        questions=(
            TextQuestion(
                "q1",
                "Stack?",
                (("A", "Python"), ("B", "Go"), ("C", "Rust"), ("4", "5")),
            ),
            TextQuestion("custom", "Name?", ()),
            TextQuestion("q3", "Where?", ()),
        ),
        raw="not a questionnaire",
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (None, DEFAULT_QUESTIONNAIRE_TITLE),
        ("", DEFAULT_QUESTIONNAIRE_TITLE),
        ("   ", DEFAULT_QUESTIONNAIRE_TITLE),
        (" Mine ", "Mine"),
    ],
)
def test_payload_without_a_readable_title_gets_the_default(title: object, expected: str) -> None:
    payload = {"title": title, "questions": [{"id": "q1", "prompt": "Name?"}]}

    assert questionnaire_from_payload(payload) == TextQuestionnaire(
        title=expected, questions=(TextQuestion("q1", "Name?", ()),), raw=""
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"raw": "", "questions": []},
        {"raw": None, "questions": "1. Name?"},
        {"questions": [{"prompt": ""}, {"id": "q1"}, None]},
    ],
)
def test_payload_without_a_readable_question_is_none(payload: dict[str, object]) -> None:
    assert questionnaire_from_payload(payload) is None


_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz?", min_size=1, max_size=10)


@given(
    prompts=st.lists(_WORD, min_size=1, max_size=4),
    labels=st.lists(_WORD, min_size=1, max_size=3),
)
def test_any_well_formed_block_round_trips_through_the_payload(
    prompts: list[str], labels: list[str]
) -> None:
    """What the daemon stores must rebuild the same questionnaire on a reopened run."""
    letters = "ABC"
    lines = []
    for number, prompt in enumerate(prompts, start=1):
        lines.append(f"{number}. {prompt}")
        lines.extend(f"{letters[index]}) {label}" for index, label in enumerate(labels))
    block = "\n".join(lines)
    options = tuple((letters[index], label) for index, label in enumerate(labels))
    expected = TextQuestionnaire(
        title=DEFAULT_QUESTIONNAIRE_TITLE,
        questions=tuple(
            TextQuestion(f"q{number}", f"{number}. {prompt}", options)
            for number, prompt in enumerate(prompts, start=1)
        ),
        raw=block,
    )

    parsed = parse_text_questionnaire(f"```text\n{block}\n```")

    assert parsed == expected
    assert questionnaire_from_payload(serialize_questionnaire(expected)) == expected
