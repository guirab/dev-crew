# Stream B: agentes (backend-agents)

> Registro histórico do M1 (2026-10-01). Depois disso o Azure DevOps foi removido (D38, `5573d1b`) e a entrevista virou rodadas (D39); o estado atual está no README e no CLAUDE.md.

Branch: `worktree-agent-a0b754394976f32b9` · base: M0 (`4188f9c`). Plano: `plan/03-backend-agents.md`.

## Feito

| Item | Onde |
|---|---|
| Spike S0 (introspecção, handshake com a CLI real, script com modo `--live`) | `docs/spikes/agent-sdk.md`, `backend/scripts/spike_sdk.py` |
| Tool `submit_*` validada por Pydantic + checagens semânticas + captor | `agents/submit.py`, `agents/specs.py` |
| Progresso determinístico + throttle (1 evento/300 ms) | `agents/progress.py` |
| Guardas `PreToolUse` (Bash, paths, Tester só testes, Reviewer/Planner somente leitura) | `agents/guards.py`, `agents/pathjail.py`, `agents/shellparse.py` |
| Prompt do job (seções fixas, work item como dado não confiável) e prompts dos 5 agentes + `_shared.md` | `agents/context.py`, `agents/prompts/*.md` |
| `SdkRunner` (ClaudeSDKClient, hooks, submit, follow-up x2, resume com fallback, custo, erros -> bus) | `agents/runner.py` |
| `ScriptedRunner` (cenário do mockup, edita arquivos de verdade) | `agents/fake.py` |
| Worker: `run_agent(bus, agent, *, settings, stop)`, cancel por `crew.ctl.<task>.cancel` | `agents/service.py`, `agents/settings.py` |
| `python -m crew.agents <nome>` | `agents/__main__.py` |
| `crew agent try <agente> --job <json> [--fake]` | `agents/cli.py` |
| Sample repo + script para virar repo git + jobs de exemplo | `fixtures/sample-repo/`, `backend/scripts/init_sample_repo.py`, `fixtures/jobs/*.json`, `backend/scripts/make_job_fixtures.py` |

Testes (`backend/tests/agents/`): ~1850 casos, a maioria em tabela nas guardas (Windows e POSIX); worker com `nats-server` real (um job por agente, cancelamento -> `failed`, retry, fatal, crash, processo `python -m crew.agents`); runner com cliente fake; wire test do servidor MCP in-process; testes `live` pulados sem chave.

## Como rodar

```bash
cd backend
uv sync
uv run pytest -q              # sem -m live; os testes de NATS precisam do nats-server no PATH
uv run ruff check . && uv run mypy src
uv run python scripts/spike_sdk.py          # spike offline
uv run python scripts/spike_sdk.py --cli    # + handshake com a CLI real (sem prompt)
```

Agente isolado, sem NATS, zero tokens (trabalha numa cópia git temporária do sample repo):

```bash
uv run crew agent try planner --job ../fixtures/jobs/planner.json --fake
uv run crew agent try tester --job ../fixtures/jobs/tester.json --fake --escalate
```

Agente real (precisa de `ANTHROPIC_API_KEY` e do `claude.exe` nativo):

```bash
uv run crew agent try planner --job ../fixtures/jobs/planner.json
uv run pytest -m live -q
```

Worker standalone (o orquestrador/`crew up` do Stream A usa `run_agent` direto):

```bash
CREW_NATS_URL=nats://127.0.0.1:4222 CREW_FAKE_AGENTS=1 uv run python -m crew.agents planner
```

Variáveis: `CREW_NATS_URL`, `CREW_MODEL_<AGENT>`, `CREW_FAKE_AGENTS`, `CREW_FAKE_SPEED` (como o mockup: 2.0 = 2x mais rápido, 1000 = instantâneo), `CREW_FAKE_ESCALATE`, `CREW_MAX_TURNS`, `CREW_CLAUDE_CLI`.

## Desvios do plano

1. **Git allowlist** em vez de denylist: só `status`, `diff`, `log`, `show`, `blame`, `ls-files`, `rev-parse`... (e `branch/tag/remote` em modo lista). `git add` também é negado (o resultado fica sem stage).
2. **Guardas além do plano:** leitura confinada ao worktree e bloqueio de arquivos sensíveis (`.env`, chaves, `.ssh`), variáveis `*_KEY/TOKEN/SECRET`, `printenv`/`env`, `eval`, `xargs`, `find -exec/-delete`, shells por stdin, `npx` sem `--no-install`, `uv run --with`, junctions/symlinks (realpath), `{a,b}`. Default-deny para tools fora da lista e `disallowed_tools` (inclui `PowerShell`).
3. **Planner e Reviewer** usam o mesmo conjunto de leitura (`ls`, `cat`, `grep`, `rg`, `find` sem ação, `git` de leitura...), não só `git log`/`ls`.
4. **Developer/Tester** mantêm a denylist do plano para comandos comuns; escrita via Bash (redirecionamento, `tee`, `sed -i`, `cp`/`mv`...) é confinada ao worktree e, no Tester, aos globs de teste.
5. **`system_prompt`** é o preset `claude_code` + `append` (não só `_shared.md + agente.md`). Validar com chave.
6. **`dataclass`/finalizers determinísticos**: `DevResult.round = job.attempt`, `Refs: AB#<id>` no commit, identidade da spec do Entrevistador (`source`, `repo`, `work_item`) vem do job; `TestResult.command` cai para `repo.test_cmd`.
7. **Reviewer:** só `major` não resolvido bloqueia `approved` (comentários antigos voltam `resolved=true` na rodada 2).
8. **`run_agent`** aceita dois kwargs opcionais extras (`runner`, `heartbeat_s`) usados pelos testes; a assinatura combinada com o Stream A continua válida.
9. **`init_sample_repo`** foi extraído para `crew.agents.sample` (o script em `backend/scripts/` é um wrapper) para o `crew agent try` reutilizar.
10. `jsonschema` (dependência transitiva do SDK) é usado nos testes sem estar declarado no `pyproject.toml`.

## Pendências

Ver `docs/spikes/agent-sdk.md` ("Fica pra validar com chave") e `docs/contract-requests.md` (pedidos ao núcleo). Resumo:

- **Precisa da API key** (`-m live`): respeito da CLI ao `deny` do hook, Bash/Git Bash no Windows, `ENV_SCRUB`, nome final `mcp__crew__submit_*`, follow-up de submit, `resume`, `total_cost_usd` cumulativo, cache, `max_budget_usd`, preset vs string, `interrupt()`.
- **Ajuste fino dos prompts** rodando `crew agent try` real no sample repo (M3).
- **Ambiente Windows:** wheel do SDK sem CLI embutida (usar `claude.exe` nativo ou fixar a 0.2.159); `crew doctor` deve checar.
- **Núcleo (A):** preencher `workspace_path` também para Entrevistador/Planner; guardar/reenviar `session_id`; checar diff do Tester; cancel antes do job começar.
- **Isolamento real** (sandbox/Docker): M5.
