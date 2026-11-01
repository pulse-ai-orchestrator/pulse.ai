# Pulse

[Português](README.md) | [English](README.en.md)

**Terminal-first AI agent orchestrator over ACP.** Pulse coordinates Cursor, Claude Code, and OpenAI Codex through the [Agent Client Protocol](https://agentclientprotocol.com). It decides which agent runs next and when; workflows, steps, and agents are data stored in SQLite.

[![CI](https://github.com/pulse-ai-orchestrator/pulse.ai/actions/workflows/ci.yml/badge.svg)](https://github.com/pulse-ai-orchestrator/pulse.ai/actions/workflows/ci.yml) · Python 3.11+ · [MIT](LICENSE) · [Discussions](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions)

## Highlights

- Workflows are stored as data, not hard-coded in the engine.
- Each step gets its own ACP session and receives only the previous step summary.
- The daemon owns run state, so runs continue after the terminal UI closes.
- Optional Git worktrees isolate concurrent runs from your editor working tree.
- Local-first storage uses SQLite at ~/.pulse/pulse.db. The Unix socket is user-only; HTTP binds to 127.0.0.1 with a per-start token.

## Installation

Requirements: macOS or Linux (use WSL2 on Windows), Python 3.11+, pipx, and at least one installed and authenticated runtime. Node.js 18+ (npx) is needed for Claude and Codex.

    pipx install git+https://github.com/pulse-ai-orchestrator/pulse.ai.git

## First steps

Run the setup wizard, then open the interactive interface:

    pulse init
    pulse

The wizard checks the runtime executable, authentication, ACP connection, default directory, model, and permission policy. Machine settings are stored in ~/.pulse/pulse.db.

## Supported runtimes

| Runtime | Executable | ACP command | Authentication |
| --- | --- | --- | --- |
| cursor | agent | agent acp | agent login or CURSOR_API_KEY |
| claude | claude | npx -y @agentclientprotocol/claude-agent-acp@0.86.0 | claude /login or ANTHROPIC_API_KEY |
| codex | codex | npx -y @agentclientprotocol/codex-acp@2.1.1 | codex login, CODEX_API_KEY, or OPENAI_API_KEY |

Claude Code and Codex use version-pinned ACP adapters distributed through npm. Each adapter inherits authentication from its corresponding CLI.

## Learn more

- [Architecture](ARCHITECTURE.md)
- [Workflow model](docs/workflows.md)
- [Agent documentation](docs/agentes.md)
- [Logs](docs/logs.md)
- [Questions and MCP](docs/questions.md)
- [Community discussions](https://github.com/pulse-ai-orchestrator/pulse.ai/discussions)
- [Contributing guide](CONTRIBUTING.md)

Distributed under the [MIT License](LICENSE).