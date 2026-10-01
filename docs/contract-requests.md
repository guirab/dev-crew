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

## 2026-10-01 · core · `Bus.consume` e `job_loop` morrem com `asyncio.TimeoutError` solto do `fetch` — ✅ aplicado na main (b53af45)

- O quê: `psub.fetch()` do nats-py 2.16 pode levantar `asyncio.TimeoutError` puro (ex.: `raise asyncio.TimeoutError` quando o deadline já passou, ou re-raise do `next_msg`), não só `nats.errors.TimeoutError`. `Bus.consume` e `job_loop` só capturam `nats.errors.TimeoutError`, então o loop morre depois de ~1s ocioso. Reproduzido no stream A: o consumer do orquestrador morreu em ~1s sem mensagens (task terminou com `TimeoutError()`).
- Por quê: afeta todo worker de agente (Stream B) que usa `job_loop`: o worker some em silêncio quando fica ocioso.
- Proposta (código): em `bus/client.py` (`consume`) e `bus/worker.py` (`job_loop`) trocar `except NatsTimeoutError:` por `except (NatsTimeoutError, TimeoutError):` (em py3.11+ `asyncio.TimeoutError is TimeoutError`).
- Workaround atual: o orquestrador usa um pull loop próprio (`OrchestratorService._consume_results`) e os fakes (`devfakes.FakeCrew._loop`) reiniciam o `job_loop` quando ele sai com `TimeoutError`. No `crew up`, cada agente roda sob um supervisor que reinicia o worker se ele cair (`stack.supervise`). Stream B deve aplicar o mesmo supervisor até o `bus` ser corrigido.

## 2026-10-01 · core · `Bus.request` não trata `NoRespondersError` — ✅ aplicado na main (b53af45)

- O quê: `Bus.request`/`request_raw` só convertem `TimeoutError` em `BusError`. Sem ninguém escutando o subject, o NATS responde 503 e o nats-py levanta `nats.errors.NoRespondersError` (não é `BusError`).
- Proposta: capturar `NoRespondersError` e levantar `BusError("no responders on <subject>")`.
- Workaround atual: o gateway captura `BusError` e `NoRespondersError` e responde 503.
