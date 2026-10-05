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

## App desktop

Cria o atalho "Dev Crew" no menu Iniciar (`--desktop` também na Área de Trabalho):

```bash
cd backend && uv run python -m crew.cli install-app
```

Clicar no atalho abre o Docker Desktop se precisar, sobe o NATS e o crew escondidos (agentes reais) e abre a UI numa janela própria do Edge. O ícone perto do relógio mostra o estado (amarelo iniciando, verde pronto, vermelho erro) e tem **Abrir Dev Crew**, **Ver logs** e **Encerrar**. Fechar a janela não para o crew: só o **Encerrar** para. O **Encerrar** desfaz só o que aquela abertura fez: para o container do NATS se foi o app que o subiu, e fecha o Docker Desktop (`docker desktop stop`) se foi o app que o abriu. Docker que já estava aberto antes continua aberto. Clicar no atalho de novo com o app aberto só abre outra janela.

- O atalho roda o `pythonw.exe` do venv (assinado pela PSF, passa no Smart App Control) com `-m crew.cli app`.
- Logs em `~/.dev-crew/logs/` (`app.log` do launcher, `backend.log` e `crew.log` do crew).
- `crew app --fake-agents` (zero tokens) e `--no-window` (só sobe, sem janela) existem para testes e automação.
- Se um `dev-up.ps1` já estiver rodando na mesma porta, o app só abre a janela e não o encerra.

## Rodar no terminal

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
