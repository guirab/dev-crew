"""Security guards for agent tool calls (``PreToolUse`` hooks).

Rules enforced here (CLAUDE.md): agents never commit/push/rewrite git state, never install dependencies,
never touch the network, never write outside the worktree. The Tester writes only test files; the
Reviewer and Planner are read-only; the Interviewer has no Bash.

This is a policy filter, not a sandbox: an agent can still run ``python script.py`` and do anything the
script does. Real isolation (Docker/sandbox) is an M5 item; see docs/spikes/agent-sdk.md.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import structlog
from claude_agent_sdk import HookContext, HookInput, HookMatcher
from claude_agent_sdk.types import HookEvent, PreToolUseHookSpecificOutput, SyncHookJSONOutput

from ..contracts import AgentJob
from .pathjail import PathJail, expand_braces, is_unresolvable, matches_any_glob
from .runtool import RUN_FULL_NAME, effective_tools
from .shellparse import Cmd, ParsedShell, ShellParseError, Word, parse
from .specs import AgentSpec, BashMode, WriteMode, effective_test_globs
from .submit import full_tool_name

log = structlog.get_logger(__name__)

MAX_NESTING = 4


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None


ALLOW = Decision(True)


def deny(reason: str) -> Decision:
    return Decision(False, reason)


@dataclass(frozen=True)
class GuardPolicy:
    workspace: str
    tools: frozenset[str]
    """Built-in tools plus the full name of the submit tool."""
    bash: BashMode = "none"
    write: WriteMode = "none"
    test_globs: tuple[str, ...] = ()


# ---------------------------------------------------------------- reasons
R_NETWORK = "acesso à rede não é permitido para agentes."
R_PRIVILEGE = "elevação de privilégio não é permitida."
R_SYSTEM = "comando de sistema/destrutivo não é permitido."
R_INSTALL = "instalar dependência precisa de aprovação humana: registre a necessidade em notes do resultado."
R_GIT = (
    "agentes não alteram o estado do git (sem commit, push, checkout, reset, stash...); o resultado fica "
    "sem commit. Para leitura use git status, diff, log ou show."
)
R_SHELL_STDIN = "shell lendo comandos de stdin/pipe não é analisável; rode o comando diretamente."
R_DYNAMIC = "caminho/comando dinâmico ($VAR, $(...), crase) não é permitido aqui; use valores literais."
R_SENSITIVE = "arquivo ou diretório sensível (credenciais/segredos); não é necessário para a tarefa."
R_ENV = "variável de ambiente sensível (segredo/token/chave) não pode ser lida."

DENY_ALWAYS: dict[str, str] = {
    **dict.fromkeys(
        (
            "curl",
            "wget",
            "invoke-webrequest",
            "iwr",
            "invoke-restmethod",
            "irm",
            "start-bitstransfer",
            "ssh",
            "scp",
            "sftp",
            "ftp",
            "telnet",
            "nc",
            "ncat",
            "netcat",
            "nmap",
            "socat",
            "bitsadmin",
            "certutil",
            "mshta",
            "rsync",
        ),
        R_NETWORK,
    ),
    **dict.fromkeys(("sudo", "su", "doas", "runas"), R_PRIVILEGE),
    **dict.fromkeys(
        (
            "format",
            "mkfs",
            "diskpart",
            "dd",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "stop-computer",
            "restart-computer",
            "format-volume",
            "taskkill",
            "pkill",
            "killall",
            "schtasks",
            "crontab",
            "reg",
            "regsvr32",
            "rundll32",
            "wsl",
            "docker",
            "podman",
            "kubectl",
            "printenv",
        ),
        R_SYSTEM,
    ),
    "eval": "eval executa texto arbitrário e não é analisável; rode o comando diretamente.",
    "xargs": "xargs monta comandos dinamicamente e não é analisável; use comandos com caminhos explícitos.",
    **dict.fromkeys(("powershell", "pwsh", "cmd"), "a tool Bash roda bash; não invoque PowerShell/cmd."),
    **dict.fromkeys(
        (
            "apt",
            "apt-get",
            "dpkg",
            "yum",
            "dnf",
            "brew",
            "choco",
            "winget",
            "scoop",
            "pacman",
            "apk",
            "snap",
            "gem",
            "composer",
            "nuget",
            "conda",
            "mamba",
            "micromamba",
            "pipx",
            "easy_install",
            "uvx",
            "bunx",
            "pnpx",
        ),
        R_INSTALL,
    ),
}

SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ash"})
KEYWORDS = frozenset(
    {
        "{",
        "}",
        "!",
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "do",
        "done",
        "while",
        "until",
        "for",
        "in",
        "case",
        "esac",
        "select",
        "function",
    }
)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
ENV_SECRET = re.compile(
    r"\$\{?\w*?(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|ANTHROPIC)\w*|\$\{?(?:\w*_)?PAT(?:_\w*)?\b",
    re.IGNORECASE,
)

RM_LIKE = frozenset({"rm", "rmdir", "del", "erase", "rd", "remove-item", "ri", "unlink", "shred"})
WRITE_LIKE = frozenset(
    {
        "mv",
        "mkdir",
        "touch",
        "tee",
        "truncate",
        "chmod",
        "chown",
        "chgrp",
        "rename",
        "patch",
        "tar",
        "unzip",
        "7z",
        "7za",
        "expand-archive",
    }
)
COPY_LIKE = frozenset({"cp", "install", "ln"})
SKIP_FIRST_POSITIONAL = frozenset({"chmod", "chown", "chgrp"})
INPLACE_EDITORS = frozenset({"sed", "perl", "awk", "gawk"})
READONLY_PROGRAMS = frozenset(
    {
        "ls",
        "dir",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "find",
        "pwd",
        "echo",
        "printf",
        "tree",
        "stat",
        "file",
        "diff",
        "sort",
        "uniq",
        "cut",
        "basename",
        "dirname",
        "realpath",
        "which",
        "type",
        "true",
        "false",
        "test",
        "[",
        "cd",
        "date",
    }
)
GREP_LIKE = frozenset({"grep", "egrep", "fgrep", "rg"})
FIND_ACTIONS = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
)

# wrapper programs: (bare flags, flags that take a value, regexes for attached-value flags)
_Flags = tuple[frozenset[str], frozenset[str], tuple[re.Pattern[str], ...]]
WRAPPERS: dict[str, _Flags] = {
    "command": (frozenset({"-p", "-v", "-V"}), frozenset(), ()),
    "builtin": (frozenset(), frozenset(), ()),
    "exec": (frozenset({"-l"}), frozenset(), ()),
    "nohup": (frozenset(), frozenset(), ()),
    "setsid": (frozenset({"-c", "-f", "-w", "--fork", "--wait", "--ctty"}), frozenset(), ()),
    "time": (frozenset({"-p", "-v"}), frozenset(), ()),
    "stdbuf": (frozenset(), frozenset(), (re.compile(r"-[oei]\S+"),)),
    "env": (
        frozenset({"-i", "--ignore-environment", "-0", "--null", "-v", "--debug"}),
        frozenset({"-u", "--unset", "-C", "--chdir"}),
        (re.compile(r"--(unset|chdir)=.+"),),
    ),
    "timeout": (
        frozenset({"--foreground", "--preserve-status", "-v", "--verbose"}),
        frozenset({"-s", "-k", "--signal", "--kill-after"}),
        (re.compile(r"--(signal|kill-after)=.+"),),
    ),
    "nice": (
        frozenset(),
        frozenset({"-n", "--adjustment"}),
        (re.compile(r"-\d+"), re.compile(r"--adjustment=.+")),
    ),
}

GIT_READ = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "blame",
        "ls-files",
        "ls-tree",
        "rev-parse",
        "rev-list",
        "describe",
        "shortlog",
        "merge-base",
        "cat-file",
        "show-ref",
        "grep",
        "diff-tree",
        "diff-index",
        "diff-files",
        "name-rev",
        "check-ignore",
        "for-each-ref",
        "whatchanged",
        "version",
        "help",
    }
)
GIT_SAFE_GLOBALS = frozenset({"--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs"})
GIT_FORBIDDEN_FLAGS = ("--output", "-O", "--open-files-in-pager", "--no-index")
GIT_BRANCH_FLAGS = frozenset(
    {
        "--show-current",
        "--list",
        "-l",
        "-a",
        "--all",
        "-r",
        "--remotes",
        "-v",
        "-vv",
        "--verbose",
        "--no-color",
        "--color",
    }
)

NPM_ALLOWED = frozenset({"ci", "run", "run-script", "test", "t", "tst", "start", "stop", "ls", "list"})
NPM_VALUE_FLAGS = frozenset({"--prefix", "-C", "--workspace", "-w", "--cache", "--registry"})
NODE_PM_DENIED = frozenset(
    {
        "add",
        "install",
        "i",
        "up",
        "update",
        "upgrade",
        "remove",
        "rm",
        "uninstall",
        "dlx",
        "create",
        "init",
        "publish",
        "link",
        "unlink",
        "global",
        "import",
        "patch",
        "set",
        "config",
        "login",
        "x",
        "pm",
    }
)
FROZEN_FLAGS = frozenset({"--frozen-lockfile", "--immutable", "--ci"})
PIP_ALLOWED = frozenset({"list", "show", "freeze", "check", "inspect", "help"})
UV_VALUE_FLAGS = frozenset(
    {
        "--directory",
        "--project",
        "--python",
        "-p",
        "--group",
        "--extra",
        "--package",
        "--env-file",
        "--index",
        "--config-file",
        "--cache-dir",
        "--python-preference",
        "--color",
    }
)
PY_PM_ALLOWED = frozenset({"run", "show", "list", "check", "env", "version"})
PY_PM_PROGRAMS = frozenset({"poetry", "pdm", "hatch", "pipenv", "rye"})
CARGO_DENIED = frozenset(
    {"install", "add", "update", "publish", "fetch", "login", "yank", "remove", "new", "init", "vendor"}
)
GO_DENIED = frozenset({"get", "install"})

SENSITIVE_NAMES = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.kdbx",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".npmrc",
    ".netrc",
    ".pypirc",
    ".git-credentials",
    ".credentials.json",
    "credentials",
    "credentials.json",
    "service-account*.json",
)
SENSITIVE_EXCEPTIONS = (".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults")
SENSITIVE_DIRS = frozenset({".ssh", ".aws", ".azure", ".gnupg", ".kube"})
NULL_DEVICES = frozenset({"/dev/null", "nul", "/dev/stdout", "/dev/stderr", "/dev/tty"})


# ---------------------------------------------------------------- helpers
def is_sensitive(raw: str) -> bool:
    """True for credential/secret files and directories (by name, any location, also ``rev:path``)."""
    cleaned = raw.replace("\\", "/")
    if ":" in cleaned and not re.match(r"^[A-Za-z]:/", cleaned):
        cleaned = cleaned.rsplit(":", 1)[-1]  # git rev:path
    parts = [p for p in cleaned.split("/") if p]
    if any(p.lower() in SENSITIVE_DIRS for p in parts):
        return True
    name = parts[-1].lower() if parts else ""
    if name in SENSITIVE_EXCEPTIONS:
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SENSITIVE_NAMES)


def _program(raw: str) -> str:
    name = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
    for ext in (".exe", ".cmd", ".bat", ".com", ".ps1"):
        name = name.removesuffix(ext)
    return name


def _looks_external(raw: str) -> bool:
    """Arguments that may name a path outside the worktree (absolute, home, drive, UNC or with ``..``)."""
    if not raw:
        return False
    expanded = expand_braces(raw)
    if expanded is None:
        return True
    for candidate in expanded:
        if candidate.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", candidate):
            return True
        if ".." in re.split(r"[\\/]", candidate):
            return True
    return False


def _positionals(words: list[Word], *, win_flags: bool = False) -> list[Word]:
    """Non-flag arguments (``--`` ends flag parsing). ``win_flags`` also skips ``/s``-style flags."""
    out: list[Word] = []
    options_done = False
    for w in words:
        if not options_done and w.text == "--":
            options_done = True
        elif not options_done and w.text.startswith("-") and w.text != "-":
            continue
        elif not options_done and win_flags and re.fullmatch(r"/[A-Za-z?]", w.text):
            continue
        else:
            out.append(w)
    return out


def _flag_values(words: list[Word]) -> list[Word]:
    """Values attached to long options (``--target-directory=/x``) as words."""
    return [
        Word(w.text.split("=", 1)[1], w.dynamic) for w in words if w.text.startswith("--") and "=" in w.text
    ]


def _strip_flags(args: list[Word], spec: _Flags) -> list[Word] | None:
    """Drop the wrapper's own flags; ``None`` when a flag is unknown (cannot tell what runs next)."""
    bare, valued, patterns = spec
    rest = list(args)
    while rest and rest[0].text.startswith("-") and rest[0].text != "-":
        tok = rest.pop(0).text
        if tok == "--":
            break
        if tok in bare or any(p.fullmatch(tok) for p in patterns):
            continue
        if tok in valued and rest:
            rest.pop(0)
            continue
        return None
    return rest


def _first_positional(args: list[Word], value_flags: frozenset[str]) -> int:
    idx = 0
    while idx < len(args):
        tok = args[idx].text
        if tok in value_flags:
            idx += 2
        elif tok.startswith("-"):
            idx += 1
        else:
            return idx
    return len(args)


# ---------------------------------------------------------------- bash policy
class BashChecker:
    def __init__(self, policy: GuardPolicy) -> None:
        self.policy = policy
        self.jail = PathJail(policy.workspace)
        self.cwd = self.jail.root
        self.ignore_case = self.jail.flavor == "windows"

    # ---- entry ----
    def check(self, command: str, depth: int = 0) -> Decision:
        if self.policy.bash == "none":
            return deny("esta tool não está disponível para este agente.")
        if depth > MAX_NESTING:
            return deny("comando aninhado demais para ser analisado; simplifique.")
        try:
            parsed: ParsedShell = parse(command)
        except ShellParseError as e:
            return deny(f"comando não analisável ({e}); simplifique.")
        saved = self.cwd
        try:
            for inner in parsed.nested:
                self.cwd = saved
                if not (d := self.check(inner, depth + 1)).allowed:
                    return d
            self.cwd = saved
            for cmd in parsed.commands:
                if not (d := self._cmd(cmd, depth)).allowed:
                    return d
        finally:
            if depth > 0:  # a nested/subshell `cd` must not leak into the caller
                self.cwd = saved
        return ALLOW

    # ---- simple command ----
    def _cmd(self, cmd: Cmd, depth: int) -> Decision:
        for redirect in cmd.redirects:
            if not (d := self._redirect(redirect.op, redirect.target, redirect.writes)).allowed:
                return d
        return self._words(list(cmd.words), depth) if cmd.words else ALLOW

    def _redirect(self, op: str, target: Word | None, writes: bool) -> Decision:
        if target is None or op in ("<<", "<<-", "<<<"):
            return ALLOW  # heredoc/here-string are data, not paths
        text = target.text
        if op in (">&", "<&") and re.fullmatch(r"\d+-?|-", text):
            return ALLOW
        if is_sensitive(text):
            return deny(R_SENSITIVE)
        if not writes:
            if self.policy.bash == "readonly" and not target.dynamic and not self._inside(text):
                return deny("leitura fora do worktree não é permitida.")
            return ALLOW
        if text.lower() in NULL_DEVICES:
            return ALLOW
        if self.policy.bash == "readonly":
            return deny("este agente é somente leitura: redirecionamento de saída não é permitido.")
        return self._write_target(text, target.dynamic)

    def _inside(self, raw: str) -> bool:
        expanded = expand_braces(raw)
        if expanded is None:
            return False
        for candidate in expanded:
            r = self.jail.resolve(candidate, self.cwd)
            if r is None or not r.inside:
                return False
        return True

    def _write_target(self, raw: str, dynamic: bool) -> Decision:
        if dynamic:
            return deny(R_DYNAMIC)
        expanded = expand_braces(raw)
        if expanded is None:
            return deny("expansão de chaves {a,b} grande demais para ser analisada.")
        for candidate in expanded:
            if not (d := self._write_one(candidate)).allowed:
                return d
        return ALLOW

    def _write_one(self, raw: str) -> Decision:
        r = self.jail.resolve(raw, self.cwd)
        if r is None:
            return deny(f"caminho '{raw}' não resolvível; use caminho literal dentro do worktree.")
        if not r.inside or r.rel is None:
            return deny(f"escrita fora do worktree não é permitida ('{raw}').")
        if ".git" in r.rel.split("/"):
            return deny("o diretório .git é protegido.")
        if is_sensitive(raw):
            return deny(R_SENSITIVE)
        if self.policy.write == "tests_only" and not matches_any_glob(
            r.rel, self.policy.test_globs, ignore_case=self.ignore_case
        ):
            return deny(f"o Tester só altera arquivos de teste ({', '.join(self.policy.test_globs)}).")
        return ALLOW

    # ---- word normalization ----
    def _words(self, words: list[Word], depth: int) -> Decision:
        rest = list(words)
        while rest and ((rest[0].text in KEYWORDS and not rest[0].dynamic) or ASSIGNMENT.match(rest[0].text)):
            rest.pop(0)
        if not rest:
            return ALLOW
        head = rest[0]
        if head.dynamic:
            return deny(R_DYNAMIC)
        prog = _program(head.text)
        args = rest[1:]
        if prog in WRAPPERS:
            return self._wrapper(prog, args, depth)
        return self._program(prog, args, depth)

    def _wrapper(self, prog: str, args: list[Word], depth: int) -> Decision:
        stripped = _strip_flags(args, WRAPPERS[prog])
        if stripped is None:
            return deny(f"opção de '{prog}' não suportada pela guarda; rode o comando diretamente.")
        if prog == "env":
            while stripped and ASSIGNMENT.match(stripped[0].text):
                stripped.pop(0)
            if not stripped:
                return deny("env sem comando imprime o ambiente (segredos); não é permitido.")
        elif prog == "timeout" and stripped:
            stripped.pop(0)  # duration
        return self._words(stripped, depth) if stripped else ALLOW

    # ---- per program ----
    def _program(self, prog: str, args: list[Word], depth: int) -> Decision:
        if prog in DENY_ALWAYS:
            return deny(DENY_ALWAYS[prog])
        if prog.startswith("mkfs."):
            return deny(R_SYSTEM)
        if not (d := self._scan_args(prog, args)).allowed:
            return d
        if prog in SHELLS:
            return self._shell(args, depth)
        if self.policy.bash == "readonly":
            return self._readonly(prog, args)
        if prog == "git":
            return self._git(args)
        if prog in ("cd", "pushd"):
            return self._cd(args)
        if prog == "popd":
            self.cwd = self.jail.root
            return ALLOW
        if prog in RM_LIKE:
            return self._rm(prog, args)
        if prog in COPY_LIKE:
            return self._copy_like(args)
        if prog in WRITE_LIKE or (prog in INPLACE_EDITORS and self._is_inplace(args)):
            return self._write_like(prog, args)
        if prog == "find":
            return self._find(args)
        return self._packages(prog, args, depth)

    @staticmethod
    def _scan_args(prog: str, args: list[Word]) -> Decision:
        """Secrets in env vars and sensitive file names anywhere in the arguments."""
        scanned = args
        if prog in GREP_LIKE:
            first = next((i for i, w in enumerate(args) if not w.text.startswith("-")), None)
            scanned = [w for i, w in enumerate(args) if i != first]  # first positional is the pattern
        elif prog in ("echo", "printf"):
            scanned = []
        elif prog == "git":
            scanned = [w for w in args if re.search(r"[/\\:]", w.text) or w.text.startswith(".")]
        for w in args:
            if ENV_SECRET.search(w.text):
                return deny(R_ENV)
        for w in scanned:
            if not w.dynamic and is_sensitive(w.text):
                return deny(R_SENSITIVE)
        return ALLOW

    def _shell(self, args: list[Word], depth: int) -> Decision:
        for idx, w in enumerate(args):
            if w.text.startswith("-") and not w.text.startswith("--") and "c" in w.text[1:]:
                if idx + 1 >= len(args):
                    return deny(R_SHELL_STDIN)
                if args[idx + 1].dynamic:
                    return deny(R_DYNAMIC)
                return self.check(args[idx + 1].text, depth + 1)
        if self.policy.bash == "readonly":
            return deny("este agente é somente leitura: shells não são permitidos.")
        if not _positionals(args) and not any(w.text in ("--version", "--help") for w in args):
            return deny(R_SHELL_STDIN)
        return ALLOW

    # ---- readonly mode (planner, reviewer) ----
    def _readonly(self, prog: str, args: list[Word]) -> Decision:
        if prog == "git":
            return self._git(args)
        if prog not in READONLY_PROGRAMS:
            return deny(
                f"'{prog}' não é permitido para este agente (somente leitura: git status/diff/log/show, ls, "
                "cat, head, tail, wc, grep, rg, find)."
            )
        if any(w.dynamic for w in args):
            return deny(R_DYNAMIC)
        for word in [*args, *_flag_values(args)]:
            text = word.text
            if text.startswith("-") and "=" not in text:
                continue
            if _looks_external(text):
                if not self._inside(text):
                    return deny(f"leitura fora do worktree não é permitida ('{text}').")
            elif not is_unresolvable(text):
                r = self.jail.resolve(text, self.cwd)  # catches symlinks/junctions leading outside
                if r is not None and not r.inside:
                    return deny(f"leitura fora do worktree não é permitida ('{text}').")
        if prog == "find":
            return self._find(args)
        if prog == "cd":
            return self._cd(args)
        if prog == "rg" and any(w.text.startswith("--pre") for w in args):
            return deny("rg --pre executa programas externos.")
        if prog == "sort" and any(
            w.text in ("-o", "--output") or w.text.startswith("--output=") for w in args
        ):
            return deny("sort -o escreve arquivos; este agente é somente leitura.")
        return ALLOW

    # ---- git ----
    def _git(self, args: list[Word]) -> Decision:
        idx = 0
        while idx < len(args):
            tok = args[idx].text
            if tok in GIT_SAFE_GLOBALS:
                idx += 1
            elif tok == "-C":
                if idx + 1 >= len(args) or args[idx + 1].dynamic or not self._inside(args[idx + 1].text):
                    return deny("git -C só é permitido dentro do worktree.")
                idx += 2
            elif tok in ("--version", "--help", "-h"):
                return ALLOW
            elif tok.startswith("-"):
                return deny(f"opção global do git não permitida ('{tok}'). {R_GIT}")
            else:
                break
        if idx >= len(args):
            return ALLOW  # bare `git` prints usage
        if args[idx].dynamic:
            return deny(R_DYNAMIC)
        sub = args[idx].text
        rest = args[idx + 1 :]
        if sub == "branch":
            if all(w.text in GIT_BRANCH_FLAGS for w in rest):
                return ALLOW
            return deny(f"git branch só lista branches. {R_GIT}")
        if sub in ("tag", "remote"):
            listing = {"-l", "--list", "-n"} if sub == "tag" else {"-v", "--verbose"}
            if all(w.text in listing for w in rest):
                return ALLOW
            return deny(f"git {sub} só em modo lista. {R_GIT}")
        if sub not in GIT_READ:
            return deny(f"git {sub} não permitido. {R_GIT}")
        for w in rest:
            if w.text.startswith(GIT_FORBIDDEN_FLAGS):
                return deny(
                    f"git {sub} {w.text.split('=')[0]} não permitido (escreve ou lê fora do worktree)."
                )
        return ALLOW

    # ---- filesystem commands ----
    def _cd(self, args: list[Word]) -> Decision:
        pos = _positionals(args)
        if not pos:
            return deny(
                "cd sem argumento vai para HOME (fora do worktree); informe um diretório do worktree."
            )
        target = pos[0]
        if target.dynamic or target.text == "-":
            return deny(R_DYNAMIC)
        r = self.jail.resolve(target.text, self.cwd)
        if r is None or not r.inside:
            return deny(f"cd fora do worktree não é permitido ('{target.text}').")
        self.cwd = r.norm
        return ALLOW

    def _rm(self, prog: str, args: list[Word]) -> Decision:
        for word in [*_positionals(args, win_flags=prog in ("del", "erase", "rd")), *_flag_values(args)]:
            if not (d := self._write_target(word.text, word.dynamic)).allowed:
                return d
            r = self.jail.resolve(word.text, self.cwd)
            if r is not None and r.rel == "":
                return deny("não remova a raiz do worktree.")
            if re.search(r"(^|[\\/])\.[^\\/]*[*?\[]", word.text):
                return deny(
                    "glob de dotfiles (.*) pode atingir .git e a raiz; liste os arquivos explicitamente."
                )
        return ALLOW

    @staticmethod
    def _is_inplace(args: list[Word]) -> bool:
        return any(
            w.text == "--in-place"
            or w.text.startswith("--in-place=")
            or bool(re.fullmatch(r"-[A-Za-z]*i\S*", w.text))
            for w in args
            if w.text.startswith("-")
        )

    def _copy_like(self, args: list[Word]) -> Decision:
        """``cp``/``install``/``ln``: sources only need to be inside; the destination is a write."""
        target_dir: Word | None = None
        pos: list[Word] = []
        options_done = False
        skip = False
        for idx, w in enumerate(args):
            if skip:
                skip = False
            elif options_done or not w.text.startswith("-") or w.text == "-":
                pos.append(w)
            elif w.text == "--":
                options_done = True
            elif w.text in ("-t", "--target-directory") and idx + 1 < len(args):
                target_dir, skip = args[idx + 1], True
            elif w.text.startswith("--target-directory="):
                target_dir = Word(w.text.split("=", 1)[1], w.dynamic)
        if target_dir is not None:
            sources, dests = pos, [target_dir]
        elif pos:
            sources, dests = pos[:-1], pos[-1:]
        else:
            return ALLOW
        for w in sources:
            if w.dynamic:
                return deny(R_DYNAMIC)
            if not self._inside(w.text):
                return deny(f"origem fora do worktree não é permitida ('{w.text}').")
        for w in dests:
            if not (d := self._write_target(w.text, w.dynamic)).allowed:
                return d
        return ALLOW

    def _write_like(self, prog: str, args: list[Word]) -> Decision:
        pos = _positionals(args)
        if prog in SKIP_FIRST_POSITIONAL and pos:
            pos = pos[1:]
        for word in [*pos, *_flag_values(args)]:
            if not (d := self._write_target(word.text, word.dynamic)).allowed:
                return d
        return ALLOW

    @staticmethod
    def _find(args: list[Word]) -> Decision:
        for w in args:
            if w.text in FIND_ACTIONS:
                return deny(
                    f"find {w.text} executa/escreve; use find só para listar e aja com comandos explícitos."
                )
        return ALLOW

    # ---- dependency managers ----
    def _packages(self, prog: str, args: list[Word], depth: int) -> Decision:
        texts = [w.text for w in args]
        sub = next((t for t in texts if not t.startswith("-")), "")
        if prog in ("python", "python3", "py"):
            if texts[:2] == ["-m", "pip"]:
                return self._pip(args[2:])
            if "setup.py" in texts and any(t in ("install", "develop") for t in texts):
                return deny(R_INSTALL)
            return ALLOW
        if prog in ("pip", "pip3"):
            return self._pip(args)
        if prog == "npm":
            idx = _first_positional(args, NPM_VALUE_FLAGS)
            npm_sub = args[idx].text if idx < len(args) else ""
            if npm_sub in NPM_ALLOWED:
                return ALLOW
            return deny(
                f"npm {npm_sub or '(sem subcomando)'} não permitido: só ci, run, test, start, ls. {R_INSTALL}"
            )
        if prog == "npx":
            if "--no-install" in texts or "--no" in texts:
                return ALLOW
            return deny(
                "npx pode baixar pacotes da rede: use 'npx --no-install <bin>' ou 'npm run <script>'. "
                + R_INSTALL
            )
        if prog in ("pnpm", "yarn", "bun"):
            if sub in NODE_PM_DENIED and not (sub in ("install", "i") and FROZEN_FLAGS & set(texts)):
                return deny(R_INSTALL)
            return ALLOW
        if prog == "uv":
            return self._uv(args, depth)
        if prog in PY_PM_PROGRAMS:
            if sub == "run":
                return self._run_rest(args, depth)
            return ALLOW if sub in ("", *PY_PM_ALLOWED) else deny(R_INSTALL)
        if prog == "cargo":
            return deny(R_INSTALL) if sub in CARGO_DENIED else ALLOW
        if prog == "go":
            return deny(R_INSTALL) if sub in GO_DENIED else ALLOW
        return ALLOW

    @staticmethod
    def _pip(args: list[Word]) -> Decision:
        sub = next((w.text for w in args if not w.text.startswith("-")), "")
        flags = {w.text for w in args if w.text.startswith("-")}
        if sub in PIP_ALLOWED or (not sub and flags <= {"--version", "-V", "--help", "-h"}):
            return ALLOW
        return deny(R_INSTALL)

    def _uv(self, args: list[Word], depth: int) -> Decision:
        idx = _first_positional(args, UV_VALUE_FLAGS)
        sub = args[idx].text if idx < len(args) else ""
        rest = args[idx + 1 :]
        texts = [w.text for w in rest]
        if sub == "run":
            if any(t.startswith("--with") for t in texts):
                return deny("uv run --with instala pacotes temporários. " + R_INSTALL)
            return self._run_rest(args, depth)
        if sub in ("sync", "tree", "version"):
            return ALLOW
        if sub == "lock" and "--check" in texts:
            return ALLOW
        if sub == "pip":
            return self._pip(rest)
        return deny(R_INSTALL if sub else "uv sem subcomando.")

    def _run_rest(self, args: list[Word], depth: int) -> Decision:
        """Evaluate the command after ``run`` (``uv run pytest``, ``poetry run ruff``)."""
        texts = [w.text for w in args]
        if "run" not in texts:
            return ALLOW
        after = args[texts.index("run") + 1 :]
        inner = after[_first_positional(after, UV_VALUE_FLAGS) :]
        return self._words(inner, depth + 1) if inner else ALLOW


# ---------------------------------------------------------------- tool-level checks
def _str_input(tool_input: Mapping[str, Any], key: str) -> str | None:
    value = tool_input.get(key)
    return value if isinstance(value, str) and value else None


def _check_read_path(jail: PathJail, raw: str) -> Decision:
    if is_sensitive(raw):
        return deny(R_SENSITIVE)
    r = jail.resolve(raw)
    if r is None:
        return deny(f"caminho '{raw}' não resolvível; use caminho literal dentro do worktree.")
    if not r.inside:
        return deny(f"leitura fora do worktree não é permitida ('{raw}').")
    return ALLOW


def _check_pattern(raw: str) -> Decision:
    if _looks_external(raw):
        return deny(f"padrão de busca fora do worktree não é permitido ('{raw}').")
    return ALLOW


def _check_write_path(policy: GuardPolicy, jail: PathJail, raw: str) -> Decision:
    r = jail.resolve(raw)
    if r is None:
        return deny(f"caminho '{raw}' não resolvível; use caminho literal dentro do worktree.")
    if not r.inside or r.rel is None:
        return deny(f"escrita fora do worktree não é permitida ('{raw}').")
    if ".git" in r.rel.split("/"):
        return deny("o diretório .git é protegido.")
    if is_sensitive(raw):
        return deny(R_SENSITIVE)
    if policy.write == "tests_only" and not matches_any_glob(
        r.rel, policy.test_globs, ignore_case=jail.flavor == "windows"
    ):
        return deny(
            f"o Tester só altera arquivos de teste ({', '.join(policy.test_globs)}); "
            "se o código de produção precisa mudar, reporte como failure."
        )
    return ALLOW


def check_tool(policy: GuardPolicy, tool_name: str, tool_input: Mapping[str, Any]) -> Decision:
    """Decide whether one tool call is allowed. Deny by default for anything unknown."""
    if tool_name not in policy.tools:
        return deny(f"a tool '{tool_name}' não está disponível para este agente.")
    if tool_name == RUN_FULL_NAME:  # sandboxed Bash: same policy, defense in depth
        tool_name = "Bash"
    elif tool_name.startswith("mcp__"):
        return ALLOW  # only the submit tool is ever registered under allowed MCP names
    jail = PathJail(policy.workspace)
    match tool_name:
        case "Read":
            raw = _str_input(tool_input, "file_path")
            return deny("Read sem file_path.") if raw is None else _check_read_path(jail, raw)
        case "Glob" | "Grep":
            path = _str_input(tool_input, "path")
            if path and not (d := _check_read_path(jail, path)).allowed:
                return d
            pattern = _str_input(tool_input, "pattern" if tool_name == "Glob" else "glob")
            if pattern and not (d := _check_pattern(pattern)).allowed:
                return d
            return ALLOW
        case "Write" | "Edit" | "MultiEdit" | "NotebookEdit":
            if policy.write == "none":
                return deny("este agente é somente leitura.")
            raw = _str_input(tool_input, "notebook_path" if tool_name == "NotebookEdit" else "file_path")
            return deny(f"{tool_name} sem caminho.") if raw is None else _check_write_path(policy, jail, raw)
        case "Bash":
            command = _str_input(tool_input, "command")
            if command is None:
                return deny("Bash sem command.")
            if tool_input.get("dangerouslyDisableSandbox"):
                return deny("dangerouslyDisableSandbox não é permitido.")
            return BashChecker(policy).check(command)
        case _:
            return deny(f"a tool '{tool_name}' não é suportada pelas guardas.")


def policy_for(spec: AgentSpec[Any], job: AgentJob, workspace: str) -> GuardPolicy:
    return GuardPolicy(
        workspace=workspace,
        tools=frozenset({*effective_tools(spec, job), full_tool_name(spec.submit_name)}),
        bash=spec.bash,
        write=spec.write,
        test_globs=effective_test_globs(job) if spec.write == "tests_only" else (),
    )


BlockCallback = Callable[[str], Awaitable[None]]


def for_agent(
    spec: AgentSpec[Any], job: AgentJob, workspace: str, on_block: BlockCallback | None = None
) -> dict[HookEvent, list[HookMatcher]]:
    """``hooks`` option value: one ``PreToolUse`` hook (all tools) that denies by policy.

    Fails closed: any error inside the guard denies the call. Every denial is reported through
    ``on_block`` (the runner turns it into ``progress{kind: "status"}``).
    """
    policy = policy_for(spec, job, workspace)

    async def pre_tool_use(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> SyncHookJSONOutput:
        data: Mapping[str, object] = input_data
        name = data.get("tool_name")
        tool_input = data.get("tool_input")
        try:
            if not isinstance(name, str) or not isinstance(tool_input, Mapping):
                decision = deny("chamada de tool malformada.")
            else:
                decision = check_tool(policy, name, tool_input)
        except Exception:  # fail closed
            log.exception("guard_error", tool=name)
            decision = deny("erro interno na guarda; chamada bloqueada por segurança.")
        if decision.allowed:
            return {}
        reason = decision.reason or "bloqueado pela política."
        if on_block is not None:
            await on_block(reason)
        output: PreToolUseHookSpecificOutput = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
        return {"hookSpecificOutput": output}

    return {"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]}
