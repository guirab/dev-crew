# Standards base formats

Shared rules for every file:
- Internal vault links as wikilinks with the vault-relative path, because in a workspace several notes share a name (`[[standards/Conventions]]` vs `[[standards/my-api/Conventions]]`). Add an alias when the path reads badly: `[[standards/my-api/Conventions|my-api conventions]]`. In a single-repo project, `[[standards/Conventions]]`.
- Code files as repo-relative paths in code spans (`src/modules/orders/orders.service.ts:42`). In project-level files, prefix the repo: `my-api/src/modules/orders/orders.service.ts:42`.
- Note names in Title Case with spaces.
- English throughout. Code identifiers stay as they are.

The templates below use the workspace layout. In a single-repo project, drop the `<REPO>/` segment from every path and merge the project-level and repo-level `Conventions` into one.

---

## <REPO>/Before You Develop.md

The entry point for one repo. Short: it is read before every feature. It does not explain standards; it says **where** each one lives.

```markdown
---
updated_at: YYYY-MM-DD
commit: <short SHA of the analyzed HEAD>
---

# Before You Develop: <REPO>

<1–2 sentences: what this repo is and its role in the project.>

## Checklist

1. Are the terms your feature touches in the [[standards/Glossary|Glossary]]? Use the canonical name; add any new term.
2. Read the ADRs for the area you touch: <short list of wikilinks to the ADRs that affect this repo>.
3. Follow the [[standards/Conventions|project conventions]] and the [[standards/<REPO>/Conventions|<REPO> conventions]].
4. For each artifact you write, follow the source in the table below and copy from a **current example**, never from legacy code.

## Where each standard lives

| Artifact | Source of truth | Current example |
|---|---|---|
| <e.g. Controller> | <pointer: skill/file/note, or a Conventions section link> | `<path:line>` |
| ... | ... | ... |

## Enforced by tooling

<One line per tool: what it already enforces and the command to run it. Do not restate its rules.>
- Lint/format: `<command>` (config in `<file>`)
- Commits: <commitlint / hook>

## Legacy: do not copy

- `<path or module>`: <which old pattern it follows and what the current one is>
```

---

## Glossary.md (project level)

Based on the glossary format from `domain-modeling` (mattpocock-skills), with one deliberate deviation: the `_In code_` line, because this base serves developers, and the mismatch between business name and code name is the most common source of mistakes.

```markdown
# Glossary

<1–2 sentences: the domain this glossary covers.>

## <Natural grouping, e.g. Loyalty Program>

**<Canonical term>**:
<1–2 sentences: what the thing IS, not what it does.>
_In code_: `<EntityName>` (<repo>), table `<table>`, enum `<Enum.Value>`
_Avoid_: <synonyms the team should not use>
```

Rules:
- **Be opinionated**: when several names exist for one concept, pick one and list the rest under `_Avoid_`.
- Only this project's business terms. Generic programming concepts stay out, however often they appear in the code.
- Include `_In code_` and `_Avoid_` only when they have content. In a workspace, name the repo next to each code name when repos differ.
- A term whose meaning is unclear gets a `> [!question]` callout right below it.

---

## Conventions.md (project level) and <REPO>/Conventions.md

Same shape at both levels. The project-level file holds rules that cross repos; the repo-level file holds only what is particular to that repo. Each section is one rule (or a group of rules) with the **why** and a real example. If the rule is already written in another source, the section is a one-line pointer.

```markdown
# Conventions            ← repo level: "# Conventions: <REPO>"

## <Subject, e.g. Service Boundaries>

<Rule in positive imperative, 1–3 lines.> <Why, 1 line, or a link to the ADR.>

Example: `<path:line>`

## <Subject that already has an owner>

Source: <pointer to the skill/file/note>. <Optional: 1 line on what that source does not cover.>

## Package: <name>        ← monorepo only, where a package diverges

<What differs in this package and why.>
```

Section order: most structural first (architecture, boundaries with other services), most local last (naming, git).

---

## decisions/ADR-NNNN - Title.md (project level)

Based on the ADR format from `domain-modeling`. Sequential 4-digit numbering: take the highest number in `decisions/` and add 1.

```markdown
---
status: accepted
repos: [<repo-a>, <repo-b>]
origin: <where the decision was extracted from: [[session note]], `CLAUDE.md`, code at `<path>`, or "user on YYYY-MM-DD">
---

# <Short title of the decision>

<1–3 sentences: context, what was decided, and why.>
```

Optional sections, only when they add value:
- **Considered Options**: when the rejection is non-obvious and someone will suggest it again.
- **Consequences**: downstream effects not visible in the code.

`status`: `proposed | accepted | deprecated | superseded by ADR-NNNN`. If the reason for the decision was found in no source, use `status: proposed` and add `> [!question] What was the reason?` to the body. `repos` is omitted in a single-repo project.

---

## Home.md (only when creating a new vault)

```markdown
# <PROJECT>

<1 sentence: what the project is.>

## Standards

- [[standards/Glossary|Glossary]]
- [[standards/Conventions|Conventions]]
- <one line per repo: [[standards/<REPO>/Before You Develop|<REPO>]]>
```
