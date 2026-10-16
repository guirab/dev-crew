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

## 2026-10-16 · UI v6 · Tela Alterações durante a execução e por épico — pendente
- O quê: a tela Alterações do `mockup/v6-linha-do-tempo.html` (D78) mostra a árvore de arquivos + diff a qualquer momento da tarefa, com filtro por épico. Hoje `FileDiff` e `GET /api/tasks/{id}/diff?path=` só cobrem os arquivos do `FinalReport` (fase `done`).
- Por quê: com o "rodada por rodada" fora da tela, o diff vira o único jeito de ver o que os agentes estão fazendo.
- Proposta (código): `GET /api/tasks/{id}/files?epic=` (lista `path`, `status`, `added`, `removed`, `epic_id`) calculada do worktree da tarefa ou do épico; `diff?path=&epic=` aceita o mesmo filtro.
- Workaround atual: nenhum; até lá a tela Alterações só aparece em `done`, com os arquivos do `FinalReport`.

## 2026-10-14 · UI v4 · Diff inline no resultado e reabrir tarefa do Histórico — ✅ aplicado (exceção ao congelamento, como D38/D39)

Dois itens que a UI v4 (D73–D74, `mockup/v4-ux.html`) deixou de fora por pedirem dado novo do backend. Os dois são só leitura, sem comando novo, sem subject novo e sem mudar `TaskView`/`FinalReport`.

### A. Patch de um arquivo do resultado

- O quê: na tela de resultado (`DoneBody`) clicar num arquivo e ver o patch dele. Hoje `FinalFile` só tem `path`, `status`, `added`, `removed`.
- Por quê: revisar o que o dev-crew mudou sem sair do app (é o passo antes de commitar).
- Proposta (código):
  - Modelo novo em `contracts/history.py`:
    ```python
    class FileDiff(Contract):
        path: str
        status: FileChange
        patch: str  # unified diff vs. a base da tarefa; vazio quando binary
        binary: bool = False
        truncated: bool = False  # patch cortado em MAX_PATCH_BYTES, numa quebra de linha
    ```
  - Endpoint novo `GET /api/tasks/{task_id}/diff?path=<rel>` → `FileDiff`. O gateway lê o `TaskState` do SQLite (como `GET /api/tasks`), pega `final.worktree_path` e roda git de leitura no host (D41), com a mesma base do `diff_report` (`merge-base HEAD <base_branch>`, inclui commits dos épicos e alterações não commitadas). Arquivo não rastreado sai como adição (`git diff --no-index`). A lógica fica no `WorkspaceManager` (`file_patch`), ao lado do `diff_report`.
  - Segurança: `path` só é aceito se estiver em `final.files` da tarefa (nada de ler arquivo arbitrário do disco); `--` antes do path no git.
  - Erros: 404 com `detail` em pt-BR quando a tarefa não existe, não tem `final`, o arquivo não está no relatório ou o worktree já foi removido (`crew cleanup`). A UI mostra "worktree removido, diff indisponível".
- Custo/limites: `MAX_PATCH_BYTES = 256 KiB` por arquivo (cortado na última linha inteira, `truncated=true`); binário não traz patch. Um `git diff` por clique, timeout padrão do `git.run`. Nada vai no WS nem no `state_json`.
- Alternativas:
  1. `FinalFile.patch: str | None` (truncado) dentro do `FinalReport`. A favor: sobrevive ao `cleanup` e funciona no Histórico sem worktree. Contra: engorda o `TaskView` publicado no WS e o `state_json` de toda tarefa (precisa de teto total, ex.: 1 MiB, e aí arquivos somem do diff); calcula patch que ninguém abre.
  2. Híbrido: endpoint agora, e só se o worktree removido incomodar na prática, gravar os patches num arquivo ao lado do `crew.db` no `build_report`.
  3. Sem contrato: botão "abrir no editor" com `worktree_path/path`. Não mostra o diff, só o arquivo.
  - Recomendação: a proposta (endpoint sob demanda).
- Workaround atual: nenhum; a UI lista os arquivos por pasta sem patch.

### B. Reabrir uma tarefa do Histórico

- O quê: clicar numa tarefa do Histórico (`HistoryList`) e ver o resultado dela. `GET /api/tasks` devolve só `TaskSummary`.
- Por quê: o `crew.db` já guarda o estado completo de cada tarefa (`TaskRow.state_json`); a UI só não tem como pedir.
- Proposta (código):
  - Endpoint novo `GET /api/tasks/{task_id}` → `TaskView` (`TaskState.to_view()` do `state_json`, lido direto do store pelo gateway, como `GET /api/tasks`). Nenhum modelo novo.
  - 404 quando a tarefa não existe ou o `state_json` é de um contrato antigo incompatível (mesma regra do `list_tasks`, que já pula essas linhas).
  - Só leitura: não troca a tarefa atual do orquestrador nem do WS. A UI abre a tarefa antiga numa tela de leitura (resultado + diff do item A quando o worktree ainda existe), sem CTAs que mandam comando. Tarefa ainda em execução no Histórico leva para a tela atual.
- Custo/limites: um `SELECT` por clique; o `TaskView` de uma tarefa terminada tem o mesmo tamanho do snapshot que o WS já manda.
- Alternativas:
  1. Request/reply ao orquestrador num subject novo (`crew.state.get`): mexe em `bus/subjects.py` e passa pelo NATS sem ganho, já que o gateway já lê o SQLite.
  2. Devolver só o `FinalReport` (`GET /api/tasks/{id}/final`): menos dado, mas a tela de resultado também usa plano, épicos, testes e review do `TaskView`.
  - Recomendação: a proposta (`TaskView` inteiro).
- Workaround atual: nenhum; o Histórico só lista.

---

## 2026-10-13 · D68 · Faixa de review final — ✅ aplicado (exceção ao congelamento, como D38/D39)

- `EpicView.kind` ganha `"review"`: a faixa `REV` roda o Reviewer uma vez sobre a branch da tarefa depois do lote (ou do `finish_task`), com rodadas Developer → Tester de correção. Tickets e integração não passam mais pelo Reviewer: o terceiro estágio da faixa vira "Merge" na UI.
- Nada mais muda: `ReviewComment` continua sem `axis` (os eixos vão no texto, `[Spec]`/`[Standards]`).

---

## 2026-10-07 · T-8 · Histórico de tarefas — ✅ aplicado (exceção ao congelamento, como D38/D39)

- Saída nova: `TaskSummary` (`backend/src/crew/contracts/history.py`): `task_id`, `title`, `repo`, `phase`, `running`, `started_at`, `ended_at`, `duration_s`, `cost_usd`, `tokens`, `commit_message`, `files_changed`, `summary`. Tudo calculado no backend (`TaskState.to_summary`); `summary` é a 1ª linha da mensagem de commit do relatório final ou, sem relatório, a descrição da tarefa.
- Endpoint novo: `GET /api/tasks` (só leitura) devolve `list[TaskSummary]` lido da tabela `task` do SQLite, da mais recente para a mais antiga, no máximo 50. O stream de eventos e `TaskView` não mudam.

---

## 2026-10-07 · T-7 · Adicionar repositório existente pela UI — ✅ aplicado (exceção ao congelamento, como D38/D39)

- Comando `AddRepo` (`add_repo`): `name`, `path`, `base_branch`, `test_cmd` (obrigatório), `lint_cmd`, `setup_cmd`, `sandbox_image`, `deps_dirs`, `init_git`. O orquestrador valida, opcionalmente faz `git init` + commit inicial vazio, registra em `~/.dev-crew/repos.toml` e não inicia tarefa.
- Saídas novas: `FolderEntry`, `FolderListing`, `FolderProbe` (`GET /api/folders` e `GET /api/folders/probe`, só leitura).

---

## 2026-10-06 · M6 · Contratos v2: épicos, estimativa, limite de uso, projeto novo — ✅ aplicado (exceção ao congelamento, como D38/D39)

- `Plan`: `execution` (`single|epics`), `split_rationale`, `epics: list[Epic]` (id `E\d+`, `depends_on`, `size` S/M/L), `project_setup: ProjectSetup | None`.
- `AgentJob`: sem `budget_usd`, com `epic_id`. `AgentResultEvt.usage: list[TokenUsage]`. `AgentFailedEvt.limit: UsageLimit | None`. `Feedback.kind` ganha `merge_conflict`. `RepoContext.new_project`.
- Comandos: `ApprovePlan.epics`, `RunEpics`, `FinishTask`, `ResumeAfterLimit`, `CreateProject` (`parent_dir` vazio = `[workspace] projects_dir`), `EscalationAction.epic_id`.
- `TaskView`: `epics: list[EpicView]`, `estimate`, `limit`, `tokens`; fases `executing`, `awaiting_selection`, `limited`. `FinalReport`: `commits`, `pending_epics`, `plan_doc`, `tokens`. `Escalation.epic_id`.
- Novos: `AccountUsage` (`GET /api/usage`), `Estimate`/`EpicEstimate`.

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
