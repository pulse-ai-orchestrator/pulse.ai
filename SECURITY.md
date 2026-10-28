# Política de segurança

O Pulse inicia processos de agentes, roda git, abre um servidor HTTP local e
guarda os prompts do usuário. Levamos relatos de segurança a sério.

## Versões suportadas

O projeto ainda está antes da 1.0: só a versão mais recente da branch `main`
recebe correções de segurança.

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use um destes canais privados:

1. [Reportar pelo GitHub](https://github.com/pulse-ai-orchestrator/pulse.ai/security/advisories/new)
   (aba *Security* → *Report a vulnerability*). É o canal preferido.
2. E-mail para jonathanmatos1997@hotmail.com, com `[pulse security]` no assunto.

Inclua, se possível:

- versão ou commit do Pulse, sistema operacional e runtime (Cursor, Claude Code ou Codex);
- passos para reproduzir e o impacto esperado;
- uma prova de conceito, se tiver.

## O que esperar

- Confirmação de recebimento em até 3 dias úteis.
- Uma avaliação inicial e um plano de correção em até 10 dias úteis.
- Crédito no aviso de segurança, se você quiser.

## Escopo

Interessam especialmente:

- execução de comando ou escrita de arquivo fora do workspace da run;
- caminhos vindos do agente ou da API que escapam do worktree (`..`, symlink);
- acesso ao daemon por outro usuário ou pela rede, ou requests vindas de navegador;
- texto do agente que consegue mudar política de permissões, config ou qual agente roda;
- vazamento de credenciais (`ANTHROPIC_API_KEY`, `CURSOR_API_KEY`, …) em logs, eventos ou no banco.

Ficam fora de escopo vulnerabilidades dos próprios runtimes (Cursor, Claude
Code, Codex) e dos adapters ACP: reporte-as aos respectivos projetos.
