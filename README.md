# dev-crew

Equipe de desenvolvimento multi-agente local. Você descreve uma tarefa e os agentes Entrevistador, Planner, Developer, Tester e Reviewer planejam, implementam, testam e revisam com loop de correção, conversando via NATS JetStream. No fim, as alterações ficam locais (sem commit) com uma mensagem de commit sugerida.

- Plano e contexto: vault Obsidian em `C:/Users/guilh/Documents/Vaults/dev-crew-vault` (ver `.obsidian-vault`)
- Convenções: `CLAUDE.md`
- Referência visual: `mockup/index.html`

## Setup do zero (Windows 11)

Pré-requisitos:

```bash
winget install Git.Git
```

```bash
winget install astral-sh.uv
```

```bash
winget install OpenJS.NodeJS.LTS
```

```bash
winget install Docker.DockerDesktop
```

- Docker Desktop roda o NATS (`infra/docker-compose.yml`) e o sandbox dos agentes. Precisa do WSL2 (`wsl --install --no-distribution` + reboot).
- O `nats-server.exe` do winget não serve: o Smart App Control bloqueia binário sem assinatura.
- Agentes reais usam o Claude Code CLI (`claude.exe` nativo) logado na assinatura:

```bash
claude auth login
```

Dependências:

```bash
cd backend && uv sync
```

```bash
cd frontend && npm install
```

UI servida pelo gateway (lê `frontend/dist`):

```bash
cd frontend && npm run build
```

Config:

- `crew.toml.example` → `~/.dev-crew/crew.toml` (busca: `CREW_CONFIG` > `./crew.toml` > `~/.dev-crew/crew.toml`). Cadastre os repos em `[[repos]]` com `test_cmd`, `lint_cmd` e, opcionalmente, `setup_cmd`, `sandbox_image` e `deps_dirs`.
- `.env.example` → `backend/.env`. Deixe `ANTHROPIC_API_KEY` vazio: preenchido, os agentes cobram na API em vez da assinatura.

Checagem (config, git, Git Bash, CLI, login, NATS, Docker, repos):

```bash
cd backend && uv run python -m crew.cli doctor
```

## Rodar

Tudo num terminal (abre o Docker Desktop se precisar, sobe o NATS, cria os streams e roda `crew up`):

```bash
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

- sem flags: agentes **fake** (zero tokens). Abra `http://127.0.0.1:8787`.
- `-Real`: agentes reais via assinatura (consome a cota do plano; teto por tarefa em `budget_usd_per_task`).
- `-Escalate`: fakes forçam a escalada no Tester · `-Speed 3`: velocidade dos fakes.

Worktrees das tarefas: `~/.dev-crew/worktrees/<repo>/<task>`, branch `crew/<task>`. Revise, commite com a mensagem sugerida e depois:

```bash
cd backend && uv run python -m crew.cli cleanup <task>
```

A CLI roda como `python -m crew.cli` porque o Smart App Control bloqueia o `crew.exe` que o uv gera.

## Comandos

| Onde | Comando |
|---|---|
| backend | `uv run pytest` · `uv run ruff check .` · `uv run mypy src` |
| backend | `uv run python -m crew.cli streams init` · `uv run python -m crew.cli gen-schema` |
| frontend | `npm run gen:types` · `npm run typecheck` · `npm run lint` · `npm test` · `npm run build` |
| frontend | `npm run dev:mock` (UI sem backend, MSW) · `npm run test:e2e` |
| infra | `docker compose -f infra/docker-compose.yml up -d` / `down` |
