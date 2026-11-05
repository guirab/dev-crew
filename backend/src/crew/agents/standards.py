"""Project standards base (written by the ``project-standards`` skill in the Obsidian vault).

The agents cannot read outside the worktree (guards), so the worker reads the base on the host and the
runner appends it to the system prompt. Read on every job: the files may change without a restart.

``dir`` is the repo's folder in the base: ``<vault>/standards`` in a single-repo project,
``<vault>/standards/<REPO>`` in a workspace (shared ``Glossary.md``, ``Conventions.md`` and
``decisions/`` one level up, ADRs filtered by their ``repos:`` frontmatter).
"""

from __future__ import annotations

from pathlib import Path

import structlog

from .. import vaults

log = structlog.get_logger(__name__)

MAX_CHARS = 24_000
BEFORE = "Before You Develop.md"
CONVENTIONS = "Conventions.md"
GLOSSARY = "Glossary.md"
FULL_AGENTS = frozenset({"planner", "developer", "reviewer"})
READERS = FULL_AGENTS | {"tester"}  # the Tester only gets the testing sections
RETIRED = ("superseded", "deprecated")

Meta = dict[str, str | list[str]]


def dir_for(repo: str, repo_paths: dict[str, Path], overrides: dict[str, Path]) -> Path | None:
    """The repo's folder in the base, resolved now (D82): a base created earlier in this task counts.

    A repo registered after the worker started (added from the UI) is read from the registry.
    """
    path, override = repo_paths.get(repo), overrides.get(repo)
    if path is None and override is None:
        from .. import projects  # lazy: only for repos the worker did not know at startup

        found = next((r for r in projects.load_registered() if r.name == repo), None)
        if found is None:
            return None
        path, override = found.path, found.standards_dir
    if override is not None:
        return override
    assert path is not None
    return vaults.resolve(path).standards_dir


def has_base(dir: Path) -> bool:
    """There are base files at ``dir`` (what ``load`` would read)."""
    return _files(dir) is not None


def load(dir: Path | None, agent: str) -> str:
    """The base as Markdown for ``agent``, or ``""``. Never raises: a broken base must not fail the job."""
    if agent not in READERS:
        return ""
    if dir is None:
        log.debug("standards_missing", agent=agent, reason="not_configured")
        return ""
    try:
        return _load(dir, agent)
    except Exception as e:  # a broken base only costs the standards, never the job
        log.warning("standards_unreadable", dir=str(dir), error=str(e))
        return ""


def _load(dir: Path, agent: str) -> str:
    found = _files(dir)
    if found is None:
        log.warning("standards_missing", dir=str(dir), agent=agent)
        return ""
    workspace, files = found
    root = dir.parent if workspace else dir
    blocks: list[tuple[str, str]] = []
    for path in files:
        if agent == "tester" and path.name != CONVENTIONS:
            continue
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.warning("standards_file_skipped", path=str(path), error=str(e))
            continue
        if path.parent.name == "decisions" and not _adr_applies(
            _frontmatter(text), dir.name if workspace else None
        ):
            continue
        if agent == "tester":
            text = _test_sections(text)
        if text.strip():
            blocks.append((path.relative_to(root.parent).as_posix(), text.strip()))
    return _fit(blocks)


def _files(dir: Path) -> tuple[bool, list[Path]] | None:
    """(workspace?, files in prompt order) or ``None`` when there is no base at ``dir``."""
    if not dir.is_dir():
        return None
    parent = dir.parent
    workspace = not (dir / GLOSSARY).is_file() and (parent / GLOSSARY).is_file()
    root = parent if workspace else dir
    candidates = [dir / BEFORE, dir / CONVENTIONS]
    if workspace:
        candidates.append(parent / CONVENTIONS)
    candidates.append(root / GLOSSARY)
    candidates += sorted((root / "decisions").glob("ADR-*.md"))
    found = [p for p in candidates if p.is_file()]
    return (workspace, found) if found else None


def _fit(blocks: list[tuple[str, str]]) -> str:
    """Whole files, in order, while they fit in ``MAX_CHARS``; the others are listed, never cut."""
    out: list[str] = []
    omitted: list[str] = []
    size = 0
    for label, text in blocks:
        block = f"### {label}\n\n{text}"
        if size + len(block) + 2 > MAX_CHARS:
            omitted.append(label)
            continue
        out.append(block)
        size += len(block) + 2
    if omitted:
        out.append(f"[omitidos por tamanho: {', '.join(omitted)}]")
    return "\n\n".join(out)


def _adr_applies(meta: Meta, repo: str | None) -> bool:
    status = meta.get("status", "")
    if isinstance(status, str) and status.strip().lower().startswith(RETIRED):
        return False
    repos = meta.get("repos")
    if repo is None or repos is None:  # single-repo project, or an ADR for every repo
        return True
    names = repos if isinstance(repos, list) else [repos]
    return repo.lower() in {n.lower() for n in names}


def _frontmatter(text: str) -> Meta:
    """Minimal YAML frontmatter: ``key: value``, inline lists ``[a, b]`` and block lists ``- a``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: Meta = {}
    key = ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        items = meta.get(key)
        if stripped.startswith("- ") and isinstance(items, list):
            items.append(_unquote(stripped[2:]))
            continue
        k, sep, value = line.partition(":")
        if not sep or line[:1].isspace():
            continue
        key, value = k.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [_unquote(v) for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = _unquote(value) if value else []
    return meta


def _unquote(value: str) -> str:
    return value.strip().strip("\"'")


def _test_sections(text: str) -> str:
    """Only the ``## ...`` sections whose title mentions tests (for the Tester)."""
    sections: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = [line] if "test" in line.lower() else None
            if current is not None:
                sections.append(current)
        elif line.startswith("# "):
            current = None
        elif current is not None:
            current.append(line)
    return "\n\n".join("\n".join(s).strip() for s in sections)
