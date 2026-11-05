# dev-crew

dev-crew is a multi-agent development team that runs on your own machine. You describe a task, and the Interviewer, Standards, Planner, Developer, Tester and Reviewer agents plan, implement, test and review it in a fix loop, talking to each other over NATS JetStream.

- Small task: a single run. The changes stay local (no commit), with a suggested commit message.
- Feature or whole project: the Planner splits it into small tickets (epics, following Matt Pocock's `to-tickets` method) with dependencies. The plan shows a cost estimate (tokens, USD equivalent, % of the 5-hour session and of the weekly limit) and you choose which ones to run now. Epics that don't depend on each other run in parallel, each in its own worktree. dev-crew makes one commit per epic and merges everything into the `crew/<task>` branch (no push).
- New project from scratch: the "Novo projeto" (New project) card creates the folder with git, and the Planner picks the stack and the commands, starting with the foundation (E0).

The UI is in Brazilian Portuguese; UI labels below are quoted as they appear, with a translation.

- Plan and context: a private Obsidian vault (path in `.obsidian-vault`)
- Conventions: `CLAUDE.md`
- Visual reference: `mockup/v6-linha-do-tempo.html`

## How it works

```
React UI ─REST/WS─▶ FastAPI gateway (127.0.0.1:8787) ─▶ NATS JetStream ◀─▶ Orchestrator (state machine + SQLite)
                                                             ▲▼
                              Agent SDK workers: interviewer · standards · planner · developer · tester · reviewer (cwd = worktree)
                                                             │ tool mcp__crew__run (docker exec)
                                                     Docker sandbox per task (repo's sandbox_image)
```

- The orchestrator is a pure state machine, `decide(state, event) -> (state, effects)`, so the flow never depends on what an LLM decides.
- Agents are stateless: everything they need comes in the job. Structured output goes through a `submit_*` tool and is validated with Pydantic.
- Agents never commit, push, install dependencies, access the network or write outside their worktree; guards in `agents/guards.py` enforce this. dev-crew itself installs the dependencies the approved plan lists.
- The Tester's pass/fail comes from the exit codes of `test_cmd` and `lint_cmd`, which the worker runs again after the agent finishes.

Stack: Python 3.12 (uv, Pydantic v2, nats-py, Claude Agent SDK, FastAPI, SQLite) · React 19 + TypeScript + Vite · NATS 2.15 · Docker.

## Setup from scratch (Windows 11)

Prerequisites:

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

- Docker Desktop runs NATS (`infra/docker-compose.yml`) and the agents' sandbox. It needs WSL2 (`wsl --install --no-distribution` + reboot).
- The winget `nats-server.exe` won't work: Smart App Control blocks unsigned binaries.
- Real agents use the Claude Code CLI (native `claude.exe`) logged in with your subscription:

```bash
claude auth login
```

Dependencies:

```bash
cd backend && uv sync
```

```bash
cd frontend && npm install
```

UI served by the gateway (reads `frontend/dist`):

```bash
cd frontend && npm run build
```

Config:

- `crew.toml.example` → `~/.dev-crew/crew.toml` (lookup order: `CREW_CONFIG` > `./crew.toml` > `~/.dev-crew/crew.toml`). Register your repos under `[[repos]]` with `test_cmd`, `lint_cmd` and, optionally, `setup_cmd`, `sandbox_image` and `deps_dirs`. `lint_cmd` runs in `bash -lc`, so it can chain the typecheck (`lint_cmd = "npm run lint && npm run typecheck"`): the Tester's `ok` comes from the exit code (D70). `standards_dir` is optional: it pins the repo's folder in the vault's standards base (see [Standards base](#standards-base)). It also works in `~/.dev-crew/repos.toml`, the only key you may edit there by hand.
- `.env.example` → `backend/.env`. Leave `ANTHROPIC_API_KEY` empty: if it is set, the agents bill the API instead of the subscription.

Health check (config, git, Git Bash, CLI, login, NATS, Docker, repos):

```bash
cd backend && uv run python -m crew.cli doctor
```

## Desktop app

This command creates the "Dev Crew" shortcut in the Start menu (`--desktop` also puts one on the Desktop):

```bash
cd backend && uv run python -m crew.cli install-app
```

Clicking the shortcut opens Docker Desktop if needed, starts NATS and the crew in the background (real agents) and opens the UI in its own Edge window. The icon in the system tray shows the state (yellow starting, green ready, red error) and has **Abrir Dev Crew** (Open), **Ver logs** (View logs) and **Encerrar** (Quit). Closing the window doesn't stop the crew: only **Encerrar** does. **Encerrar** only undoes what that launch did: it stops the NATS container if the app started it, and closes Docker Desktop (`docker desktop stop`) if the app opened it. A Docker that was already open stays open. Clicking the shortcut again while the app is running just opens another window.

- The shortcut runs the venv's `pythonw.exe` (signed by the PSF, so it passes Smart App Control) with `-m crew.cli app`.
- Logs in `~/.dev-crew/logs/` (`app.log` from the launcher, `backend.log` and `crew.log` from the crew).
- `crew app --fake-agents` (zero tokens) and `--no-window` (starts without a window) exist for testing and automation.
- If a `dev-up.ps1` is already running on the same port, the app only opens the window and doesn't shut it down.

## Running from the terminal

`dev-up.ps1` runs everything in one terminal. It opens Docker Desktop if needed, starts NATS, creates the streams and runs `crew up`:

```bash
powershell -ExecutionPolicy Bypass -File scripts/dev-up.ps1
```

- No flags: fake agents (zero tokens). Open `http://127.0.0.1:8787`.
- `-Real`: real agents on your subscription (uses your plan's quota). There is no cost or time cap; if you hit the subscription limit, the task pauses and the screen shows when it comes back, with a **Retomar** (Resume) button.
- `-Escalate`: fakes force an escalation in the Tester · `-Speed 3`: fake agent speed.

Task worktrees: `~/.dev-crew/worktrees/<repo>/<task>`, branch `crew/<task>`. Review, commit with the suggested message, then:

```bash
cd backend && uv run python -m crew.cli cleanup <task>
```

The CLI runs as `python -m crew.cli` because Smart App Control blocks the `crew.exe` that uv generates.

## Parallel epics

- The Planner decides whether to split (a small, cohesive change stays a single run) and explains why in the plan. Parallel epics never edit the same file; epics that need the same file become dependencies.
- On approval you pick the epics to run now; their dependencies come along. When the batch finishes, the approval card offers the next ones or **Concluir agora** (Finish now), and dev-crew records whatever you left out as pending.
- Each epic (ticket): worktree `crew/<task>-E1`, Developer → Tester with the fix loop. Once tests pass (dev-crew checks the exit codes of `test_cmd` and `lint_cmd`), dev-crew commits and merges into the task branch. A merge conflict becomes an integration lane (`M-E2`) that resolves and tests it before the merge completes.
- End of batch or **Concluir agora**: the **Review final** lane runs the Reviewer once over the whole branch (Spec and Standards passes); whatever it asks for goes through Developer → Tester and lands in a `fix: ajustes do review final` commit.
- The plan is saved in the project at `docs/plano/<task>.md` and updated at the end of each batch.
- `[parallel] workers_per_agent` (default 3) caps how many epics have an agent working at the same time. On the Pro plan, parallel runs drain the 5-hour session faster: check the estimate before approving.
- An agent idle for 30 min with no activity (and no command running) escalates on its own.

## Standards base

Every agent after the interview follows the repo's standards base (glossary, conventions, ADRs, `Before You Develop`), the one the `project-standards` skill writes in the project's Obsidian vault: `<vault>/standards/` (single repo) or `<vault>/standards/<REPO>/` plus shared files one level up (workspace: a folder holding several git repos). The repo itself never gets a doc file from dev-crew.

- Where the vault is, resolved on every job: `standards_dir` of the repo, a `.obsidian-vault` file (repo root, then the workspace folder), `~/Documents/Vaults/<PROJECT>-vault`, `~/Documents/Vaults/<PROJECT>` (case-insensitive; `Documentos` and `vaults` work too). Repos loose in `~/Documents` are single-repo projects.
- **Padrões** stage: when an existing repo has no base yet, the `standards` agent (Opus) runs the skill alongside the interview, without asking you anything (it decides with evidence and lists its decisions in the stage). It reads the repo and a read-only copy of the vault's notes (`<worktree>/.crew/vault/`) and writes only to `<worktree>/.crew/standards-out/`; dev-crew then copies the valid files into the vault (creating it, with `.obsidian/` and `Home.md`, when missing) and removes `.crew/` (kept out of git through `info/exclude`). The Planner waits for both the interview and this stage.
- With a base already in the vault the stage is done at once ("Usando a base existente"); a new project skips it; a failure shows in the stage and the task goes on without a base.
- A repo from `~/.dev-crew/repos.toml` gets the resolved `standards_dir` saved there; a `crew.toml` repo is left as you wrote it.
- `--fake-agents` writes a minimal fake base into `~/.dev-crew/fake-vaults/`, never into your real vaults.

## New project

- **Novo projeto** card: name (becomes the folder) and where to create it (empty = `[workspace] projects_dir`, default Documents). dev-crew creates the folder, runs `git init` with a README and `.gitignore`, and makes the first commit.
- The project is registered in `~/.dev-crew/repos.toml` (managed by dev-crew, added to the `[[repos]]` from `crew.toml`).
- The Planner fills in `project_setup` (stack, `setup_cmd`, `test_cmd`, `lint_cmd`, `sandbox_image`). Once the plan is approved, the commands go into the registry.
- The first task runs on your machine, without a container: `setup_cmd` runs in each worktree right before the first Tester, after E0 has written the manifests. From the next task on, `sandbox_image` applies.

## Commands

| Where | Command |
|---|---|
| backend | `uv run pytest` · `uv run ruff check .` · `uv run mypy src` |
| backend | `uv run python -m crew.cli streams init` · `uv run python -m crew.cli gen-schema` · `uv run python -m crew.cli skills sync --ref <sha>` (Matt Pocock's skills in the prompts) |
| frontend | `npm run gen:types` · `npm run typecheck` · `npm run lint` · `npm test` · `npm run build` |
| frontend | `npm run dev:mock` (UI without backend, MSW) · `npm run test:e2e` |
| infra | `docker compose -f infra/docker-compose.yml up -d` / `down` |
