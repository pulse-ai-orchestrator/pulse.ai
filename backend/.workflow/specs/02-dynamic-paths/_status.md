---
phase: 02-dynamic-paths
branch: feat/pulse-specs/02-dynamic-paths
status: completed
---

# Status — Fase 02-dynamic-paths

## Resultado

- `DEFAULT_PROJECT_PATH` removido de `types.py` e exports públicos
- `project_path` obrigatório em `RunCursorTaskOptions`, `ExecuteTasksOptions`, CLI e API (`run_prd_task`, `run_techspec_task`, `run_tasks_task`)
- `_require_project_path` valida ausência/vazio com mensagem acionável em PT-BR
- `_run_task` e `run_execute_tasks_loop` validam existência e tipo de diretório
- `artifacts_path` mantém default do package root (decisão documentada no README)
- README atualizado com breaking change e exemplos corretos
- Testes de validação de `project_path` adicionados em `test_cursor_task.py`

## Validação

```
pytest: 56 passed in 0.18s
```
