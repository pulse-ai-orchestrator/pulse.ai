"""What the engine tells the user, in Portuguese: run notices, the step menu, why a step stopped.

The engine composes these itself because it is the one that knows what just
happened; the screens only show them. Code, errors and logs stay in English.
"""

from __future__ import annotations

# Run notices narrated by the engine.
RUN_STOPPED_BY_USER = "Run parada pelo usuário"
AGENT_SESSION_RESTARTED = "Sessão do agente reiniciada"
LOOP_START = "o início do laço"


def run_stopped_at(label: str) -> str:
    return f"Run parada em {label}"


def loop_closed(label: str) -> str:
    return f"{label}: nada a corrigir — laço encerrado"


def step_skipped_by_user(label: str) -> str:
    return f"{label} pulado pelo usuário"


def run_blocked_at(label: str, reason: str) -> str:
    return f"Run bloqueada em {label}: {reason}"


def retrying_step(label: str) -> str:
    return f"Refazendo {label}"


def retrying_step_with_guidance(label: str) -> str:
    return f"Refazendo {label} com orientação do usuário"


def agent_session_restart_failed(error: str) -> str:
    return f"Não consegui reiniciar a sessão do agente: {error}"


def loop_ceiling_reached(label: str, max_rounds: int) -> str:
    return f"{label}: teto de {max_rounds} rodadas atingido — o que sobrou vai no relatório"


def loop_round_requested(label: str, number: int) -> str:
    return f"{label} pediu a {number}ª rodada"


def loop_last_round_requested(label: str, number: int, who: str) -> str:
    return f"{label} pediu a {number}ª rodada — a última: só {who} roda"


# The menu offered when a step fails or is blocked.
RETRY = "Refazer"
RETRY_RESOLVED = "Refazer — já resolvi"
GIVE_GUIDANCE = "Outro — dizer o que fazer"
STOP = "Parar"
SKIP_STEP = "Pular este step"
STOP_RUN = "Parar a run"
STEP_NOT_COMPLETED = "O step não foi concluído."
GUIDANCE_QUESTION = "O que o agente deve fazer nesta nova tentativa?"


def step_blocked_title(label: str) -> str:
    return f"{label} está bloqueado"


def step_failed_title(label: str) -> str:
    return f"Step {label} falhou"


# Why a step did not settle, shown under the menu title.
STEP_CANCELLED = "step cancelado"
STEP_NOT_APPROVED = "step não aprovado"
APPROVAL_TURNS_EXHAUSTED = (
    "o step atingiu o limite de rodadas de perguntas sem chegar à aprovação — "
    "Refazer abre uma sessão nova que já recebe as respostas dadas"
)
NO_APPROVAL_NOR_OUTCOME = "o agente encerrou sem o bloco de aprovação nem um desfecho válido"
AGENT_DID_NOT_COMPLETE = "o agente não concluiu o step"
OUTCOME_NOT_DECLARED = (
    "o agente encerrou sem declarar o desfecho do step — "
    "não dá para afirmar que ele entregou o que o step pede"
)
BLOCKED_WITHOUT_REASON = "o agente declarou bloqueio sem dizer o motivo"


def commit_failed(error: str) -> str:
    return f"Não commitei: {error}"


def publish_failed(error: str) -> str:
    return f"Não publiquei a branch: {error}"


def pull_request_failed(error: str) -> str:
    return f"Não abri o pedido: {error}"


def worktree_left_dirty() -> str:
    return "A pasta do worktree ficou: ainda há alteração sem commit"


def local_branch_kept(error: str) -> str:
    return f"A branch local ficou: {error}"


def commit_message(commit_type: str, subject: str, *, item_id: str) -> str:
    text = subject.strip() or _fallback_subject(commit_type, item_id)
    return f"{commit_type}: {text}"


def _fallback_subject(commit_type: str, item_id: str) -> str:
    if commit_type == "feat" and item_id:
        return f"implement {item_id}"
    if commit_type == "feat":
        return "implement the change"
    return "apply the correction"


def unknown_outcome(status: str) -> str:
    return f"o agente declarou um desfecho que o Pulse não conhece: `{status}`"


def agent_stopped_responding(detail: str) -> str:
    return f"o agente parou de responder — {detail}"


def agent_session_dropped(detail: str) -> str:
    return f"a sessão do agente caiu — {detail}"


def step_crashed(detail: str) -> str:
    return f"o step quebrou — {detail}"
