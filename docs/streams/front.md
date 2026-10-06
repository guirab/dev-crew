# Stream C · Frontend

> Registro histórico do M1 (2026-10-01). Depois disso o Azure DevOps foi removido (D38, `5573d1b`) e a entrevista virou rodadas (D39); o estado atual está no README e no CLAUDE.md.

Branch: `worktree-agent-a6675f949ca95bacb`. Escopo: só `frontend/` (mais `docs/contract-requests.md` e este arquivo).

## Como rodar

```bash
cd frontend
npm install
npm run dev:mock      # UI com MSW (REST + WS), sem backend
npm run dev           # UI contra o gateway real (proxy /api e /ws para 127.0.0.1:8787)
npm run typecheck && npm run lint && npm test
npm run build
npx playwright install chromium   # uma vez
npm run test:e2e      # smoke em modo mock (sobe o vite na porta 5199)
```

Parâmetros do modo mock (query string):

- `?speed=<n>` multiplica a velocidade do cenário (a DemoBar também tem 1x/2x/4x/8x).
- `?escalate=1` faz o Tester falhar sempre, forçando a escalada.
- `?fixture=<nome>` carrega `contracts/fixtures/view.<nome>.json` estático (somente leitura; comandos dão 409).
  Nome inexistente mostra o erro na tela com a lista disponível.
- `/dev/gallery` (só em dev): todos os status do `StageCard`, conectores, loops e botões.

A DemoBar (canto inferior esquerdo, só no modo mock) tem velocidade, "forçar escalada" e "derrubar ws"
(simula queda do gateway para ver o banner "reconectando…").

## Feito

- Scaffold de tooling: ESLint flat (typescript-eslint strict-type-checked, jsx-a11y, react-hooks v7;
  `as` proibido via `consistent-type-assertions: never`), Prettier, Vitest + Testing Library, Playwright.
- `tokens.css`/`global.css` e CSS Modules portados de `mockup/index.html`. Comparação lado a lado
  (Playwright headless, estados vazio, formulário Azure, concluída, mobile) ficou visualmente idêntica;
  as diferenças são só de conteúdo (mockup tem log de atividade, fixtures não).
- `flow/`: `stages.ts` (metadados, mapa conector→arestas igual ao mockup, `EDGE_TARGET`, descrição/tag/contador,
  overlay de progresso, regra de fechamento automático), `StageCard` (header `<button aria-expanded>`),
  `Connector`, `LoopRail` (ResizeObserver, posicionamento direto no DOM), `SourcePicker`, `FlowColumn`.
- `bodies/`: Interview, Planner, Approval, Developer, Tester (+ `EscalationPanel` reutilizado em
  Reviewer/Developer), Reviewer, Done (KPIs, arquivos, commit + copiar), `AzureForm`, `ManualForm`.
- `api/`: cliente tipado com guardas estruturais (`guards.ts`), `CommandError`, queries (TanStack Query),
  mutation `useSendCommand`, WS com reconexão exponencial (500ms a 10s) e re-hidratação por `GET /api/task`.
- `store/crew.ts` (Zustand): snapshot, progresso por estágio, conexão, versão do snapshot.
- Modo mock: `ScenarioBackend` (porta do motor do mockup, emite `TaskView`s válidos, valida comandos com 409/422),
  `FixtureBackend`, handlers MSW HTTP + WS, DemoBar.
- Regras de UI: cards fechados por padrão; expansão só por clique e sobrevive a snapshots; auto-scroll só sem
  card aberto; reduced motion; banner "reconectando…"; uma tarefa por vez (origem em modo leitura);
  "Nova tarefa"/"cancelar tarefa" (com `confirm`).
- Testes: 147 unit/integração (Vitest) + 9 e2e (Playwright). O e2e cobre o fluxo Azure completo, Manual com
  entrevista, escalada, cancelar, fixture, queda de WS, galeria e reduced motion.
- Produção: bundle de ~89 kB gzip, sem código de mock (`import.meta.env.MODE`), service worker do MSW removido do `dist`.

## Desvios do plano

- **TypeScript 6.0 em vez de 7.0.** `typescript-eslint` (8.71) exige `typescript <6.1` e TS 7 não tem a API
  programática (volta no 7.1). Fixei `typescript ~6.0.3`. Trocar para 7.x quando o typescript-eslint suportar.
- **ESLint 9** (não 10): `eslint-plugin-jsx-a11y` ainda declara peer até 9.
- `TanStack Query`: usa `queryClient.query()` (o `fetchQuery` está deprecado na 5.104). `useCurrentTask` virou
  `currentTaskQuery` + `useCrewConnection`, que grava o resultado no store (uma única fonte de verdade).
- **Sem heartbeat de aplicação no WS**: o contrato não define ping; o ping/pong de protocolo do uvicorn cobre.
  Também reconecta no evento `online`.
- `store.connection` tem 3 estados (`connecting|open|closed`) em vez de `connected: boolean`, pra não piscar o
  banner no primeiro carregamento. Antes do primeiro snapshot a UI mostra "conectando…".
- "Nova tarefa" é decisão de UI (`dismissedTaskId`); ver pedido 2 em `docs/contract-requests.md`.
- Auto-fechamento de card (nunca abre): sai de `waiting` para done/idle, ou escalada resolvida. O mockup fazia
  o mesmo manualmente em cada ação.
- Resposta de `POST /api/commands` só é aplicada ao store se nenhum snapshot do WS chegou durante o envio.
- Extras além do plano: seções "Riscos" e "Estratégia de testes" no plano; custo no KPI da concluída;
  Tester mostra cobertura; `EscalationPanel` também em Reviewer/Developer se a escalada vier desses estágios.
- Cobertura é tratada como fração 0..1 (como nas fixtures); ver pedido 1.

## Pendências

- Validar contra o gateway real no M2 (formato de erro 409/422, snapshot inicial no WS, fase terminal e `start_task`).
- Pedidos em `docs/contract-requests.md` (unidade de `coverage`, "Nova tarefa", `test_attempt`, tipagem de
  `edges`/`Escalation.stage`, rótulo "+2").
- Sem tema claro, tela de configurações nem chat livre (fora do escopo do MVP).
- Passe de acessibilidade com leitor de tela real não foi feito (só roles/labels/foco verificados por teste).
- `public/mockServiceWorker.js` é gerado pelo `msw init`; reexecutar `npx msw init public --save` ao atualizar o MSW.
