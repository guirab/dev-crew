"""Small POSIX-shell lexer used by the Bash guard.

It is not a full shell: it splits a command line into simple commands (words + redirections), expands
quoting, and surfaces every nested command (``$(...)``, backticks, process substitution, heredoc bodies
that expand) so the guard can inspect them too. Anything it cannot parse raises ``ShellParseError`` and
the guard fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

WRITE_REDIRECT_OPS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})
_FD_DUP_TARGET = re.compile(r"^(\d+-?|-)$")


class ShellParseError(ValueError):
    pass


@dataclass
class Word:
    text: str
    dynamic: bool = False
    """True when the word contains an expansion we cannot evaluate ($VAR, $(...), backticks, ...)."""


@dataclass
class Redirect:
    op: str
    target: Word | None

    @property
    def writes(self) -> bool:
        if self.op in WRITE_REDIRECT_OPS:
            return True
        if self.op == ">&":  # `>&2` duplicates a descriptor, `>&file` writes the file
            return self.target is not None and not _FD_DUP_TARGET.match(self.target.text)
        return False


@dataclass
class Cmd:
    words: list[Word] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)


@dataclass
class ParsedShell:
    commands: list[Cmd]
    nested: list[str]


_SPECIAL_PARAMS = set("?@*#!$-0123456789")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _match_paren(s: str, open_idx: int) -> int:
    """Index of the ``)`` that closes the ``(`` at ``open_idx`` (quote and nesting aware)."""
    depth = 0
    i = open_idx
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            end = s.find("'", i + 1)
            if end == -1:
                break
            i = end + 1
            continue
        if c == '"':
            i += 1
            while i < len(s) and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ShellParseError("parêntese sem fechamento")


def _scan_substitutions(text: str) -> list[str]:
    """Inner commands of every ``$(...)`` and backtick pair found in ``text`` (heredoc bodies, ${...})."""
    found: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("$(", i):
            close = _match_paren(text, i + 1)
            found.append(text[i + 2 : close])
            i = close + 1
        elif text[i] == "`":
            end = text.find("`", i + 1)
            if end == -1:
                raise ShellParseError("crase sem fechamento")
            found.append(text[i + 1 : end])
            i = end + 1
        else:
            i += 1
    return found


class _Scanner:
    def __init__(self, src: str) -> None:
        self.s = src
        self.n = len(src)
        self.i = 0
        self.cmds: list[Cmd] = []
        self.nested: list[str] = []
        self.cur = Cmd()
        self.buf: list[str] = []
        self.in_word = False
        self.dynamic = False
        self.word_quoted = False
        self.pending_op: str | None = None
        self.heredocs: list[tuple[str, bool, bool]] = []  # (delimiter, strip_tabs, quoted)

    # ---- word / command bookkeeping ----
    def add(self, text: str) -> None:
        self.buf.append(text)
        self.in_word = True

    def end_word(self) -> None:
        if not self.in_word:
            return
        word = Word("".join(self.buf), self.dynamic)
        if self.pending_op is not None:
            op = self.pending_op
            self.pending_op = None
            if op in ("<<", "<<-"):
                self.heredocs.append((word.text, op == "<<-", self.word_quoted))
            self.cur.redirects.append(Redirect(op, word))
        else:
            self.cur.words.append(word)
        self.buf = []
        self.in_word = False
        self.dynamic = False
        self.word_quoted = False

    def end_cmd(self) -> None:
        self.end_word()
        if self.pending_op is not None:
            raise ShellParseError("redirecionamento sem alvo")
        if self.cur.words or self.cur.redirects:
            self.cmds.append(self.cur)
        self.cur = Cmd()

    # ---- main loop ----
    def run(self) -> ParsedShell:
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c in " \t\r":
                self.end_word()
                self.i += 1
            elif c == "\n":
                self.end_cmd()
                self.i += 1
                if self.heredocs:
                    self.read_heredocs()
            elif c == "\\":
                nxt = s[self.i + 1] if self.i + 1 < self.n else ""
                if nxt == "\n":
                    self.i += 2
                elif nxt:
                    self.add(nxt)
                    self.i += 2
                else:
                    self.add("\\")
                    self.i += 1
            elif c == "'":
                self.single_quote()
            elif c == '"':
                self.double_quote()
            elif c == "$":
                self.dollar(in_dq=False)
            elif c == "`":
                self.backtick()
            elif c == "#" and not self.in_word:
                end = s.find("\n", self.i)
                self.i = self.n if end == -1 else end
            elif c in ";|":
                self.end_cmd()
                self.i += 1
            elif c == "&":
                if s.startswith("&>", self.i):
                    self.redirect()
                else:
                    self.end_cmd()
                    self.i += 1
            elif c in "()":
                self.end_cmd()
                self.i += 1
            elif c in "<>":
                self.redirect()
            else:
                self.add(c)
                self.i += 1
        self.end_cmd()
        return ParsedShell(self.cmds, self.nested)

    # ---- quoting ----
    def single_quote(self) -> None:
        end = self.s.find("'", self.i + 1)
        if end == -1:
            raise ShellParseError("aspas simples sem fechamento")
        self.add(self.s[self.i + 1 : end])
        self.word_quoted = True
        self.i = end + 1

    def double_quote(self) -> None:
        s = self.s
        self.in_word = True
        self.word_quoted = True
        self.i += 1
        while True:
            if self.i >= self.n:
                raise ShellParseError("aspas duplas sem fechamento")
            c = s[self.i]
            if c == '"':
                self.i += 1
                return
            if c == "\\" and self.i + 1 < self.n and s[self.i + 1] in '"\\$`\n':
                if s[self.i + 1] != "\n":
                    self.add(s[self.i + 1])
                self.i += 2
            elif c == "$":
                self.dollar(in_dq=True)
            elif c == "`":
                self.backtick()
            else:
                self.add(c)
                self.i += 1

    def dollar(self, *, in_dq: bool) -> None:
        s = self.s
        nxt = s[self.i + 1] if self.i + 1 < self.n else ""
        if nxt == "(":
            close = _match_paren(s, self.i + 1)
            self.nested.append(s[self.i + 2 : close])
            self.add("$(...)")
            self.dynamic = True
            self.i = close + 1
        elif nxt == "{":
            end = s.find("}", self.i + 2)
            if end == -1:
                raise ShellParseError("${ sem fechamento")
            inner = s[self.i + 2 : end]
            self.nested.extend(_scan_substitutions(inner))
            self.add("${" + inner + "}")
            self.dynamic = True
            self.i = end + 1
        elif nxt == "'" and not in_dq:
            j = self.i + 2
            while j < self.n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            if j >= self.n:
                raise ShellParseError("$'...' sem fechamento")
            self.add(s[self.i + 2 : j])
            self.dynamic = True  # escapes like \x2e can spell anything
            self.i = j + 1
        elif nxt == '"' and not in_dq:
            self.i += 1  # locale string: handled as a plain double-quoted string
        elif m := _IDENT.match(s, self.i + 1):
            self.add("$" + m.group(0))
            self.dynamic = True
            self.i = m.end()
        elif nxt and nxt in _SPECIAL_PARAMS:
            self.add("$" + nxt)
            self.dynamic = True
            self.i += 2
        else:
            self.add("$")
            self.i += 1

    def backtick(self) -> None:
        end = self.s.find("`", self.i + 1)
        while end != -1 and self.s[end - 1] == "\\":
            end = self.s.find("`", end + 1)
        if end == -1:
            raise ShellParseError("crase sem fechamento")
        self.nested.append(self.s[self.i + 1 : end].replace("\\`", "`"))
        self.add("`...`")
        self.dynamic = True
        self.i = end + 1

    # ---- redirections ----
    def redirect(self) -> None:
        s = self.s
        c = s[self.i]
        if c in "<>" and s.startswith("(", self.i + 1):  # process substitution <(cmd) / >(cmd)
            close = _match_paren(s, self.i + 1)
            self.nested.append(s[self.i + 2 : close])
            self.add(f"{c}(...)")
            self.dynamic = True
            self.i = close + 1
            return
        if self.in_word and "".join(self.buf).isdigit() and self.pending_op is None:
            self.buf = []  # explicit file descriptor prefix (2>file)
            self.in_word = False
            self.dynamic = False
        else:
            self.end_word()
        for op in ("&>>", "&>", "<<<", "<<-", "<<", "<&", "<>", ">>", ">&", ">|", ">", "<"):
            if s.startswith(op, self.i):
                self.i += len(op)
                self.pending_op = op
                return
        raise ShellParseError("redirecionamento inválido")  # pragma: no cover

    def read_heredocs(self) -> None:
        s = self.s
        for delim, strip_tabs, quoted in self.heredocs:
            body: list[str] = []
            while self.i < self.n:
                end = s.find("\n", self.i)
                line = s[self.i : self.n if end == -1 else end]
                self.i = self.n if end == -1 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                body.append(line)
            if not quoted:
                self.nested.extend(_scan_substitutions("\n".join(body)))
        self.heredocs = []


def parse(src: str) -> ParsedShell:
    """Split ``src`` into simple commands and collect nested command strings."""
    return _Scanner(src).run()
