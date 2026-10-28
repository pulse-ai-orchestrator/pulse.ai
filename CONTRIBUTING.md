# Contribuindo com o Pulse

Obrigado pelo interesse! Toda contribuição conta: uma dúvida bem descrita, um
bug reproduzível, uma correção na documentação ou um PR com código novo.

Ao participar, você concorda com o nosso [Código de Conduta](CODE_OF_CONDUCT.md).

## Por onde começar

| Quero… | Onde |
| --- | --- |
| Tirar uma dúvida ou pedir ajuda | [Discussions → Dúvidas](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/q-a) |
| Sugerir uma ideia ou um workflow novo | [Discussions → Ideias](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/ideas) |
| Mostrar como você usa o Pulse | [Discussions → Show and tell](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions/categories/show-and-tell) |
| Reportar um bug | [Abrir uma issue](https://github.com/pulse-ai-orchestrator/pulse.ai/issues/new/choose) |
| Reportar uma vulnerabilidade | Em privado, nunca em issue pública: veja [`SECURITY.md`](SECURITY.md) |
| Fazer a primeira contribuição | Issues com [`good first issue`](https://github.com/pulse-ai-orchestrator/pulse.ai/labels/good%20first%20issue) |

Antes de começar algo grande (um runtime novo, uma mudança no motor, uma rota
nova na API), abra uma discussão em **Ideias** ou comente na issue. Assim a
gente alinha o desenho antes de você investir tempo no código.

## Preparando o ambiente

Requisitos: macOS ou Linux (no Windows, use o WSL2), Python 3.11+ e
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/pulse-ai-orchestrator/pulse.ai.git
cd pulse.ai
uv sync && uv run pre-commit install
uv run pytest tests/<pacote>/
```

Para rodar a CLI a partir do clone: `uv run pulse`. Não é preciso ter um
runtime de agente instalado para rodar os testes: a suíte não chama nenhum CLI
real nem a rede.

## Antes de abrir o PR

1. Leia o [`AGENTS.md`](AGENTS.md). Ele resume as regras de arquitetura,
   código e testes que valem para humanos e para agentes. O
   [`ARCHITECTURE.md`](ARCHITECTURE.md) explica as camadas e o glossário.
2. Crie uma branch a partir da `main`.
3. Todo comportamento novo ou bug corrigido vem com um teste que falha sem a
   mudança.
4. Rode as mesmas checagens do CI:

   ```bash
   uv run pytest --cov
   uv run ruff check . && uv run ruff format --check .
   uv run mypy
   uv run vulture
   uv run lint-imports
   uv run deptry .
   ```

5. Atualize a documentação no mesmo PR quando mudar comportamento, rotas,
   eventos ou tabelas.

As regras que mais pegam quem está chegando:

- O motor não conhece workflows específicos. Nada de `if workflow_id == ...`:
  comportamento novo vira coluna nas tabelas de definição.
- Código, identificadores, mensagens de log e nomes de teste em inglês. Texto
  de tela e documentação podem ser em português.
- Nenhum arquivo passa de 700 linhas, e nenhuma supressão (`# noqa`,
  `# type: ignore`) entra sem o código da regra e o motivo.

## Commits e PRs

- Use [conventional commits](https://www.conventionalcommits.org/) em inglês,
  no imperativo: `feat(cli): add --json to doctor`, `fix(vcs): …`, `docs: …`.
- Um assunto por commit e por PR. PRs pequenos são revisados mais rápido.
- Preencha o [template de PR](.github/pull_request_template.md) e aponte o
  teste que prova cada afirmação.
- O CI precisa estar verde. Se travar em algo que você não entende, peça ajuda
  no próprio PR: ninguém precisa resolver tudo sozinho.

## Licença

Ao contribuir, você concorda que sua contribuição será distribuída sob a
[licença MIT](https://github.com/pulse-ai-orchestrator/pulse.ai/blob/main/LICENSE)
do projeto.
