# dev-crew

Equipe de desenvolvimento multi-agente local. Você descreve uma tarefa e os agentes Entrevistador, Planner, Developer, Tester e Reviewer planejam, implementam, testam e revisam com loop de correção, conversando via NATS JetStream. No fim, as alterações ficam locais (sem commit) com uma mensagem de commit sugerida.

- Convenções: `CLAUDE.md`
- Referência visual: `mockup/index.html`

> **Status: alpha, só Windows 11.** O app desktop, o atalho e o `dev-up.ps1` são específicos do Windows.

## Antes de começar

- **Assinatura paga do Claude** (Pro ou Max). Os agentes usam o seu login do Claude Code, não uma API key: cada pessoa gasta a própria cota. Uma tarefa real custa algo na casa de US$ 1 a 3 equivalentes.
- O **Planner** e o **Reviewer** usam Opus e os outros três usam Sonnet. Se o seu plano não tiver Opus, troque tudo por Sonnet em `[models]` no `crew.toml`.
- **Não defina `ANTHROPIC_API_KEY`** (nem no ambiente). Com ela, os agentes cobram na API em vez da assinatura. O `doctor` avisa.

## Setup do zero (Windows 11)

Pré-requisitos:

```bash
winget install Git.Git
```

```bash
winget install astral-sh.uv
```

```bash
winget install Python.Python.3.13
```

```bash
winget install OpenJS.NodeJS.LTS
```

```bash
winget install Docker.DockerDesktop
```

- Docker Desktop roda o NATS (`infra/docker-compose.yml`) e o sandbox dos agentes. Precisa do WSL2 (`wsl --install --no-distribution` + reboot) e de virtualização ligada na BIOS.
- O `nats-server.exe` do winget não serve: o Smart App Control bloqueia binário sem assinatura.
- O Python do python.org é assinado pela PSF. Com o Smart App Control ligado, o atalho do app só abre se o `pythonw.exe` do venv for assinado, então prefira esse Python ao baixado pelo uv.
- Agentes reais usam o Claude Code nativo (`claude.exe`, não o pacote npm). Instale e faça login:

```bash
irm https://claude.ai/install.ps1 | iex
```

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

- `crew.toml.example` → `~/.dev-crew/crew.toml` (busca: `CREW_CONFIG` > `./crew.toml` > `~/.dev-crew/crew.toml`).
- Repo de demonstração: o comando abaixo cria um repo git em `~/.dev-crew/repos/demo` e imprime o bloco `[[repos]]` pronto pra colar no `crew.toml`:

```bash
cd backend && uv run python -m crew.cli init-demo
```

- Repos seus: cadastre em `[[repos]]` com `path`, `test_cmd`, `lint_cmd` e, opcionalmente, `setup_cmd`, `sandbox_image` e `deps_dirs`. O `base_branch` (padrão `main`) precisa ter ao menos um commit.
- `sandbox_image` precisa de uma imagem com `bash` e `timeout` (`node:22` serve, `alpine` não).
- `.env.example` → `backend/.env` é opcional. Deixe `ANTHROPIC_API_KEY` vazio.

Checagem (config, git, Git Bash, CLI, login, build da UI, NATS, Docker, sandbox, repos):

```bash
cd backend && uv run python -m crew.cli doctor
```

## Primeiro uso

1. Rode no modo **fake** (zero tokens) pra conhecer o fluxo: `scripts/dev-up.ps1` sem flags, abra `http://127.0.0.1:8787`.
2. Passou? Rode com agentes **reais**: `scripts/dev-up.ps1 -Real` (ou o atalho do app, abaixo).
3. Crie uma tarefa no repo `demo`. O Entrevistador faz perguntas, o Planner propõe um plano e você aprova. No fim, as alterações ficam no worktree com uma mensagem de commit sugerida.

## Segurança: leia antes de apontar pra um repo seu

- Os agentes **não commitam, não fazem push, não instalam dependências e não escrevem fora do worktree**. Quem garante isso são hooks de política (`backend/src/crew/agents/guards.py`), que são um **filtro, não um sandbox**: um script escrito pelo agente pode fazer mais do que o filtro enxerga.
- Repo **sem** `sandbox_image`: o Developer e o Tester rodam Bash direto na sua máquina, com acesso ao seu usuário (`~/.ssh`, `~/.claude`) e à rede. O `doctor` avisa por repo. Para qualquer repo que não seja descartável, defina `sandbox_image`.
- Repo **com** `sandbox_image`: os comandos rodam num container por tarefa, sem rede, vendo só o worktree.
- O conteúdo do repo alvo (README, comentários, saídas) pode conter instruções maliciosas (prompt injection). Os prompts mandam tratar isso como dado, mas é só uma instrução ao modelo.
- O gateway escuta só em `127.0.0.1` e **não tem autenticação**. Em máquina compartilhada, qualquer usuário local consegue mandar comandos.

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
| backend | `uv run python -m pytest` · `uv run python -m ruff check .` · `uv run python -m mypy src` |
| backend | `uv run python -m crew.cli streams init` · `uv run python -m crew.cli gen-schema` |
| frontend | `npm run gen:types` · `npm run typecheck` · `npm run lint` · `npm test` · `npm run build` |
| frontend | `npm run dev:mock` (UI sem backend, MSW) · `npx playwright install` e `npm run test:e2e` |
| infra | `docker compose -f infra/docker-compose.yml up -d` / `down` |

Os testes que usam NATS precisam de Docker (ou `nats-server` no PATH); sem eles, são pulados em silêncio. Os testes `-m live` chamam o Claude de verdade e consomem cota.

## Licença

MIT. Veja `LICENSE`.
