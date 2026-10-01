"""Path confinement (Windows and POSIX flavors) and glob matching."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from crew.agents.pathjail import PathJail, detect_flavor, matches_any_glob

from .factories import POSIX_WS, WINDOWS_WS


def test_flavor_detection() -> None:
    assert detect_flavor(WINDOWS_WS) == "windows"
    assert detect_flavor("C:/work/crew") == "windows"
    assert detect_flavor(POSIX_WS) == "posix"


# (raw, inside, rel)
WINDOWS_CASES: list[tuple[str, bool, str | None]] = [
    ("C:\\work\\crew\\T-1\\src\\a.py", True, "src/a.py"),
    ("C:/work/crew/T-1/src/a.py", True, "src/a.py"),
    ("c:\\WORK\\Crew\\t-1\\x", True, "x"),
    ("src\\a.py", True, "src/a.py"),
    ("src/a.py", True, "src/a.py"),
    ("./src/../src/a.py", True, "src/a.py"),
    ("C:\\work\\crew\\T-1", True, ""),
    (".", True, ""),
    ("\\\\?\\C:\\work\\crew\\T-1\\x", True, "x"),
    ("/c/work/crew/T-1/x", True, "x"),
    ("/cygdrive/c/work/crew/T-1/x", True, "x"),
    ("..\\x", False, None),
    ("../T-2/x", False, None),
    ("C:\\work\\crew\\T-1\\..\\T-2\\x", False, None),
    ("C:\\work\\crew\\T-10\\x", False, None),  # prefix trap
    ("C:\\work\\crew\\T-1x\\x", False, None),
    ("C:\\work\\crew", False, None),
    ("D:\\work\\crew\\T-1\\x", False, None),
    ("C:\\Windows\\System32", False, None),
    ("\\\\server\\share\\x", False, None),
    ("//server/share/x", False, None),
    ("\\\\?\\UNC\\server\\share", False, None),
    ("/etc/passwd", False, None),
    ("\\rooted\\on\\current\\drive", False, None),
    ("/d/work/crew/T-1/x", False, None),
]

POSIX_CASES: list[tuple[str, bool, str | None]] = [
    ("/work/crew/T-1/src/a.py", True, "src/a.py"),
    ("src/a.py", True, "src/a.py"),
    ("./src/../src/a.py", True, "src/a.py"),
    ("/work/crew/T-1", True, ""),
    (".", True, ""),
    ("/work/crew/T-1/", True, ""),
    ("/work/crew/T-1/../T-1/x", True, "x"),
    ("../x", False, None),
    ("src/../../x", False, None),
    ("/work/crew/T-1/../T-2/x", False, None),
    ("/work/crew/T-10/x", False, None),
    ("/work/crew", False, None),
    ("/etc/passwd", False, None),
    ("/", False, None),
    ("C:/Windows/x", False, None),
    ("D:\\x", False, None),
]

UNRESOLVABLE = [
    "",
    "~/x",
    "~",
    "$HOME/x",
    "${HOME}/x",
    "`pwd`/x",
    "$(pwd)/x",
    "%USERPROFILE%\\x",
    "a\x00b",
]


@pytest.mark.parametrize(("raw", "inside", "rel"), WINDOWS_CASES)
def test_windows_flavor(raw: str, inside: bool, rel: str | None) -> None:
    r = PathJail(WINDOWS_WS).resolve(raw)
    assert r is not None
    assert (r.inside, r.rel) == (inside, rel)


@pytest.mark.parametrize(("raw", "inside", "rel"), POSIX_CASES)
def test_posix_flavor(raw: str, inside: bool, rel: str | None) -> None:
    r = PathJail(POSIX_WS).resolve(raw)
    assert r is not None
    assert (r.inside, r.rel) == (inside, rel)


@pytest.mark.parametrize("ws", [WINDOWS_WS, POSIX_WS])
@pytest.mark.parametrize("raw", UNRESOLVABLE)
def test_unresolvable_is_none(ws: str, raw: str) -> None:
    assert PathJail(ws).resolve(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["C:foo", "src\\a.py:stream", "src\\a.py.", "src\\a.py ", "src\\.. \\x"],
)
def test_windows_only_traps_are_unresolvable(raw: str) -> None:
    assert PathJail(WINDOWS_WS).resolve(raw) is None


def test_relative_resolution_uses_cwd() -> None:
    jail = PathJail(POSIX_WS)
    inside = jail.resolve("../x", cwd="/work/crew/T-1/sub")
    assert inside is not None
    assert (inside.inside, inside.rel) == (True, "x")
    outside = jail.resolve("../../x", cwd="/work/crew/T-1/sub")
    assert outside is not None
    assert outside.inside is False


def test_real_symlink_escape_is_detected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    out = tmp_path / "out"
    ws.mkdir()
    out.mkdir()
    (out / "secret.txt").write_text("x", encoding="utf-8")
    try:
        os.symlink(out, ws / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks not permitted on this host")
        # no symlink privilege on Windows: a directory junction needs none and escapes the same way
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(ws / "link"), str(out)], capture_output=True, check=False
        )
        if made.returncode != 0:
            pytest.skip("neither symlinks nor junctions available")
    jail = PathJail(str(ws))
    escaped = jail.resolve("link/secret.txt")
    assert escaped is not None
    assert escaped.inside is False
    ok = jail.resolve("normal.txt")
    assert ok is not None
    assert ok.inside is True


# ---------------- globs ----------------
GLOB_CASES: list[tuple[str, bool]] = [
    ("tests/test_a.py", True),
    ("tests/unit/test_a.py", True),
    ("tests/conftest.py", True),
    ("tests/data/x.json", True),
    ("test_a.py", True),
    ("pkg/test_a.py", True),
    ("pkg/sub/test_a.py", True),
    ("a.test.ts", True),
    ("web/a.test.tsx", True),
    ("web/a.spec.ts", True),
    ("web/a.spec.tsx", True),
    ("web/__tests__/a.ts", True),
    ("web/__tests__/deep/a.ts", True),
    ("src/a.py", False),
    ("shop/report.py", False),
    ("tests", False),
    ("src/tests_helper.py", False),
    ("mytests/a.py", False),
    ("contest.py", False),
    ("web/a.ts", False),
    ("web/a.test.ts.bak", False),
]


@pytest.mark.parametrize(("rel", "expected"), GLOB_CASES)
def test_default_test_globs(rel: str, expected: bool) -> None:
    from crew.agents.specs import DEFAULT_TEST_GLOBS

    assert matches_any_glob(rel, DEFAULT_TEST_GLOBS, ignore_case=False) is expected


def test_glob_case_sensitivity_switch() -> None:
    assert matches_any_glob("Tests/A.py", ["tests/**"], ignore_case=True)
    assert not matches_any_glob("Tests/A.py", ["tests/**"], ignore_case=False)


def test_glob_backslash_input_and_custom_patterns() -> None:
    assert matches_any_glob("tests\\unit\\a.py", ["tests/**"], ignore_case=False)
    assert matches_any_glob("spec/a_spec.rb", ["spec/**", "**/*_spec.rb"], ignore_case=False)
    assert matches_any_glob("a/b.py", ["a/?.py"], ignore_case=False)
    assert not matches_any_glob("a/bb.py", ["a/?.py"], ignore_case=False)
    assert matches_any_glob("a/b1.py", ["a/b[0-9].py"], ignore_case=False)
    assert not matches_any_glob("a/bx.py", ["a/b[!x].py"], ignore_case=False)
    assert not matches_any_glob("src/a.py", [], ignore_case=False)
