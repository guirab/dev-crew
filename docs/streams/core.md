# Stream A — backend-core

> Registro histórico do M1 (2026-10-01). Depois disso o Azure DevOps foi removido (D38, `5573d1b`) e a entrevista virou rodadas (D39); o estado atual está no README e no CLAUDE.md.

Estado: entregue. `uv run pytest -q` (282 testes), `ruff check`, `ruff format` e `mypy src` verdes (mypy strict em `contracts/`, `bus/`, `orchestrator/`).

## O que foi feito

| Área | Arquivos | Notas |
|---|---|---|
| Config | `config.py`, `logging.py` | `crew.toml` (`CREW_CONFIG` > `./crew.toml` > `~/.dev-crew/crew.toml`) validado por pydantic (`extra=forbid`); segredos via `.env` (pydantic-settings, `SecretStr`). Gateway só aceita `127.0.0.1`/`localhost`. `CREW_HOME` muda o diretório de dados (db, logs, worktrees padrão). |
| Máquina | `orchestrator/{machine,state,events,effects,budget}.py` | `decide(state, event) -> (state, effects)` puro (trabalha numa cópia; `state is None` = sem tarefa). Todas as setas do diagrama, limites, cancel em qualquer fase, resultados stale, orçamento, uma tarefa por vez. |
| View | `TaskState.to_view()` | Statuses/arestas mantidos por transição (espelha `go/finish/log` do mockup). Os 8 fixtures de `contracts/fixtures` são reproduzidos por sequências de eventos (`tests/test_orch_view.py`). |
| Serviço | `orchestrator/{service,store,devfakes}.py` | Uma inbox + um worker (decide sempre vê estado consistente). Efeitos lentos (worktree, Azure, relatório) rodam em background e voltam como eventos. Persiste antes de responder ao comando. Recuperação: recarrega do SQLite, republica a view, reemite o passo em voo (`boot`), reativa o timer do job. Timeout de job (`job_timeout_min`). `devfakes.FakeCrew` = agentes fake roteirizados (cenário do mockup). |
| Workspace | `workspace/{git,manager}.py` | `git worktree add -b crew/<task>`, `create` idempotente, fetch best-effort, `diff_report` (`status -z -uall` + `diff --numstat` contra o merge-base, contagem de linhas dos não rastreados), `cleanup` (recusa sujo sem `--force`), modo `inplace`. `task_id` validado (`T-<n>`) contra path traversal. |
| Azure | `azure/{mapping,mcp_client,service,fake}.py` | Sessão MCP stdio única com reconexão; allow-list de tool/action só de leitura (qualquer `*_write` é bloqueada antes de sair do processo); remoção dos marcadores UNTRUSTED; HTML -> Markdown; critérios por `<li>`; ReproSteps de Bug. `--fake-azure`/`CREW_FAKE_AZURE=1` = os 4 itens do mockup. Testado com JSON gravado **e** contra um servidor MCP stdio de verdade (`tests/data/fake_azure_mcp_server.py`), incluindo reconexão após crash. |
| Gateway | `gateway/{app,hub}.py` | `GET /api/repos`, `GET /api/azure/work-items`, `GET /api/task`, `POST /api/commands` (409 conflito de estado, 422 validação, 503 serviço fora), `WS /ws` (snapshot -> atualizações sem janela de corrida; consumidor lento é ressincronizado). Allow-list de `Host` (DNS rebinding), checagem de `Origin` em WS e POST, CORS só pro Vite, sem `/docs`. Serve `frontend/dist` se existir. |
| CLI | `cli.py`, `stack.py`, `doctor.py` | `up`, `svc`, `doctor`, `cleanup` + flags `--fake-agents --fake-azure --fake-speed --fake-escalate`. `stack.py` = composition root; cada serviço roda sob supervisor (reinicia com backoff). |

## Como rodar

```bash
cd backend && uv sync
uv run pytest -q          # precisa de nats-server no PATH (testes -m nats pulam sem ele)
uv run ruff check . && uv run mypy src
```

```bash
uv run crew doctor                      # explica o que falta
uv run crew up --fake-agents --fake-azure --fake-speed 4
```

Depois `GET http://127.0.0.1:8787/api/task`, `POST /api/commands`, `WS /ws`. `--fake-escalate` faz o Tester falhar 3x (escalada). Serviços isolados: `crew svc orchestrator|gateway|azure|agent:<nome>`. `crew cleanup T-7 [--force]` remove o worktree.

## Interface com o Stream B

`stack.load_agent_runtime()` importa `crew.agents.service.run_agent` e `crew.agents.settings.AgentRuntimeSettings` de forma lazy (só `ModuleNotFoundError` desses dois módulos cai no fallback; erro de import dentro do código do B aparece). Chama `run_agent(bus, agent, settings=AgentRuntimeSettings(model, fake, fake_speed, fake_escalate), stop=stop)` com um supervisor em volta. Sem o módulo: `--fake-agents` usa `devfakes.FakeCrew`; sem `--fake-agents` o `crew up` falha com mensagem clara. `--builtin-fakes` (oculto) força o `FakeCrew` mesmo com o Stream B presente. Para agentes reais o `ANTHROPIC_API_KEY` do `.env` é exportado pro ambiente (o Agent SDK lê do env).

O orquestrador monta `AgentJob` com `RepoContext` do `crew.toml`, `workspace_path`, `resume_session_id` por agente (vindo de `AgentResultEvt.session_id`) e `budget_usd` restante; `job_id` é `uuid5` determinístico (dedupe do JetStream).

## Decisões / desvios do plano

- **Estado `None` + `TaskState` mutável pydantic**: `decide` aceita `TaskState | None`; rejeições viram o efeito `Reject(error)` (estado inalterado) e o serviço responde `CommandReply(ok=False)`.
- **Worktree criado no início da tarefa** (antes do Planner/Entrevistador), não só na aprovação: os agentes já têm `workspace_path` e uma falha de repo aparece cedo (fase `failed`). No Azure a ordem é work item -> worktree -> Planner.
- **Contadores**: `dev_round`/`review_round` contam jobs despachados (como nos fixtures); um job que morre devolve a rodada. `test_attempt` conta falhas consecutivas. `instruct` após limite zera o ciclo do limite que estourou (`test_attempt` ou `review_round`); `replan` zera `test_attempt` e `review_round` (não `dev_round`, pra manter `DevResult.round` único) e descarta sessões de developer/tester/reviewer.
- **Escalada por orçamento**: `stage` = o agente que não pôde ser despachado; `more_attempts` libera `max(+50%, gasto + 50% do orçamento)` e retoma o job pendente; `instruct`/`replan` são recusados (409) enquanto o orçamento estiver estourado.
- **Escalada por falha de agente** guarda o job que falhou: `more_attempts` reexecuta igual; `instruct` manda o Developer (ou re-roda Planner com o texto); `replan` indisponível se a falha foi do Entrevistador.
- **Review**: `approved` com comentário `major` não resolvido é tratado como `changes_requested`; `approved` sem `commit_message` ganha fallback conventional (`fix:` pra Bug, senão `feat:`). Na aprovação, comentários de rodadas anteriores vão `resolved=true` no `review` final (como no fixture `done`).
- **Fim da tarefa em dois passos**: aprovação -> `BuildFinalReport` (I/O) -> `ReportBuilt` -> `done`. Se o diff falhar, o relatório sai com `files=[]` e a tarefa conclui mesmo assim.
- **Progresso** só atualiza `now`/logs em memória (sem view nem persist por linha); o gateway repassa o `progress` direto do bus.
- **CORS** aceita também `http://127.0.0.1:5173` (além de `localhost:5173`).
- Dois bugs do M0 contornados e registrados em `docs/contract-requests.md`: `Bus.consume`/`job_loop` morrem com `asyncio.TimeoutError` solto do `fetch`, e `Bus.request` não trata `NoRespondersError`.
- Marcadores UNTRUSTED do Azure: o formato exato não pôde ser confirmado em fonte oficial (README/`utils.ts` não mostram). O `mapping` remove de forma tolerante `<<id>>`/`<</id>>` e `[UNTRUSTED ... ]` e, se o JSON ainda não parsear, extrai o maior objeto/array. **Validar no M4 com um work item real.**

## Pendências

- M4: rodar `crew doctor`/`crew up` contra o Azure real (PAT) e conferir formato dos marcadores, shape do WIQL/`get_batch` e `@CurrentIteration` com `team`. Mapping foi testado só com payloads gravados à mão + servidor MCP fake.
- Aplicar no `bus/` as correções de `contract-requests.md` (o supervisor e o pull loop próprio podem sair depois).
- Stream B precisa rodar seu worker sob o mesmo tipo de supervisor até o `bus` ser corrigido (já é assim quando entra pelo `crew up`).
- Cobertura de 100% da máquina não foi medida com ferramenta (pytest-cov fora das deps); a tabela cobre cada transição/guarda listada acima.
- Cancelamento deixa o worktree no disco (de propósito: inspeção); remover com `crew cleanup`.
- `GET /api/azure/work-items` pode levar até ~2 min na primeira chamada (spawn do `npx`); o front deve mostrar loading.
