# dev-crew

Equipe de desenvolvimento multi-agente local. Você descreve uma tarefa e os agentes Entrevistador, Planner, Developer, Tester e Reviewer planejam, implementam, testam e revisam com loop de correção, conversando via NATS JetStream.

- Tarefa pequena: uma execução só. As alterações ficam locais (sem commit) com uma mensagem de commit sugerida.
- Tarefa de feature ou projeto inteiro: o Planner corta em **tickets** pequenos (épicos, no método `to-tickets` do Matt Pocock) com dependências, o plano mostra a estimativa de custo (tokens, US$ equivalente, % da sessão de 5 h e da semana) e você escolhe quais rodar agora. Épicos sem dependência entre si rodam **em paralelo**, cada um no seu worktree. O dev-crew faz **um commit por épico** e junta tudo na branch `crew/<task>` (sem push).
- **Projeto novo** do zero: o card "Novo projeto" cria a pasta com git, e o Planner escolhe a stack e os comandos, começando pela fundação (E0).

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
- `-Real`: agentes reais via assinatura (consome a cota do plano). Não há teto de custo nem de tempo (D51); se o limite da assinatura bater, a tarefa para e a tela mostra quando volta, com o botão **Retomar**.
- `-Escalate`: fakes forçam a escalada no Tester · `-Speed 3`: velocidade dos fakes.

Worktrees das tarefas: `~/.dev-crew/worktrees/<repo>/<task>`, branch `crew/<task>`. Revise, commite com a mensagem sugerida e depois:

```bash
cd backend && uv run python -m crew.cli cleanup <task>
```

A CLI roda como `python -m crew.cli` porque o Smart App Control bloqueia o `crew.exe` que o uv gera.

## Épicos em paralelo

- O Planner decide se divide (mudança pequena e coesa fica numa execução só) e justifica no plano. Épicos paralelos nunca editam o mesmo arquivo; quem precisa do mesmo arquivo vira dependência.
- Na aprovação você marca os épicos que rodam agora; os dependentes entram junto. Quando o lote termina, o card de aprovação oferece os próximos ou **Concluir agora** (o que ficou de fora fica registrado como pendente).
- Cada épico (ticket): worktree `crew/<task>-E1`, Developer → Tester com o loop de correção. Testes passando (o dev-crew confere o exit code de `test_cmd` e `lint_cmd`), o dev-crew commita e faz merge na branch da tarefa. Conflito de merge vira uma faixa de integração (`M-E2`) que resolve e testa antes de concluir o merge.
- Fim do lote ou **Concluir agora**: a faixa **Review final** roda o Reviewer uma vez sobre a branch inteira (passadas Spec e Standards); o que ele pedir passa por Developer → Tester e sai num commit `fix: ajustes do review final`.
- O plano fica salvo no projeto em `docs/plano/<task>.md`, atualizado no fim de cada lote.
- `[parallel] workers_per_agent` (padrão 3) limita quantos épicos têm um agente trabalhando ao mesmo tempo. Na assinatura Pro, paralelo esgota a sessão de 5 h mais rápido: confira a estimativa antes de aprovar.
- Um agente parado 30 min sem nenhuma atividade (e sem comando rodando) escala sozinho (D52).

## Projeto novo

- Card **Novo projeto**: nome (vira a pasta) e onde criar (vazio = `[workspace] projects_dir`, padrão Documentos). O dev-crew cria a pasta, faz `git init` com README e `.gitignore` e o primeiro commit.
- O projeto fica registrado em `~/.dev-crew/repos.toml` (gerido pelo dev-crew, somado aos `[[repos]]` do `crew.toml`).
- O Planner preenche `project_setup` (stack, `setup_cmd`, `test_cmd`, `lint_cmd`, `sandbox_image`). Aprovado o plano, os comandos vão pro registro.
- A primeira tarefa roda na sua máquina, sem container: o `setup_cmd` roda em cada worktree logo antes do primeiro Tester, depois que o E0 escreveu os manifestos. Da próxima tarefa em diante vale o `sandbox_image`.

## Comandos

| Onde | Comando |
|---|---|
| backend | `uv run pytest` · `uv run ruff check .` · `uv run mypy src` |
| backend | `uv run python -m crew.cli streams init` · `uv run python -m crew.cli gen-schema` · `uv run python -m crew.cli skills sync --ref <sha>` (skills do Matt Pocock nos prompts) |
| frontend | `npm run gen:types` · `npm run typecheck` · `npm run lint` · `npm test` · `npm run build` |
| frontend | `npm run dev:mock` (UI sem backend, MSW) · `npm run test:e2e` |
| infra | `docker compose -f infra/docker-compose.yml up -d` / `down` |
