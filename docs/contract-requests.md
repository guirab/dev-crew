# Pedidos de mudança de contrato

Contratos estão congelados desde o M0 (`backend/src/crew/contracts/`, `backend/src/crew/bus/subjects.py`, `contracts/`).
Precisou mudar? Adicione uma entrada abaixo, siga com workaround local e avise. A sessão principal aplica e regenera tipos.

Formato:

```
## <data> · <stream> · <título curto>
- O quê:
- Por quê:
- Proposta (código):
- Workaround atual:
```

---

## Desvios do M0 em relação ao plano (já aplicados)

- `Envelope.payload` é `dict` + `type` (`progress|result|failed|view`), decodificado por `Envelope.decode_payload()` em vez de `Envelope[T]` genérico.
- Toda saída de agente tem campo discriminador `type` (`interview|plan|dev|test|review`) → `AgentOutput` é união discriminada.
- `TaskView.stages` é um modelo `Stages` com os 9 campos explícitos (não dict) — tipagem melhor no TS.
- `TaskView.description` adicionado.
- `ReviewComment.resolved` adicionado.
- Mensagens WS: `WsView{type:"view", data}` e `WsProgress{type:"progress", task_id, data}` (união `WsMessage`).
- `RepoInfo{name, base_branch}` pra `GET /api/repos`.
- Fixtures: `planning` no lugar de `idle` (sem tarefa = `view: null`).
- `bus/client.py` + `bus/worker.py` + `crew streams init` entregues no M0 (Streams A e B dependem só do M0).

---

## 2026-10-01 · Stream B (agents) · Pedidos e pontos de atenção para o núcleo / M2

> **Status M2 (sessão principal):** 1 ✅ `crew doctor` checa `claude.exe` (aceita `CREW_CLAUDE_CLI`, recusa shim `.cmd`) · 2 ✅ orquestrador já preenche `workspace_path` (worktree criado no início) pra todos · 3 ✅ `sessions` por agente → `resume_session_id` · 4/5 ok · 6 ✅ cancel publica `crew.ctl` **e** faz purge dos jobs enfileirados · 7/8 → M5.

Nenhum contrato foi alterado. Itens abaixo são decisões que o Stream A / sessão principal precisa conhecer.

1. **Windows: o wheel do `claude-agent-sdk` não traz a CLI.** O PyPI não tem wheel `win_amd64` nas versões 0.2.157 e 0.2.160-0.2.163 (existe até a 0.2.159); o `uv.lock` só lista wheels de macOS/Linux, então no Windows o uv instala o wheel puro sem `_bundled/claude.exe`. O SDK cai para o `claude.exe` nativo (`~/.local/bin/claude.exe` ou PATH). O runner aceita `CREW_CLAUDE_CLI=<caminho>`.
   - Proposta: `crew doctor` checa `claude.exe` (versão >= 2.0.0) e Git Bash; ou fixar `claude-agent-sdk==0.2.159` no `pyproject.toml` (dono: A) se quiserem a CLI embutida.
2. **`AgentJob.workspace_path` é obrigatório para todos os agentes**, inclusive Entrevistador e Planner (o runner falha com `FatalJobError` se vier `None`). `RepoContext` não tem o caminho do repo base.
   - Proposta: o orquestrador sempre preenche `workspace_path` (repo base para Entrevistador/Planner, worktree para os demais), ou adicionar `RepoContext.path`.
3. **Sessões:** o orquestrador deve guardar `AgentResultEvt.session_id` por agente e devolvê-lo em `AgentJob.resume_session_id`. O runner só usa `resume` quando há informação nova (feedback ou, no Entrevistador, uma resposta) e recai para prompt completo se a sessão não puder ser retomada.
4. **`ReviewResult`:** só `major` **não resolvido** (`resolved=false`) bloqueia `approved`. Na rodada 2 os comentários antigos voltam com `resolved=true`. O agente já acrescenta `Refs: AB#<id>` ao `commit_message` quando a tarefa vem do Azure; o orquestrador não deve duplicar.
5. **`DevResult.round`** é forçado pelo agente a `job.attempt`; `TestResult.command` vem de `repo.test_cmd` quando o agente deixa vazio.
6. **Cancelamento** (`crew.ctl.<task>.cancel`) é core pub/sub, não durável: se o cancel for publicado antes do worker assinar (job ainda na fila), ele não vale. O orquestrador deve republicar ou não despachar jobs de tarefa cancelada.
7. **Tester só escreve testes** é garantido pelas guardas nas tools `Write`/`Edit` e nos comandos Bash que escrevem, mas um programa (`python script.py`) pode escrever onde quiser dentro do worktree. Proposta para o M2: o workspace service compara o diff pós-Tester e reporta arquivos de produção alterados.
8. **Isolamento real** (Docker / `sandbox` do SDK) segue como item do M5: as guardas são filtro de política, não sandbox (ver `docs/spikes/agent-sdk.md`).

## 2026-10-01 · core · `Bus.consume` e `job_loop` morrem com `asyncio.TimeoutError` solto do `fetch` — ✅ aplicado na main (b53af45)

- O quê: `psub.fetch()` do nats-py 2.16 pode levantar `asyncio.TimeoutError` puro (ex.: `raise asyncio.TimeoutError` quando o deadline já passou, ou re-raise do `next_msg`), não só `nats.errors.TimeoutError`. `Bus.consume` e `job_loop` só capturam `nats.errors.TimeoutError`, então o loop morre depois de ~1s ocioso. Reproduzido no stream A: o consumer do orquestrador morreu em ~1s sem mensagens (task terminou com `TimeoutError()`).
- Por quê: afeta todo worker de agente (Stream B) que usa `job_loop`: o worker some em silêncio quando fica ocioso.
- Proposta (código): em `bus/client.py` (`consume`) e `bus/worker.py` (`job_loop`) trocar `except NatsTimeoutError:` por `except (NatsTimeoutError, TimeoutError):` (em py3.11+ `asyncio.TimeoutError is TimeoutError`).
- Workaround atual: o orquestrador usa um pull loop próprio (`OrchestratorService._consume_results`) e os fakes (`devfakes.FakeCrew._loop`) reiniciam o `job_loop` quando ele sai com `TimeoutError`. No `crew up`, cada agente roda sob um supervisor que reinicia o worker se ele cair (`stack.supervise`). Stream B deve aplicar o mesmo supervisor até o `bus` ser corrigido.

## 2026-10-01 · core · `Bus.request` não trata `NoRespondersError` — ✅ aplicado na main (b53af45)

- O quê: `Bus.request`/`request_raw` só convertem `TimeoutError` em `BusError`. Sem ninguém escutando o subject, o NATS responde 503 e o nats-py levanta `nats.errors.NoRespondersError` (não é `BusError`).
- Proposta: capturar `NoRespondersError` e levantar `BusError("no responders on <subject>")`.
- Workaround atual: o gateway captura `BusError` e `NoRespondersError` e responde 503.

## 2026-10-01 · front · Pedidos do Stream C (nenhum bloqueante; o front já segue com workaround)

### 1. Documentar a unidade de `TestResult.coverage` — ✅ `Field(ge=0, le=1)` fração 0..1
- O quê: `coverage: float | None` não diz se é fração (0.87) ou percentual (87). As fixtures usam fração.
- Por quê: o front formata `Math.round(coverage * 100)%`. Se o orquestrador mandar 87, a UI mostra 8700%.
- Proposta: docstring/`Field(ge=0, le=1, description="fração 0..1")` em `TestResult.coverage`.
- Workaround atual: front assume fração (como nas fixtures).

### 2. Confirmar o protocolo de "Nova tarefa" depois de `done`/`cancelled` — ✅ confirmado no M2: fase terminal não bloqueia `start_task` (testado via gateway real)
- O quê: o front trata "Nova tarefa" como ação só de UI (dispensa o `task_id` terminal e mostra os cards de origem). Pressupõe que `start_task` é aceito quando a tarefa atual está em fase terminal (`done`/`cancelled`/`failed`), e que `GET /api/task` e o WS continuam devolvendo a última tarefa até uma nova começar.
- Por quê: o contrato só cita 409 "se já existe task ativa"; não diz se terminal conta como ativa.
- Proposta: documentar no gateway/orquestrador que fase terminal não bloqueia `start_task`. Alternativa: publicar `view: null` após o usuário dispensar (exigiria um comando novo; não pedido).
- Workaround atual: `dismissedTaskId` no store do front. Recarregar a página mostra a tarefa terminal de novo.

### 3. Snapshot inicial no WS — ✅ gateway manda `{type:"view"}` ao conectar
- O quê: o front aceita os dois comportamentos (gateway manda `{type:"view"}` ao conectar ou não). Ao abrir/reabrir o WS ele também faz `GET /api/task`; o resultado só vale se nenhum snapshot do WS chegou no meio.
- Proposta: documentar a escolha. Mandar o snapshot ao conectar economiza o GET.

### 4. Semântica de `Counters.test_attempt`
- O quê: o front mostra `tester n/max` quando `test_attempt > 0`. A fixture `done` tem `test_attempt: 0` (falhas consecutivas zeradas após passar), então o tag do Tester some em `done`. O mockup mostrava o contador também depois de passar.
- Proposta: se quiser o contador visível no fim, expor um `test_runs` count (já existe `len(test_runs)`) e o front passa a usar isso. Sem urgência.

### 5. Tipagem de `TaskView.edges` e `Escalation.stage`
- O quê: o gerador produziu `edges: {[k: string]: "on"|"active"}` (perde `EdgeKey`) e `Escalation.stage` com os 5 agentes (o plano dizia 3).
- Proposta: `dict[EdgeKey, EdgeStatus]` com chaves opcionais e `Literal["tester","reviewer","developer"]` em `Escalation.stage`; ou ajustar o gerador de tipos.
- Workaround atual: aliases derivados em `frontend/src/contracts/aliases.ts`.

### 6. Rótulo "+2 tentativas"
- O quê: o botão da escalada diz "+2 tentativas" (texto do mockup), mas o valor real é decisão do orquestrador (`more_attempts` não carrega número).
- Proposta: se o incremento for configurável, expor em `Escalation` (ex.: `extra_attempts: int`) pro front rotular sem hardcode.
