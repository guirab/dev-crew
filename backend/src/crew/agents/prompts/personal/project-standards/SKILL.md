---
name: project-standards
description: Analyze a code repo and create or update its standards docs (glossary, conventions, ADRs, "Before You Develop") in the project's Obsidian vault.
disable-model-invocation: true
---

# Project Standards

Builds a repo's **standards base**: everything a human or agent must read before developing a new feature so it comes out matching what already exists. Works for any project; nothing here assumes a stack, language or folder layout.

The base is an **opinionated index**, not a copy. Every meaning lives in a **single source of truth**: if a standard is already written somewhere (agent skill, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, a vault note), the base **points** to it. If a tool enforces it (linter, formatter, tsconfig, commitlint), the config is the source and the base does not restate it. The base keeps what lives only in the team's heads or in the code: the unwritten convention, the reason behind a choice, the gotcha no config confesses.

The vault holds **only docs about the code**. The code repo lives elsewhere and is read, never written to.

## Layout

One vault per **project**, by default `~/Documents/vaults/<PROJECT>-vault/` (how an existing one is found: step 1). A project is either a **workspace** (a folder holding several sibling code repos) or a single repo.

**Workspace project**: what is shared by every repo sits at the project level; each repo gets a folder named after it with what is particular to it.

```
~/Documents/vaults/<PROJECT>-vault/    ← <VAULT>
└── standards/
    ├── Glossary.md                    ← business terms, valid for every repo
    ├── Conventions.md                 ← rules that cross repos
    ├── decisions/
    │   └── ADR-NNNN - <Title>.md      ← each lists the repos it affects
    └── <REPO>/                        ← just the code repo's name, used as a folder
        ├── Before You Develop.md      ← entry point: points to project-level + repo-level docs
        └── Conventions.md             ← only what is particular to this repo
```

**Single-repo project**: no `<REPO>/` folder; everything sits directly in `standards/` (`Before You Develop.md`, `Glossary.md`, `Conventions.md`, `decisions/`). If a second repo joins the project later, switch to the workspace layout: create `standards/<REPO>/` for each repo, move each repo's `Before You Develop` and particular conventions into it, and keep the shared parts at the project level.

**Monorepo** (one repo, several packages/apps): still one repo. Packages appear as sections in that repo's `Conventions.md`, only where they diverge.

Formats and templates for each file: [FORMATS.md](FORMATS.md). Read it before writing any of them.

All output is in **English**, whatever the language of the code comments or existing notes. Code identifiers stay as they are.

## Process

### 1. Locate repo, project and vault

- **Repo**: `git rev-parse --show-toplevel`, run from the main working directory, never from inside the vault. `<REPO>` is that folder's name.
- **Project**: if the repo's parent folder holds other git repos, the project is a workspace and `<PROJECT>` is the parent folder's name; otherwise `<PROJECT>` is `<REPO>` and the project is single-repo.
- **`<VAULTS_ROOT>`**: `~/Documents/vaults`, or `~/Documentos/vaults` if the home uses `Documentos`. Names match case-insensitively (`Vaults` works).
- **`<VAULT>`**: the first that applies:
  1. the path in a `.obsidian-vault` file (content trimmed) at the repo root or, in a workspace, in the workspace folder;
  2. `<VAULTS_ROOT>/<PROJECT>-vault/`, if it exists;
  3. `<VAULTS_ROOT>/<PROJECT>/`, if it exists.

  If none exists, confirm with the user (showing the path and the project name you derived), then create `<VAULTS_ROOT>/<PROJECT>-vault/`: an empty `.obsidian/` directory (what makes Obsidian recognize the folder as a vault) and a `Home.md` (template in FORMATS.md). Then suggest the user add a `.obsidian-vault` file with the vault path to the repo (or workspace folder); do not write it yourself.
- **Mode**: the repo's `Before You Develop.md` exists → **update** (step 7). Otherwise → **create** (steps 2–6). In a workspace, project-level files written by runs on other repos are reused and extended, never rewritten.

Done when: `<REPO>`, `<PROJECT>`, layout (workspace or single-repo), `<VAULT>` and mode are settled.

### 2. Inventory existing sources

Before reading code, map what is **already documented**:

- Agent instructions in the repo: `CLAUDE.md`, `AGENTS.md`, `.claude/skills/`, `.opencode/skills/`, `.cursor/rules/`, `.github/copilot-instructions.md` (follow symlinks; a symlinked folder shared by several repos is still a source).
- In a workspace: `CLAUDE.md` / `AGENTS.md` in the workspace folder, which often hold cross-repo rules.
- Repo docs: `README.md`, `CONTRIBUTING.md`, `docs/`, `docs/adr/`, `GLOSSARY.md`.
- Config that enforces rules: linter, formatter, `tsconfig` or equivalent, `.editorconfig`, commitlint, git hooks (husky, lefthook, pre-commit).
- The vault: existing `standards/` files (project level and other repos' folders), and the notes that mention `<REPO>` (`grep -rl "<REPO>" <VAULT> --include='*.md'`), including decision sections in session notes.

For each source, note what it covers. Where two sources cover the same subject, record a **duplication** (resolved in step 5).

Done when: every source found has a one-line "covers X"; no agent-instructions folder was left unopened.

### 3. Extract patterns from code

Map the repo layout (2–3 levels, excluding dependencies and build output) and pick **2–3 representative modules** (per package, in a monorepo), preferring recently changed ones (`git log --since=6.months --name-only`), because recent code shows the **current** pattern. Compare them with each other.

A pattern counts only if it appears in **at least two places**. When new and old modules diverge, the new one is current and the old one is **legacy**, recorded as "do not copy from here".

Artifact types to cover (adapt to the stack; skip those the repo lacks):
layers and request flow · module folder structure · file, class and function naming · input/output (DTOs, schemas, validation) · data access and migrations · errors and error responses · authentication and authorization · calls to other services · configuration and env vars · logging and observability · tests (tools, location, what gets tested) · i18n · frontend: components, state, data fetching, forms, styling · git: branches, commits, PRs.

In a workspace, sort each pattern: if it also holds in other repos (check their code or the project-level `Conventions.md`), it is **project-level**; otherwise it is **repo-level**.

Done when: every artifact type present in the repo has **one** of: a pointer to a step 2 source, an extracted pattern with a real example (`path/file:line`), or a "no clear pattern" flag listing the divergent examples.

### 4. Extract vocabulary and decisions

**Glossary**: domain terms come from enums, entities and tables, routes, i18n files, and vault feature notes. Only terms of **this project's business** go in, never generic programming concepts. When code and business use different names for the same thing, record both: that mismatch is the most expensive mistake in a new feature.

**Decisions**: candidates come from session notes' decision sections, existing ADRs, imperative rules in `CLAUDE.md` and skills ("never X", "always Y"), and **deviations from the obvious path** in the code (e.g. a query builder instead of an ORM). A candidate becomes an ADR only if it passes all three: **hard to reverse**, **surprising without context**, **a real trade-off was made**. The rest goes to the right `Conventions.md` if it is still a rule, and is dropped otherwise. Before creating an ADR, check `decisions/` for one that already records it; if so, add `<REPO>` to its `repos` list instead.

Done when: every candidate is classified (ADR, convention, or dropped) and every ADR cites where it came from.

### 5. Resolve gaps with the user

Before writing, ask what the code and sources cannot settle, **at most 5 questions per round**, grouped:

- Step 2 duplications: which source is the truth? (the other one should become a pointer)
- "No clear pattern" flags: which one is correct going forward?
- Ambiguous terms: what is the canonical name?
- Decisions whose **reason** is written nowhere.
- Project-level vs repo-level, when the sorting in step 3 was not clear-cut.

Anything left unanswered goes into the doc as a `> [!question]` callout, never as fact.

### 6. Write

Follow [FORMATS.md](FORMATS.md). Order: ADRs → Glossary → Conventions (project, then repo) → `Before You Develop` (last, since it points to all of them).

Then wire it into the graph: link the repo's `Before You Develop` from the vault hub (`Home` or MOC) and from the vault's project note for `<REPO>`, if one exists. When an existing vault note duplicates the base, **leave it in place**: report it and suggest replacing its content with a pointer.

### 7. Update mode

Read the frontmatter of the repo's `Before You Develop.md` (`updated_at` and `commit`). Analyze only `git log <commit>..HEAD` and only session notes newer than `updated_at`. Run steps 3–6 **restricted to what changed**: new pattern, new term, new decision, pattern turned legacy. Edit existing files rather than recreating them; an ADR that no longer holds gets `status: superseded by ADR-NNNN` and stays. Update the frontmatter last.

### 8. Report

Short message: vault path (and whether it was created), files created or changed, duplications found with the suggested single source, and open `[!question]` items.

## Rules

- **Evidence, not assumption**: every pattern cites a real file; every ADR cites its origin. Anything inferred without evidence is labeled as such.
- **Pointer before copy**: information with an owner gets linked to its owner.
- **Current over legacy**: the cited example is always the most recent one that follows the pattern.
- **Lean**: every doc is read before every feature. A line that does not change how the reader works gets cut.
