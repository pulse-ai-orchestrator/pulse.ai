"""Step outcome protocol read from the agent response (`pulse:outcome` block).

Without it, a step that merely ended its turn (e.g. "I can't, missing
credentials") was recorded as `done`. The engine does not interpret prose; the
agent must explicitly declare the outcome, and silence is not success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

OUTCOME_TAG = "outcome"
FIELD = re.compile(
    r"^[ \t>*-]*(status|reason|needs|motivo|precisa|next|proximo|próximo|commit)[ \t]*:[ \t]*(.*)$",
    re.IGNORECASE,
)
COMMIT_SUBJECT_MAX = 72
_COMMIT_TYPE = re.compile(r"^(feat|fix|chore|docs|refactor|test|perf|ci|build|style):\s*(.+)$")


class OutcomeStatus(StrEnum):
    DONE = "done"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    MISSING = "missing"


class LoopSignal(StrEnum):
    """What the agent asks of the loop around its step (the `next` field)."""

    REPEAT = "repeat"
    CLOSE = "close"


_DONE_WORDS = frozenset({"done", "ok", "concluido", "concluído", "sucesso", "success", "pronto"})
_BLOCKED_WORDS = frozenset(
    {"blocked", "bloqueado", "bloqueio", "travado", "stuck", "impedido", "failed", "falhou"}
)
# "This step does not apply to the task." Honoured only where the step definition
# allows it (`StepDef.skippable`); see [pulse.orchestrator.engine._judge_turn].
_SKIPPED_WORDS = frozenset({"skipped", "skip", "pulado", "pular", "dispensado", "n/a"})
_NEEDS_USER = frozenset(
    {
        "user",
        "usuario",
        "usuário",
        "pessoa",
        "human",
        "humano",
        "permission",
        "permissao",
        "permissão",
        "acesso",
        "access",
        "credencial",
        "credential",
        "segredo",
        "secret",
        "decisao",
        "decisão",
    }
)
_REPEAT_WORDS = frozenset({"repeat", "repetir", "again", "denovo", "nova-rodada", "loop"})
_CLOSE_WORDS = frozenset({"close", "fechar", "encerrar", "end", "clean", "limpo"})

REASON_MAX_CHARS = 400


@dataclass(frozen=True)
class Outcome:
    """What the agent declared when closing the step."""

    status: OutcomeStatus
    reason: str = ""
    needs: str = ""
    next: LoopSignal | None = None
    unknown_status: str = ""
    commit_subject: str = ""

    @property
    def delivered(self) -> bool:
        return self.status == OutcomeStatus.DONE

    @property
    def skips(self) -> bool:
        """The agent declares that the step does not apply to this task."""
        return self.status == OutcomeStatus.SKIPPED

    @property
    def repeats(self) -> bool:
        """The agent requests another loop round (only when the step delivered)."""
        return self.delivered and self.next == LoopSignal.REPEAT

    @property
    def closes(self) -> bool:
        """The agent says the loop is over; see [pulse.orchestrator.loops.close_loop]."""
        return self.delivered and self.next == LoopSignal.CLOSE

    @property
    def needs_user(self) -> bool:
        """The agent depends on a person, access or permission.

        When `True`, the self-unblock attempt is skipped and the user is asked directly.
        """
        return self.needs in _NEEDS_USER


@cache
def _fence(tag: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    opener = rf"```pulse:{re.escape(tag)}[ \t]*\n"
    # The body never holds a fence and the closing fence ends its line, so a stray
    # opener quoted from a file cannot run on and swallow the agent's real block.
    block = rf"{opener}((?:(?!```).)*)```[ \t]*(?:\n|$)"
    return re.compile(opener, re.IGNORECASE), re.compile(block, re.DOTALL | re.IGNORECASE)


def last_fenced_block(text: str, tag: str) -> str | None:
    """Body of the block the last `pulse:<tag>` opener starts; `None` if absent or malformed.

    Only the last opener counts. When the agent's own block is malformed, an
    earlier block quoted from a file must not stand in for it.
    """
    opener, block = _fence(tag)
    openers = list(opener.finditer(text))
    if not openers:
        return None
    match = block.match(text, openers[-1].start())
    return match.group(1) if match else None


def parse_outcome(text: str) -> Outcome:
    """Outcome of the last `pulse:outcome` block; `MISSING` when there is none.

    The last block wins because a continued step accumulates more than one.
    """
    body = last_fenced_block(text or "", OUTCOME_TAG)
    if body is None:
        return Outcome(status=OutcomeStatus.MISSING)

    fields: dict[str, str] = {}
    for line in body.splitlines():
        match = FIELD.match(line.strip())
        if match is None:
            continue
        key = match.group(1).lower()
        key = {
            "motivo": "reason",
            "precisa": "needs",
            "proximo": "next",
            "próximo": "next",
        }.get(key, key)
        fields.setdefault(key, _clean(match.group(2)))

    raw_status = _first_word(fields.get("status", ""))
    reason = fields.get("reason", "")[:REASON_MAX_CHARS]
    needs = _first_word(fields.get("needs", ""))
    nxt = _first_word(fields.get("next", ""))

    if raw_status in _DONE_WORDS:
        return Outcome(
            status=OutcomeStatus.DONE,
            next=_loop_signal(nxt),
            commit_subject=accept_commit_subject(fields.get("commit", "")),
        )
    if raw_status in _SKIPPED_WORDS:
        return Outcome(status=OutcomeStatus.SKIPPED, reason=reason)
    if raw_status in _BLOCKED_WORDS:
        return Outcome(status=OutcomeStatus.BLOCKED, reason=reason, needs=needs)
    if not raw_status:
        return Outcome(status=OutcomeStatus.MISSING)
    return Outcome(
        status=OutcomeStatus.BLOCKED, reason=reason, needs=needs, unknown_status=raw_status
    )


def accept_commit_subject(raw: str) -> str:
    """The subject of a `commit:` line, or empty when the line is not usable.

    One lowercase line, no accent, at most 72 characters. A Conventional Commits
    type at the start is dropped: the step's `commit_type` supplies the prefix.
    """
    text = raw.strip()
    if not text or len(text) > COMMIT_SUBJECT_MAX or text != text.lower():
        return ""
    if any(ord(char) > 127 for char in text):
        return ""
    typed = _COMMIT_TYPE.match(text)
    subject = typed.group(2).strip() if typed else text
    if not subject or len(subject) > COMMIT_SUBJECT_MAX:
        return ""
    return subject


def _loop_signal(word: str) -> LoopSignal | None:
    if word in _REPEAT_WORDS:
        return LoopSignal.REPEAT
    if word in _CLOSE_WORDS:
        return LoopSignal.CLOSE
    return None


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _first_word(value: str) -> str:
    """`done.`, `**done**` and `done — entreguei` are all the same `done`."""
    words = value.split()
    return words[0].lower().strip(".,;:*_`") if words else ""
