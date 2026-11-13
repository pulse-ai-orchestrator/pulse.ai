"""Every user-visible text of the TUI, in one place.

The product speaks Portuguese to the user while code, errors and logs are in
English; keeping the copy here keeps the screens free of Portuguese literals
(enforced by `tests/tui/test_strings.py`) and lets wording change without
touching behavior. Parametrized texts are `str.format` templates: the
placeholder names document what each one receives.
"""

from __future__ import annotations

from pulse.client.run_session import ERROR_TITLE, WORKFLOW_FAILED_TITLE
from pulse.history import log_wording

# Shared: actions, answers and hints reused across screens
BACK = "Voltar"
BACK_ARROW = "← Voltar"
CANCEL = "Cancelar"
CONFIRM = "Confirmar"
REMOVE = "Remover"
QUIT = "Sair"
# Dialog and error words the engine also records in the run history: one
# source, so the live screen and the reopened run never disagree.
YES = log_wording.ANSWER_YES
NO = log_wording.ANSWER_NO
CANCELLED = log_wording.ANSWER_CANCELLED
QUESTION = log_wording.QUESTION_TITLE
ANSWER = log_wording.ANSWER_TITLE
ERROR = ERROR_TITLE
AGENT = "Agent"
ENVIRONMENT = "Ambiente"
HINT_CONFIRM_OR_CANCEL = "Enter confirma · Esc cancela"
HINT_CONFIRM_OR_BACK = "Enter confirma · Esc volta"
RUN_SUMMARY = "{current} · steps {done}/{total}"

# Apps
APP_TITLE = "Pulse // ACP Cockpit"
ONBOARDING_APP_TITLE = "Pulse // Setup"

# Cockpit and history detail: key bindings
BINDING_MENU = "Menu"
BINDING_STOP = "Parar"
BINDING_RESUME = "Retomar"
BINDING_REMOVE_WORKTREE = "Remover worktree"
BINDING_FOCUS = "Focus"
BINDING_ARTIFACTS = "Artifacts"
BINDING_BACK = "Back"
BINDING_PREV_FILE = "Prev file"
BINDING_NEXT_FILE = "Next file"
BINDING_UP = "Up"
BINDING_DOWN = "Down"

# Cockpit: run lifecycle messages in the stream
WORKFLOW_FAILED = WORKFLOW_FAILED_TITLE
WORKFLOW_EXIT_CODE = "O fluxo encerrou com código {code}."
WORKFLOW_DONE = "Workflow concluído"
RUN_STOPPED = "Run parada — dá para retomar de onde parou"
RUN_BLOCKED = "Run bloqueada — resolva o que o step pediu e retome de onde parou"
RUN_RESUMABLE_FROM_FAILURE = "Dá para retomar do step que falhou"
RUN_STOPPING = "Parando — cortando o step em execução"

# Header
HEADER_BRAND = "PULSE // ACP COCKPIT"
HEADER_PIPELINE_BADGE = "SYS.PIPELINE"
HEADER_RUN_EMPTY = "RUN 0/0"
HEADER_STOPPED = "PARADA"
HEADER_AWAITING_INPUT = "PRECISA DE VOCÊ"
CONTEXT_LABEL = "{tokens} tokens"

# Footer
FOOTER_MENU = "MENU"
FOOTER_BACK = "VOLTAR"
FOOTER_FOCUS = "FOCUS"
FOOTER_FOCUS_PHASES = "PHASES"
FOOTER_FOCUS_STREAM = "STREAM"
FOOTER_FOCUS_ARTIFACT = "ARTIFACT"
FOOTER_CLOSE = "FECHAR"
FOOTER_FILE = "FILE"
FOOTER_OPEN = "ABRIR"
FOOTER_STOP = "PARAR"
FOOTER_NAV = "NAV"

# Phase sidebar
SIDEBAR_NO_STEPS = "Nenhum step configurado"

# Log stream
STREAM_DEFAULT_SURFACE = "RUNTIME MODE & WORKSPACE CONFIG SURFACE"
STREAM_HEADER = "{surface} [backend]"
STREAM_META = "{count} entries · step {position}/{total}          {right}"
STREAM_ASSISTANT = "Assistente"
STREAM_WORKFLOW_FAILURE = "Falha no workflow"
STREAM_NO_ACTIVITY = "Nenhuma atividade neste item."
STREAM_WAITING = "Aguardando atividade do agente…"
STREAM_LOADING = "carregando…"
ENTRY_ASSISTANT_TITLE = "Assistant"
NO_PERSISTED_LOGS = "Nenhum log persistido para esta run."
# Artifact pane
ARTIFACT_OPEN_RAIL = "▸\nABRIR"
ARTIFACT_HEADER = "ARTEFATOS  {count}"
ARTIFACT_NONE_IN_PHASE = "Nenhum artefato nesta fase"
ARTIFACT_NONE_IN_PHASE_MARKDOWN = "_Nenhum artefato nesta fase._"
ARTIFACT_LIVE = "live"
ARTIFACT_PAUSED = "paused"
ARTIFACT_WRITING = "escrevendo"
ARTIFACT_WRITING_MARKDOWN = "_Escrevendo `{name}`…_"
ARTIFACT_EMPTY_MARKDOWN = "_`{name}` está vazio._"
ARTIFACT_TRUNCATED = "\n\n[… artefato truncado …]"

# Prompt dock and prompt bridge
PROMPT_BINDING_CANCEL = "Cancel"
PROMPT_DEFAULT_TITLE = "Prompt"
PROMPT_HINT_MULTI_SELECT = "Espaço marca · Enter confirma · Esc cancela"
PROMPT_HINT_SELECT = "↑↓ escolhe · letra vai direto · Enter confirma · Esc cancela"
PROMPT_INPUT_PLACEHOLDER = "Resposta…"
PERMISSION_TITLE = "Permissão"
OTHER_OPTION_PROMPT = "{prompt}\n[Outro — descreva]"

# Confirm modal
CONFIRM_TITLE_REMOVE_FROM_HISTORY = "REMOVER DO HISTÓRICO"
CONFIRM_TITLE_REMOVE_WORKTREE = "REMOVER WORKTREE"

# Resume choice modal
RESUME_TITLE = "WORKFLOW NÃO CONCLUÍDO"
RESUME_STOPPED_AT = "parou em: {summary}"
RESUME_OPTION = "Retomar de onde parou"

# Home
HOME_SUBTITLE = "Orquestrador de agentes de IA · v{version}"
HOME_ROOT_HINT = "↑↓ navega · Enter seleciona · Q sai"
TASK_TITLE_LABEL = "Título"
TASK_TITLE_PLACEHOLDER = "Ex.: Corrigir login com e-mail maiúsculo"
TASK_SLUG_LABEL = "Slug"
TASK_DESCRIPTION_LABEL = "Descrição"
TASK_DESCRIPTION_PLACEHOLDER = "Detalhes da tarefa — cole logs, links ou critérios de aceite"
TASK_CONFIG_LABEL = "Config"
TASK_GIT_WORKTREE = "Auto branch"
TASK_GIT_COMMITS = "Auto commit"
TASK_GIT_PULL_REQUEST = "Auto PR/MR"
TASK_TITLE_REQUIRED = "Dê um título à tarefa."
TASK_PLAIN_PLACEHOLDER = "Descreva a tarefa — cole logs, links ou critérios de aceite"
TASK_MORE_OPTIONS = "Mais opções"
TASK_MORE_OPTIONS_DETAIL = "título, slug e config"
TASK_FEWER_OPTIONS = "Menos opções"
TASK_OPTIONS_SHORTCUT = "ctrl+o"
TASK_KEYS_PLAIN = (
    ("enter", "enviar"),
    ("ctrl+j", "nova linha"),
    ("@", "arquivo"),
    ("esc", "voltar"),
)
TASK_KEYS_DETAILED = (
    ("tab", "próximo campo"),
    ("espaço", "marcar"),
    ("@", "arquivo"),
    ("enter", "enviar"),
    ("esc", "voltar"),
)
HOME_ALERTS_ONE = "{count} sessão precisa de você"
HOME_ALERTS_MANY = "{count} sessões precisam de você"
HOME_ALERTS_HINT = "Enter abre a sessão para responder · Esc volta"
HOME_START_NOW = "Enter inicia agora"
HOME_DESCRIBE_TASK = "Enter para descrever a tarefa"
HOME_SESSION_PROMPT = "Escolha o workflow da tarefa"
HOME_SESSION_STEPS = "{count} etapas"
HOME_SESSION_STEP_ONE = "1 etapa"
HOME_SESSION_STARTS_NOW = "inicia direto"
HOME_SESSION_EMPTY = "Nenhum workflow disponível. Verifique a engine em Configurações."
HOME_SESSION_KEYS = (("↑↓", "navegar"), ("enter", "escolher"), ("esc", "voltar"))
HOME_SETUP = "Configurar Pulse"
HOME_START_ENGINE = "Iniciar a engine"
HOME_ENGINE_STARTING = "Iniciando a engine…"
HOME_ANSWER_ONE = "Responder 1 sessão pendente"
HOME_ANSWER_MANY = "Responder {count} sessões pendentes"
HOME_NEW_SESSION = "Nova sessão"
HOME_HISTORY = "Histórico"
HOME_SETTINGS = "Configurações"
HOME_EXIT_RUNNING_ONE = (
    "[pulse] {count} sessão continua rodando em segundo plano. "
    "Rode `pulse` e abra Histórico para acompanhar."
)
HOME_EXIT_RUNNING_MANY = (
    "[pulse] {count} sessões continuam rodando em segundo plano. "
    "Rode `pulse` e abra Histórico para acompanhar."
)

# History list
HISTORY_BINDING_SEARCH = "Buscar"
HISTORY_TITLE = "Histórico"
HISTORY_COUNT_ONE = "1 run"
HISTORY_COUNT_MANY = "{count} runs"
HISTORY_SEARCH_PLACEHOLDER = "Buscar por título, tarefa, workflow ou status…"
HISTORY_KEYS_LIST = (
    ("↑↓", "navegar"),
    ("enter", "abrir"),
    ("/", "buscar"),
    ("d", "remover"),
    ("esc", "voltar"),
)
HISTORY_KEYS_EMPTY = (
    ("/", "buscar"),
    ("esc", "voltar"),
)
HISTORY_KEYS_SEARCH_EMPTY = (("esc", "sair da busca"),)
HISTORY_KEYS_SEARCH = (
    ("↑↓", "navegar"),
    ("enter", "abrir"),
    ("esc", "sair da busca"),
)
HISTORY_EMPTY = "Nenhuma run neste workspace ainda"
HISTORY_EMPTY_ACTION = "Descreva uma tarefa na tela inicial para começar  ·  esc volta"
HISTORY_NO_MATCH = "Nenhuma run corresponde a “{query}”"
HISTORY_NO_MATCH_ACTION = "esc limpa a busca"
HISTORY_AGE_NOW = "agora"
HISTORY_AGE_MINUTES = "há {count} min"
HISTORY_AGE_HOURS = "há {count} h"
HISTORY_AGE_YESTERDAY = "ontem"
HISTORY_AGE_DAYS = "há {count} dias"
HISTORY_AGE_DATE_FORMAT = "%d/%m/%Y"
HISTORY_DURATION = "duração {duration}"
HISTORY_STEPS = "{done}/{total} etapas"
HISTORY_BRANCH = "⎇ {branch}"
HISTORY_RUN_REMOVED = "Run removida: {title}"
HISTORY_RUN_ALREADY_GONE = "Essa run já não estava mais no histórico"
HISTORY_RUN_IN_USE = "Run mantida no histórico: ela ainda está em andamento"
HISTORY_REMOVE_DETAIL = (
    "Apaga a run, os logs e a lista de artefatos. Os arquivos no workspace ficam."
)
HISTORY_REMOVE_LIVE_WARNING = "Atenção: esta run consta em andamento — remover pode derrubá-la."

# History detail: worktree removal
WORKTREE_KEPT_RUN_ACTIVE = "Worktree mantido — a run está em andamento"
WORKTREE_BRANCH = "Branch: {branch}"
WORKTREE_DIRTY = (
    "Há mudança não commitada aqui. O git vai recusar a remoção — commite ou descarte antes."
)
WORKTREE_CLEAN = "A branch continua no repositório; só o diretório sai."
WORKTREE_REMOVED = "Worktree removido"
WORKTREE_GIT_REFUSED = "Worktree mantido — o git recusou a remoção"

# Onboarding
ONBOARD_TITLE = "CONFIGURAR PULSE"
ONBOARD_WORKSPACE_PLACEHOLDER = "Caminho do workspace…"
ONBOARD_HINT_KEYS = "Enter confirma  ·  Esc cancela"
ONBOARD_CONFIG_EXISTS = "Config já existe"
ONBOARD_RECONFIGURE = "Sim — reconfigurar"
ONBOARD_KEEP = "Não — manter"
ONBOARD_DEFAULT_AGENT = "Agente padrão"
ONBOARD_RUNTIME_OPTION = "{label} — `{binary}`"
ONBOARD_ENVIRONMENT_FOR = "Ambiente — {runtime}"
ONBOARD_QUIT_INSTALL = "Sair — {hint}"
ONBOARD_RETRY = "Tentar de novo"
ONBOARD_AUTH_LATER = "Usar {env_var} depois"
ONBOARD_WORKSPACE_STATUS = "Diretório padrão do workspace"
ONBOARD_WORKSPACE_INPUT = "Caminho absoluto do workspace"
ONBOARD_INVALID_DIRECTORY = "Diretório inválido. Escolha uma pasta existente."
ONBOARD_EXPORT_KEY = "Exporte {env_var} e rode `pulse` de novo."
ONBOARD_OPENING_LOGIN = "Abrindo {login}…"
ONBOARD_LOGIN_FAILED = "Login não concluído"
ONBOARD_TESTING_ACP = "Testando conexão ACP…"
ONBOARD_ACP_CONNECTION = "Conexão ACP"
ONBOARD_CONTINUE_ANYWAY = "Continuar mesmo assim"
ENGINE_UNAVAILABLE_HEADLINE = "Engine indisponível"
ENGINE_REFUSED_HEADLINE = "Engine recusou o pedido"
ONBOARD_RUN_LOGIN = "Executar `{command}`"
ENGINE_UNAVAILABLE = "Engine indisponível: {error}"
ENGINE_REFUSED = "Engine recusou o pedido: {error}"
ONBOARD_READY = "Pronto"
ONBOARD_CONFIG_SAVED = "Config salvo em {path}"

# Settings
SETTINGS_TITLE = "Configurações"
SETTINGS_ROOT_HINT = "O que os agents usam e como as runs tocam o git"
SETTINGS_GLOBAL_LABEL = "Global"
SETTINGS_GLOBAL_DESCRIPTION = "Runtime, modelo e permissões de todos os agents"
SETTINGS_AGENTS_LABEL = "Por agent"
SETTINGS_AGENTS_DESCRIPTION = "Ajusta um agent sem mexer nos outros"
SETTINGS_AGENTS_COUNT = "{count} agents"
SETTINGS_WORKTREE_LABEL = "Worktree"
SETTINGS_WORKTREE_DESCRIPTION = "Isola cada run numa branch própria"
SETTINGS_ATOMIC_LABEL = "Autocommit"
SETTINGS_ATOMIC_DESCRIPTION = "Um commit por entrega"
SETTINGS_ATOMIC_NEEDS_WORKTREE = "Autocommit só liga com o Worktree ligado."
SETTINGS_PR_LABEL = "PR/MR"
SETTINGS_PR_DESCRIPTION = "Abre o pedido no fim da run"
SETTINGS_PR_NEEDS_COMMITS = "PR/MR só liga com o Worktree e o Autocommit ligados."
SETTINGS_DOCTOR_LABEL = "Verificar ambiente"
SETTINGS_DOCTOR_DESCRIPTION = "Runtimes instalados, login e config"
SETTINGS_TOGGLE_ON = "ligado"
SETTINGS_TOGGLE_OFF = "desligado"
SETTINGS_TOGGLE_UNAVAILABLE = "indisponível"
SETTINGS_WORKTREE_ENABLED = (
    "As runs deste projeto passam a rodar num `git worktree` próprio, em "
    "`~/.pulse/worktrees/`, numa branch com o nome da tarefa. A árvore de "
    "trabalho do editor fica intocada."
)
SETTINGS_WORKTREE_DISABLED = (
    "As runs voltam a rodar na árvore de trabalho do projeto. "
    "Autocommit e PR/MR foram desligados. Os worktrees já criados continuam onde estão."
)
SETTINGS_ATOMIC_ENABLED = (
    "Cada entrega de implementação ou correção vira um commit na branch da run."
)
SETTINGS_ATOMIC_DISABLED = "As runs deixam de commitar. PR/MR foi desligado."
SETTINGS_PR_ENABLED = "No fim da run o Pulse abre o pedido no GitHub ou no GitLab."
SETTINGS_PR_DISABLED = "O Pulse deixa de abrir pedido no fim da run."
BRANCH_TITLE = "BRANCH"
BRANCH_CONFIRM = "Confirmar"
BRANCH_TAKEN = "Essa branch já existe. Escolha outro nome."
BRANCH_INVALID = "Nome de branch inválido."
BRANCH_EMPTY = "Informe o nome da branch."
SETTINGS_LOADING_MODELS = "Carregando modelos…"
SETTINGS_LOADING_DOCTOR = "Carregando checks…"
SETTINGS_PICK_MODEL = "Escolha o modelo"
SETTINGS_PICK_POLICY = "Escolha a política de permissões"
SETTINGS_PICK_AGENT = "Escolha o agent a ajustar"
SETTINGS_PICK_RUNTIME = "Escolha o runtime"
SETTINGS_GLOBAL_HINT = (
    "O global sobrescreve todos os agents. Trocar um agent depois vale só para ele."
)
SETTINGS_AGENT_HINT = "Vale só para este agent"
SETTINGS_FIELD_RUNTIME = "Runtime"
SETTINGS_FIELD_MODEL = "Modelo"
SETTINGS_FIELD_PERMISSIONS = "Permissões"
SETTINGS_AGENT_VALUE = "{runtime} · {model}"
SETTINGS_DOCTOR_HINT = "Resultado dos checks deste ambiente"
SETTINGS_DOCTOR_GLOBAL_CONFIG = "Config global · modelo {model}"
SETTINGS_DOCTOR_PROJECT_CONFIG = "Config do projeto · {source}"
SETTINGS_DOCTOR_NO_CHECKS = "Nenhum check"
SETTINGS_KEYS_ROOT = (
    ("↑↓", "navegar"),
    ("enter", "selecionar"),
    ("espaço", "alternar"),
    ("esc", "fechar"),
)
SETTINGS_KEYS_MENU = (
    ("↑↓", "navegar"),
    ("enter", "selecionar"),
    ("esc", "voltar"),
)

# Permission policies, keyed by `PERMISSION_POLICIES`
PERMISSION_LABELS = {
    "ask": "Perguntar antes de cada permissão",
    "auto_approve": "Aprovar automaticamente",
    "deny_writes": "Permitir leitura e artefatos Pulse, bloquear escrita de código",
}
