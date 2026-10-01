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
