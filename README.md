# dev-crew

Equipe de desenvolvimento multi-agente local. Você entrega uma tarefa (work item do Azure DevOps ou descrita na mão) e os agentes Entrevistador, Planner, Developer, Tester e Reviewer planejam, implementam, testam e revisam com loop de correção, conversando via NATS JetStream. No fim, as alterações ficam locais (sem commit) com uma mensagem de commit sugerida.

- Plano e contexto: vault Obsidian em `C:/Users/guilh/Documents/Vaults/dev-crew-vault` (ver `.obsidian-vault`)
- Convenções: `CLAUDE.md`
- Referência visual: `mockup/index.html`

## Setup (Windows 11)

```bash
winget install astral-sh.uv
winget install NATSAuthors.NATSServer
```

```bash
cd backend && uv sync
```

```bash
cd frontend && npm install
```

NATS (escolha um):

```bash
docker compose -f infra/docker-compose.yml up -d
```

```bash
nats-server -js -sd %USERPROFILE%/.dev-crew/nats -m 8222
```

Copie `crew.toml.example` → `crew.toml` e `.env.example` → `.env` e preencha.

## Rodar

Tudo num terminal (sobe NATS se não estiver rodando, cria streams e roda `crew up`):

```bash
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

- sem flags: agentes e Azure **fake** (zero tokens) — abra `http://127.0.0.1:8787`
- `-Real`: agentes reais via assinatura (`claude.exe` nativo logado com `claude auth login`; **sem** `ANTHROPIC_API_KEY`, senão cobra na API)
- `-Escalate`: fakes forçam a escalada no Tester · `-Speed 3`: velocidade dos fakes

Antes do primeiro uso real:

```bash
cd backend && uv run crew doctor
```

Config local: `~/.dev-crew/crew.toml` (ou `CREW_CONFIG`). Worktrees das tarefas: `~/.dev-crew/worktrees/<repo>/<task>` — revise, commite com a mensagem sugerida e depois `uv run crew cleanup <task>`.

## Comandos

| Onde | Comando |
|---|---|
| backend | `uv run pytest` · `uv run ruff check .` · `uv run mypy src` |
| backend | `uv run crew streams init` · `uv run crew gen-schema` |
| frontend | `npm run gen:types` · `npm run typecheck` · `npm test` |
