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

## 2026-10-01 · core · `Bus.consume` e `job_loop` morrem com `asyncio.TimeoutError` solto do `fetch`

- O quê: `psub.fetch()` do nats-py 2.16 pode levantar `asyncio.TimeoutError` puro (ex.: `raise asyncio.TimeoutError` quando o deadline já passou, ou re-raise do `next_msg`), não só `nats.errors.TimeoutError`. `Bus.consume` e `job_loop` só capturam `nats.errors.TimeoutError`, então o loop morre depois de ~1s ocioso. Reproduzido no stream A: o consumer do orquestrador morreu em ~1s sem mensagens (task terminou com `TimeoutError()`).
- Por quê: afeta todo worker de agente (Stream B) que usa `job_loop`: o worker some em silêncio quando fica ocioso.
- Proposta (código): em `bus/client.py` (`consume`) e `bus/worker.py` (`job_loop`) trocar `except NatsTimeoutError:` por `except (NatsTimeoutError, TimeoutError):` (em py3.11+ `asyncio.TimeoutError is TimeoutError`).
- Workaround atual: o orquestrador usa um pull loop próprio (`OrchestratorService._consume_results`) e os fakes (`devfakes.FakeCrew._loop`) reiniciam o `job_loop` quando ele sai com `TimeoutError`. No `crew up`, cada agente roda sob um supervisor que reinicia o worker se ele cair (`stack.supervise`). Stream B deve aplicar o mesmo supervisor até o `bus` ser corrigido.

## 2026-10-01 · core · `Bus.request` não trata `NoRespondersError`

- O quê: `Bus.request`/`request_raw` só convertem `TimeoutError` em `BusError`. Sem ninguém escutando o subject, o NATS responde 503 e o nats-py levanta `nats.errors.NoRespondersError` (não é `BusError`).
- Proposta: capturar `NoRespondersError` e levantar `BusError("no responders on <subject>")`.
- Workaround atual: o gateway captura `BusError` e `NoRespondersError` e responde 503.
