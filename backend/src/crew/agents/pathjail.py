"""Lexical + real-path confinement of file paths to a workspace root (Windows and POSIX flavors).

The check is purely lexical (``ntpath`` / ``posixpath``) so it behaves identically on any host and is
unit-testable with both path styles. When the flavor matches the host and the root exists, the real path
(symlinks/junctions resolved) is checked as well.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from typing import Literal

Flavor = Literal["windows", "posix"]

_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]")
_MSYS_DRIVE = re.compile(r"^\\(?:cygdrive\\)?([A-Za-z])(?:\\(.*))?$")


@dataclass(frozen=True)
class Resolved:
    """Outcome of resolving one path against the jail."""

    inside: bool
    norm: str
    rel: str | None
    """Path relative to the root, with forward slashes (``""`` for the root itself); ``None`` if outside."""


def detect_flavor(path: str) -> Flavor:
    return "windows" if (_DRIVE_ROOT.match(path) or path.startswith("\\\\") or "\\" in path) else "posix"


def is_unresolvable(raw: str) -> bool:
    """Shell/env expansions we cannot evaluate statically."""
    return (
        not raw
        or "\x00" in raw
        or "$" in raw
        or "`" in raw
        or raw.startswith("~")
        or bool(re.search(r"%[^%\s]+%", raw))
    )


class PathJail:
    def __init__(self, root: str) -> None:
        self.flavor: Flavor = detect_flavor(root)
        self._mod = ntpath if self.flavor == "windows" else posixpath
        self.root = self._mod.normpath(root)
        self._real_root: str | None = None
        if (os.name == "nt") == (self.flavor == "windows") and os.path.isdir(self.root):
            self._real_root = os.path.realpath(self.root)

    # ---- normalization ----
    def _windows_abs(self, raw: str, base: str) -> str | None:
        s = raw.replace("/", "\\")
        if s.startswith("\\\\?\\"):
            s = s[4:]
            if s.upper().startswith("UNC\\"):
                return "\\\\" + s[4:]
        if s.startswith("\\\\"):  # UNC / device paths are never inside a local worktree
            return ntpath.normpath(s)
        if m := _MSYS_DRIVE.match(s):
            s = f"{m.group(1).upper()}:\\{m.group(2) or ''}"
        drive, rest = ntpath.splitdrive(s)
        if drive and not rest.startswith("\\"):
            return None  # drive-relative ("C:foo"): depends on a per-drive cwd we do not know
        for comp in rest.split("\\"):
            if comp in ("", ".", ".."):
                continue
            if comp.endswith((".", " ")) or ":" in comp:  # Win32 trims these / NTFS alternate streams
                return None
        if not drive and rest.startswith("\\"):
            return ntpath.normpath(s)  # rooted on the current drive: not mappable, treated as outside
        return ntpath.normpath(s if drive else ntpath.join(base, s))

    def _posix_abs(self, raw: str, base: str) -> str:
        return posixpath.normpath(raw if raw.startswith("/") else posixpath.join(base, raw))

    def _contains(self, root: str, path: str) -> bool:
        if self.flavor == "windows":
            a, b = ntpath.normcase(root), ntpath.normcase(path)
            try:
                return ntpath.commonpath([a, b]) == a
            except ValueError:  # different drives
                return False
        try:
            return posixpath.commonpath([root, path]) == root
        except ValueError:
            return False

    def resolve(self, raw: str, cwd: str | None = None) -> Resolved | None:
        """Resolve ``raw`` (relative to ``cwd``, default root). ``None`` means unresolvable -> deny."""
        if is_unresolvable(raw):
            return None
        base = cwd or self.root
        if self.flavor == "posix" and _DRIVE_ROOT.match(raw):
            return Resolved(False, raw, None)  # a Windows drive path can never be inside a POSIX worktree
        norm = self._windows_abs(raw, base) if self.flavor == "windows" else self._posix_abs(raw, base)
        if norm is None:
            return None
        if not self._contains(self.root, norm):
            return Resolved(False, norm, None)
        if self._real_root is not None:
            real = os.path.realpath(norm)
            if not self._contains(os.path.normpath(self._real_root), os.path.normpath(real)):
                return Resolved(False, norm, None)
        rel = self._mod.relpath(norm, self.root).replace("\\", "/")
        return Resolved(True, norm, "" if rel == "." else rel)


# ---------------- globs ----------------
def _expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end() :]
    return [r for alt in match.group(1).split(",") for r in _expand_braces(head + alt + tail)]


MAX_BRACE_EXPANSIONS = 64


def expand_braces(raw: str) -> list[str] | None:
    """Shell brace expansion (``a{b,c}`` -> ``ab``, ``ac``). ``None`` if it explodes past the limit."""
    out = _expand_braces(raw)
    return out if len(out) <= MAX_BRACE_EXPANSIONS else None


def _segment_regex(seg: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(seg):
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = seg.find("]", i + 2)
            if end == -1:
                out.append(re.escape(c))
            else:
                body = seg[i + 1 : end]
                body = "^" + body[1:] if body.startswith("!") else body
                out.append(f"[{body}]")
                i = end
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def glob_to_regex(pattern: str) -> str:
    """``**`` spans directories (zero or more segments); ``*``/``?`` never cross ``/``."""
    pattern = pattern.replace("\\", "/").removeprefix("./").lstrip("/")
    segs = pattern.split("/")
    parts: list[str] = []
    for idx, seg in enumerate(segs):
        last = idx == len(segs) - 1
        if seg == "**":
            parts.append(".+" if last else "(?:[^/]+/)*")
        else:
            parts.append(_segment_regex(seg) + ("" if last else "/"))
    return "".join(parts)


def matches_any_glob(rel: str, patterns: tuple[str, ...] | list[str], *, ignore_case: bool) -> bool:
    flags = re.IGNORECASE if ignore_case else 0
    rel = rel.replace("\\", "/")
    return any(
        re.fullmatch(glob_to_regex(expanded), rel, flags)
        for pattern in patterns
        for expanded in _expand_braces(pattern)
    )
