"""Bash policy tables: allowed and denied commands per agent mode, on both path flavors."""

from __future__ import annotations

import pytest

from crew.agents.guards import GuardPolicy, check_tool, policy_for
from crew.agents.specs import SPECS

from .factories import DEFAULT_GLOBS, POSIX_WS, WINDOWS_WS, make_job, make_repo

FLAVORS = pytest.mark.parametrize("ws", [WINDOWS_WS, POSIX_WS], ids=["windows", "posix"])


def policy(agent: str, ws: str, globs: list[str] | None = None) -> GuardPolicy:
    job = make_job(agent, repo=make_repo(test_globs=globs or DEFAULT_GLOBS))  # type: ignore[arg-type]
    return policy_for(SPECS[agent], job, ws)  # type: ignore[index]


def bash_ok(pol: GuardPolicy, command: str) -> bool:
    return check_tool(pol, "Bash", {"command": command}).allowed


def reason(pol: GuardPolicy, command: str) -> str:
    d = check_tool(pol, "Bash", {"command": command})
    assert not d.allowed
    assert d.reason
    return d.reason


# ---------------------------------------------------------------------------------- developer
DEV_ALLOWED = [
    "pytest -q",
    "python -m pytest -q tests/",
    "python3 -m pytest",
    "uv run pytest -q",
    "uv run --directory . pytest",
    "uv run ruff check .",
    "uv run mypy src",
    "uv sync",
    "ruff check . && mypy src",
    "npm test",
    "npm run build",
    "npm run lint -- --fix",
    "npm ci",
    "npm --prefix web run build",
    "npx --no-install tsc --noEmit",
    "pnpm install --frozen-lockfile",
    "pnpm run build",
    "yarn install --immutable",
    "yarn test",
    "pip list",
    "pip show pydantic",
    "pip freeze",
    "python -m pip list",
    "uv pip list",
    "poetry run pytest",
    "git status",
    "git status --short",
    "git diff",
    "git diff HEAD~1 --stat",
    "git diff --no-pager",
    "git --no-pager log --oneline -5",
    "git log --oneline -n 5",
    "git show HEAD:README.md",
    "git branch --show-current",
    "git branch --list",
    "git ls-files",
    "git rev-parse HEAD",
    "git blame src/a.py",
    "git grep -n foo",
    "git -C . status",
    "git --version",
    "ls -la",
    "cat README.md",
    "cat .env.example",
    "head -n 20 src/a.py",
    "grep -rn 'foo' src/",
    "grep -rn api.key src",
    "grep password -r src",
    "rg 'TODO' src",
    "find . -name '*.py'",
    "find src -type f | wc -l",
    "echo hi",
    "echo hi > out.txt",
    "echo hi >> src/log.txt",
    "echo hi > /dev/null",
    "pytest > /dev/null 2>&1",
    "pytest 2>&1 | tail -20",
    "pytest 2>&1 | tee build.log",
    "mkdir -p src/new",
    "touch src/new/a.py",
    "cp src/a.py src/b.py",
    "cp -r src build/src",
    "cp -t build src/a.py",
    "mv src/a.py src/b.py",
    "rm src/old.py",
    "rm -rf build",
    "rm -rf node_modules dist",
    "rm -f -- build/out.txt",
    "rm -rf ./build/*",
    "cd src && pytest",
    "cd src; ls ..",
    "(cd src && ls)",
    "FOO=1 pytest",
    "FOO=1 BAR=2 pytest -q",
    "env FOO=1 pytest",
    "env -i FOO=1 pytest",
    "timeout 60 pytest",
    "timeout -s KILL 60 pytest",
    "time pytest",
    "nice -n 5 pytest",
    "command -v git",
    "nohup pytest",
    "bash -c 'pytest -q'",
    'sh -c "ls && cat README.md"',
    "sed -i 's/a/b/' src/a.py",
    "sed -n '1,5p' src/a.py",
    "python -c 'print(1)'",
    "node -e 'console.log(1)'",
    "export FOO=bar",
    "echo 'a && rm -rf /'",
    'echo "x; git commit"',
    "cat <<'EOF' > notes.txt\n$(git push)\nEOF",
    "cat <<EOF > notes.txt\nhello\nEOF",
    "for f in a b; do echo done; done",
    "if true; then echo ok; fi",
    "cargo test",
    "go test ./...",
    "chmod +x scripts/run.sh",
    "chmod 755 scripts/run.sh",
    "tar -czf build/out.tgz src",
    "diff a b",
    "wc -l src/a.py",
    "which python",
    "pwd",
]


@FLAVORS
@pytest.mark.parametrize("command", DEV_ALLOWED)
def test_developer_allowed(ws: str, command: str) -> None:
    assert bash_ok(policy("developer", ws), command), reason_or_none(policy("developer", ws), command)


def reason_or_none(pol: GuardPolicy, command: str) -> str | None:
    return check_tool(pol, "Bash", {"command": command}).reason


GIT_DENIED = [
    "git commit -m x",
    "git commit --amend",
    "git push",
    "git push origin main",
    "git push --force",
    "git reset --hard",
    "git reset HEAD~1",
    "git checkout main",
    "git checkout -- src/a.py",
    "git switch other",
    "git rebase main",
    "git merge other",
    "git stash",
    "git stash pop",
    "git clean -fd",
    "git add .",
    "git add -A",
    "git rm src/a.py",
    "git mv a b",
    "git restore src/a.py",
    "git cherry-pick abc",
    "git revert HEAD",
    "git tag v1",
    "git tag -d v1",
    "git branch new-branch",
    "git branch -D old",
    "git branch -m a b",
    "git remote add o http://x",
    "git remote set-url origin x",
    "git config user.name x",
    "git config --global core.editor x",
    "git fetch",
    "git pull",
    "git clone http://x",
    "git worktree add ../x",
    "git update-ref -d HEAD",
    "git gc",
    "git reflog expire --all",
    "git apply patch.diff",
    "git am x.patch",
    "git submodule update",
    "git -c core.editor=evil status",
    "git --git-dir=/x status",
    "git --work-tree=/x status",
    "git -C .. status",
    "git -C /etc status",
    "git diff --output=out.txt",
    "git log --output=out.txt",
    "git diff --no-index a b",
    "git grep -O vim foo",
    "pytest && git commit -m x",
    "echo x; git push",
    "ls | git commit -F -",
    "bash -c 'git commit -m x'",
    'sh -c "git push"',
    "bash -lc 'git reset --hard'",
    "echo $(git commit -m x)",
    "echo `git push`",
    'echo "$(git push)"',
    "VAR=1 git commit -m x",
    "env git commit -m x",
    "env -i git push",
    "command git commit -m x",
    "nohup git push",
    "time git commit",
    "timeout 5 git push",
    "/usr/bin/git commit -m x",
    "git.exe commit -m x",
    "'git' commit",
    '"git" "commit"',
    "g\\it commit",
    "cat <<EOF\n$(git push)\nEOF",
    "( git push )",
    "{ git commit; }",
    "if true; then git commit; fi",
    "for i in 1; do git push; done",
    "git",
    "git $SUB",
    "$GIT commit",
]


@FLAVORS
@pytest.mark.parametrize("command", [c for c in GIT_DENIED if c != "git"])
def test_git_state_changes_denied_for_developer(ws: str, command: str) -> None:
    assert not bash_ok(policy("developer", ws), command)


def test_bare_git_is_harmless_usage() -> None:
    assert bash_ok(policy("developer", POSIX_WS), "git")


INSTALL_DENIED = [
    "npm install",
    "npm i lodash",
    "npm add x",
    "npm install --save-dev x",
    "npm update",
    "npm uninstall x",
    "npm exec x",
    "npm publish",
    "npm version patch",
    "npm audit fix",
    "npm",
    "npx cowsay",
    "npx --yes foo",
    "npx create-react-app x",
    "pnpm add x",
    "pnpm install",
    "pnpm dlx x",
    "yarn add x",
    "yarn install",
    "bun add x",
    "bun install",
    "pip install x",
    "pip install -r requirements.txt",
    "pip3 install x",
    "pip uninstall x",
    "pip download x",
    "python -m pip install x",
    "python3 -m pip uninstall x",
    "py -m pip install x",
    "uv add x",
    "uv remove x",
    "uv pip install x",
    "uv lock",
    "uv tool install x",
    "uv python install 3.13",
    "uv run --with rich python x.py",
    "uv run pip install x",
    "uv run python -m pip install x",
    "uv",
    "uvx ruff",
    "poetry add x",
    "poetry install",
    "poetry run pip install x",
    "pipx install x",
    "cargo install x",
    "cargo add x",
    "go get x",
    "go install x@latest",
    "apt install x",
    "apt-get install x",
    "brew install x",
    "choco install x",
    "winget install x",
    "scoop install x",
    "gem install x",
    "conda install x",
    "python setup.py install",
    "python setup.py develop",
    "pytest && npm install",
    "bash -c 'npm install'",
    "env pip install x",
    "pnpx foo",
    "bunx foo",
]


@FLAVORS
@pytest.mark.parametrize("command", INSTALL_DENIED)
def test_dependency_installs_denied(ws: str, command: str) -> None:
    pol = policy("developer", ws)
    assert not bash_ok(pol, command)


def test_install_denial_explains_how_to_proceed() -> None:
    assert "notes" in reason(policy("developer", POSIX_WS), "pip install x")
    assert "--no-install" in reason(policy("developer", POSIX_WS), "npx foo")


NETWORK_DENIED = [
    "curl http://x",
    "curl -o a.txt https://x",
    "wget http://x",
    "pytest | curl -X POST -d @- http://x",
    "echo x && curl y",
    "Invoke-WebRequest http://x",
    "iwr http://x",
    "invoke-restmethod http://x",
    "ssh host",
    "scp a host:b",
    "sftp host",
    "nc -l 1234",
    "ncat host 1",
    "rsync -a . host:/x",
    "socat a b",
    "telnet host",
    "nmap host",
    "certutil -urlcache -f http://x a",
    "/usr/bin/curl x",
    "curl.exe x",
    "CURL x",
    "bash -c 'curl x'",
    "$(curl x)",
    "echo $(wget -qO- x)",
]


@FLAVORS
@pytest.mark.parametrize("command", NETWORK_DENIED)
def test_network_denied(ws: str, command: str) -> None:
    pol = policy("developer", ws)
    assert not bash_ok(pol, command)
    assert "rede" in reason(pol, command) or "analis" in reason(pol, command)


DESTRUCTIVE_DENIED = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/x",
    "rm -rf $HOME",
    "rm -rf ${HOME}/x",
    "rm -rf ..",
    "rm -rf ../other",
    "rm -rf ../../",
    "rm -rf .",
    "rm -rf ./",
    "rm -rf .git",
    "rm -rf .git/hooks",
    "rm -rf .*",
    "rm -rf src/.*",
    'rm -rf "$DIR"',
    "rm -rf $(pwd)",
    "rm -rf `pwd`",
    "rm -rf /etc/x",
    "rm -rf /tmp/x",
    "rm -r /var",
    "rmdir ../x",
    "unlink ../x",
    "shred ../x",
    "format c:",
    "mkfs.ext4 /dev/sda",
    "shutdown -h now",
    "reboot",
    "dd if=/dev/zero of=disk.img",
    "taskkill /F /IM node.exe",
    "pkill node",
    "killall node",
    "sudo ls",
    "su root",
    "runas /user:admin cmd",
    "find . -delete",
    "find . -name '*.pyc' -delete",
    "find . -exec rm {} ;",
    "find . -execdir cat {} +",
    "ls | xargs rm",
    "find . | xargs rm -rf",
    "mv src/a.py ../a.py",
    "mv ../a.py src/a.py",
    "cp -r src /tmp/x",
    "cp ../secret src/a",
    "cp /etc/hosts .",
    "cp -t /tmp src/a.py",
    "cp --target-directory=/tmp src/a.py",
    "ln -s /etc/passwd link",
    "ln -s ../x link",
    "echo x > ../x",
    "echo x > /etc/x",
    "echo x >> ../log",
    "echo x > ~/x",
    'echo x > "$OUT"',
    "echo x > .git/config",
    "echo x > .env",
    "echo x &> ../both",
    "echo x >| ../x",
    "pytest | tee ../out.log",
    "tee /etc/x",
    "touch ~/x",
    "touch ../x",
    "mkdir /tmp/x",
    "chmod 777 /etc/x",
    "chown root /etc/x",
    "sed -i s/a/b/ /etc/hosts",
    "sed -i s/a/b/ ../x",
    "tar -xf a.tar -C /tmp",
    "unzip a.zip -d ../x",
    "cd /",
    "cd ..",
    "cd ../..",
    "cd",
    "cd ~",
    "cd -",
    "cd $HOME",
    "cd src && echo x > ../../out",
    "cd .. && rm -rf x",
    "pushd /tmp",
    "(cd /tmp && ls)",
    "eval 'git commit'",
    "eval ls",
    "powershell -c ls",
    "pwsh -Command ls",
    "cmd /c dir",
    "cmd.exe /c del x",
    "wsl rm -rf /",
    "docker run -v /:/x alpine",
    "podman run x",
    "kubectl delete x",
    "schtasks /create",
    "crontab -e",
    "reg delete HKLM",
    "$CMD",
    "$CMD arg",
    "${CMD} arg",
    "$(echo rm) -rf x",
    "env -S 'rm -rf /'",
    "env -S'rm -rf /'",
    "exec -a x rm -rf /",
    "command -z rm",
    "timeout --weird 5 ls",
    "bash",
    "sh",
    "echo 'rm -rf /' | bash",
    "echo x | sh",
    "bash -c",
    "printenv",
    "printenv HOME",
    "env",
    "env -i",
    "echo $ANTHROPIC_API_KEY",
    "echo ${AZURE_DEVOPS_PAT}",
    "echo $GITHUB_TOKEN",
    "echo $MY_SECRET",
    "echo $DB_PASSWORD",
    "cat .env",
    "cat config/.env.local",
    "cat ../.env",
    "cat ~/.ssh/id_rsa",
    "cat id_rsa",
    "cat server.pem",
    "cat private.key",
    "cat ~/.aws/credentials",
    "head .npmrc",
    "git show HEAD:.env",
    "git diff -- .env",
    "grep password .env",
    "grep -r token .ssh",
    'echo "unterminated',
    "echo $(unterminated",
    "echo 'x",
    "rm -rf {src,../x}",
    "rm -rf ../{a,b}",
    "echo x > {a,../b}",
    "cp {a,../b} dest",
    "cp a {b,../c}",
    "touch {a,~/b}",
    "touch {a,b}{1,2}{3,4}{5,6}{7,8}{9,0}{1,2}",
]


@FLAVORS
@pytest.mark.parametrize("command", DESTRUCTIVE_DENIED)
def test_destructive_escape_and_secret_denied(ws: str, command: str) -> None:
    pol = policy("developer", ws)
    assert not bash_ok(pol, command), command


WINDOWS_ONLY_DENIED = [
    "rm -rf C:/Windows",
    "rm -rf C:\\\\Windows",
    "rm -rf /c/Users",
    "del /s /q C:/x",
    "rd /s /q C:/x",
    "echo x > C:/Windows/x",
    "echo x > D:/x",
    "cp src/a.py C:/Users/x",
    "cd C:/",
    "cd /c/",
    "touch //server/share/x",
    "echo x > //server/share/x",
    "rm -rf C:foo",
    "echo x > a.txt:stream",
]


@pytest.mark.parametrize("command", WINDOWS_ONLY_DENIED)
def test_windows_paths_denied(command: str) -> None:
    assert not bash_ok(policy("developer", WINDOWS_WS), command)


def test_windows_absolute_inside_worktree_is_allowed() -> None:
    pol = policy("developer", WINDOWS_WS)
    assert bash_ok(pol, "echo x > C:/work/crew/T-1/out.txt")
    assert bash_ok(pol, "rm -rf /c/work/crew/T-1/build")
    assert bash_ok(pol, "cd C:/work/crew/T-1/src && pytest")
    assert not bash_ok(pol, "rm -rf C:/work/crew/T-1")
    assert not bash_ok(pol, "rm -rf C:/work/crew/T-10/x")


def test_posix_absolute_inside_worktree_is_allowed() -> None:
    pol = policy("developer", POSIX_WS)
    assert bash_ok(pol, "echo x > /work/crew/T-1/out.txt")
    assert bash_ok(pol, "rm -rf /work/crew/T-1/build")
    assert not bash_ok(pol, "rm -rf /work/crew/T-1")
    assert not bash_ok(pol, "rm -rf /work/crew/T-10/x")
    assert not bash_ok(pol, "echo x > /work/crew/T-1/../T-2/x")


def test_cd_state_is_tracked_across_commands() -> None:
    pol = policy("developer", POSIX_WS)
    assert bash_ok(pol, "cd src && cd .. && touch a")
    assert not bash_ok(pol, "cd src && cd ../.. && touch a")
    assert not bash_ok(pol, "cd src; touch ../../x")
    assert bash_ok(pol, "cd src; touch ../x")
    # a cd inside a subshell does not leak out
    assert not bash_ok(pol, "(cd src); touch ../../x")


def test_denial_reasons_are_in_portuguese_and_actionable() -> None:
    pol = policy("developer", POSIX_WS)
    assert "git" in reason(pol, "git commit -m x")
    assert "sem commit" in reason(pol, "git push")
    assert "rede" in reason(pol, "curl x")
    assert "worktree" in reason(pol, "echo x > ../x")
    assert "sensível" in reason(pol, "cat .env")
    assert "Bash" in reason(pol, "powershell -c ls") or "PowerShell" in reason(pol, "powershell -c ls")


def test_nesting_limit_fails_closed() -> None:
    cmd = "ls"
    for _ in range(8):
        cmd = f"bash -c '{cmd}'".replace("'", '"', 0) if False else "bash -c " + _quote(cmd)
    assert not bash_ok(policy("developer", POSIX_WS), cmd)


def _quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------------- tester
TESTER_ALLOWED = [
    "pytest -q",
    "python -m pytest -q --cache-clear",
    "uv run pytest",
    "npm test",
    "echo x > tests/test_a.py",
    "echo x >> tests/unit/test_b.py",
    "touch tests/conftest.py",
    "mkdir -p tests/unit",
    "cp src/a.py tests/data/a.py",
    "cp -t tests/data src/a.py",
    "mv tests/a.py tests/b.py",
    "echo x > pkg/test_thing.py",
    "pytest 2>&1 | tail",
    "pytest > /dev/null",
    "git status",
    "git diff",
    "rm tests/old_test.py",
    "ls src",
    "cat src/a.py",
]

TESTER_DENIED = [
    "echo x > src/a.py",
    "echo x >> shop/report.py",
    "echo x > conftest.py",
    "touch src/new.py",
    "mkdir src/new",
    "rm src/a.py",
    "rm -rf src",
    "rm -rf build",
    "sed -i s/a/b/ src/a.py",
    "tee src/a.py",
    "mv tests/a.py src/a.py",
    "mv src/a.py tests/a.py",
    "cp tests/a.py src/a.py",
    "cp -t src tests/a.py",
    "chmod +x src/run.sh",
    "echo x > ../tests/test_a.py",
    "git commit -m x",
    "pip install pytest-cov",
    "curl x",
]


@FLAVORS
@pytest.mark.parametrize("command", TESTER_ALLOWED)
def test_tester_allowed(ws: str, command: str) -> None:
    pol = policy("tester", ws)
    assert bash_ok(pol, command), reason_or_none(pol, command)


@FLAVORS
@pytest.mark.parametrize("command", TESTER_DENIED)
def test_tester_denied(ws: str, command: str) -> None:
    assert not bash_ok(policy("tester", ws), command)


def test_tester_globs_come_from_the_repo_config() -> None:
    pol = policy("tester", POSIX_WS, globs=["spec/**"])
    assert bash_ok(pol, "echo x > spec/a_spec.rb")
    assert not bash_ok(pol, "echo x > tests/test_a.py")


def test_tester_falls_back_to_default_globs_when_repo_has_none() -> None:
    job = make_job("tester", repo=make_repo(test_globs=[]))
    pol = policy_for(SPECS["tester"], job, POSIX_WS)
    assert bash_ok(pol, "echo x > tests/test_a.py")
    assert bash_ok(pol, "echo x > web/a.spec.ts")
    assert not bash_ok(pol, "echo x > src/a.py")


# ---------------------------------------------------------------------------------- read-only agents
READONLY_ALLOWED = [
    "git log --oneline -5",
    "git log -p -n 1",
    "git diff",
    "git diff main...HEAD",
    "git diff --stat HEAD~1",
    "git status",
    "git status --short",
    "git show HEAD",
    "git show HEAD~1:src/a.py",
    "git blame src/a.py",
    "git ls-files",
    "git rev-parse --abbrev-ref HEAD",
    "git branch --show-current",
    "git --no-pager diff",
    "git diff | head -50",
    "git log | grep fix",
    "ls",
    "ls -la src",
    "dir src",
    "cat src/a.py",
    "head -n 20 src/a.py",
    "tail -n 5 src/a.py",
    "wc -l src/a.py",
    "grep -rn foo src",
    "grep -rn api.key src",
    "rg foo",
    "rg -n 'def ' src",
    "find . -name '*.py'",
    "find src -type f -name '*.py' | wc -l",
    "tree src",
    "pwd",
    "echo hi",
    "cd src && ls",
    "cat src/a.py | head -5",
    "cat src/a.py 2>&1",
    "ls > /dev/null",
    "bash -c 'ls'",
    "stat src/a.py",
    "diff src/a.py src/b.py",
    "ls ./src/../tests",
]

READONLY_DENIED = [
    "rm x",
    "rm -rf build",
    "touch x",
    "mkdir x",
    "mv a b",
    "cp a b",
    "echo x > y",
    "echo x >> y",
    "cat a > b",
    "tee x",
    "sed -i s/a/b/ x",
    "sed -n 1p x",
    "awk '{print}' x",
    "python -c 'print(1)'",
    "python script.py",
    "pytest",
    "npm test",
    "npm install",
    "pip list",
    "uv run pytest",
    "make",
    "git commit -m x",
    "git add .",
    "git checkout x",
    "git branch new",
    "git stash",
    "git push",
    "git diff --output=x",
    "git -c x=y diff",
    "git show HEAD:.env",
    "curl x",
    "wget x",
    "cat /etc/passwd",
    "cat ../x",
    "cat ../../etc/passwd",
    "cat ~/.bashrc",
    "ls ..",
    "ls /",
    "ls ~",
    "ls C:/",
    "find / -name x",
    "find .. -name x",
    "find . -delete",
    "find . -exec cat {} ;",
    "grep x ../..",
    "grep -r x /etc",
    "rg x ..",
    "rg --pre cat x",
    "cat $(echo x)",
    "cat $FILE",
    "ls $HOME",
    "cat {a,../b}",
    "ls {src,..}",
    "cat < ../x",
    "cat .env",
    "head -5 .ssh/id_rsa",
    "ls; rm x",
    "ls && git push",
    "ls | sh",
    "ls | bash",
    "sort -o out.txt in.txt",
    "sort --output=out.txt in.txt",
    "bash script.sh",
    "bash -c 'rm x'",
    "bash -c 'git commit -m x'",
    "sh",
    "cd ..",
    "cd /",
    "cd",
    "env",
    "printenv",
    "xargs ls",
    "eval ls",
    "powershell ls",
    "echo $ANTHROPIC_API_KEY",
]


@FLAVORS
@pytest.mark.parametrize("agent", ["planner", "reviewer"])
@pytest.mark.parametrize("command", READONLY_ALLOWED)
def test_readonly_agents_allowed(ws: str, agent: str, command: str) -> None:
    pol = policy(agent, ws)
    assert bash_ok(pol, command), reason_or_none(pol, command)


@FLAVORS
@pytest.mark.parametrize("agent", ["planner", "reviewer"])
@pytest.mark.parametrize("command", READONLY_DENIED)
def test_readonly_agents_denied(ws: str, agent: str, command: str) -> None:
    assert not bash_ok(policy(agent, ws), command), command


def test_readonly_reason_lists_what_is_allowed() -> None:
    assert "somente leitura" in reason(policy("reviewer", POSIX_WS), "pytest")
    assert "somente leitura" in reason(policy("planner", POSIX_WS), "echo x > y")


# ---------------------------------------------------------------------------------- interviewer
@pytest.mark.parametrize("command", ["ls", "git status", "cat README.md", "echo hi"])
def test_interviewer_has_no_bash(command: str) -> None:
    pol = policy("interviewer", POSIX_WS)
    assert not bash_ok(pol, command)
    assert "disponível" in reason(pol, command)
