"""``crew doctor``: checks the environment and says exactly what is missing and how to fix it."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nats.errors import Error as NatsError

from .bus import Bus
from .bus import subjects as s
from .config import ConfigError, CrewConfig, Secrets, crew_home, find_config_path, load_config
from .gateway.app import DEFAULT_DIST
from .gitbash import find_git_bash
from .workspace import git

Status = Literal["ok", "warn", "fail"]
TEST_CMD_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str
    hint: str = ""


def ok(name: str, detail: str) -> Check:
    return Check(name, "ok", detail)


def warn(name: str, detail: str, hint: str) -> Check:
    return Check(name, "warn", detail, hint)


def fail(name: str, detail: str, hint: str) -> Check:
    return Check(name, "fail", detail, hint)


# ============================================================================ individual checks


def check_config(path: Path | None) -> tuple[Check, CrewConfig | None]:
    try:
        cfg = load_config(path)
    except ConfigError as e:
        return fail("config", str(e).splitlines()[0], "copie crew.toml.example para crew.toml e ajuste"), None
    where = path or find_config_path()
    if not cfg.repos:
        return fail(
            "config", f"{where}: nenhum [[repos]]", "declare ao menos um repositório em crew.toml"
        ), cfg
    return ok("config", f"{where} ({len(cfg.repos)} repo(s))"), cfg


async def check_git() -> Check:
    try:
        res = await git.run(Path.cwd(), "--version")
    except git.GitError as e:
        return fail("git", e.stderr, "instale o Git for Windows: winget install Git.Git")
    return ok("git", res.stdout.strip())


def check_git_bash() -> Check:
    if sys.platform != "win32":
        return ok("git-bash", "não necessário fora do Windows")
    found = find_git_bash()
    if found is None:
        return warn(
            "git-bash",
            "Git Bash não encontrado (o bash.exe do System32 é o WSL e não serve)",
            "a tool Bash do Agent SDK precisa do Git Bash (vem com o Git for Windows)",
        )
    return ok("git-bash", found)


def find_claude_cli() -> str | None:
    """Same lookup order the Agent SDK uses when the wheel has no bundled CLI (Windows)."""
    override = os.environ.get("CREW_CLAUDE_CLI")
    if override:
        return override if Path(override).is_file() else None
    exe = "claude.exe" if sys.platform == "win32" else "claude"
    local = Path.home() / ".local" / "bin" / exe
    if local.is_file():
        return str(local)
    found = shutil.which(exe)
    # the SDK refuses the npm shim (claude.cmd), so only a real executable counts
    return found if found and not found.lower().endswith(".cmd") else None


async def check_claude_cli() -> Check:
    exe = find_claude_cli()
    if exe is None:
        return fail(
            "claude-cli",
            "claude.exe (Claude Code nativo) não encontrado",
            "o wheel do claude-agent-sdk no Windows não traz a CLI: instale o Claude Code nativo "
            "ou aponte CREW_CLAUDE_CLI=<caminho do claude.exe>",
        )
    try:
        proc = await asyncio.to_thread(
            subprocess.run, [exe, "--version"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return fail("claude-cli", f"{exe} falhou: {e}", "reinstale o Claude Code nativo")
    return ok("claude-cli", f"{exe} {proc.stdout.decode(errors='replace').strip()}")


async def check_nats(cfg: CrewConfig) -> Check:
    url = cfg.nats.url
    hint = "suba o NATS: docker compose -f infra/docker-compose.yml up -d  (ou: nats-server -js)"
    try:
        bus = await asyncio.wait_for(Bus.connect(url, name="crew-doctor"), 5)
    except (TimeoutError, OSError, NatsError) as e:
        return fail("nats", f"{url} inacessível ({type(e).__name__})", hint)
    try:
        try:
            await bus.js.account_info()
        except Exception:
            return fail(
                "nats", f"{url} responde, mas JetStream está desligado", "inicie o servidor com a flag -js"
            )
        missing = []
        for stream in (s.STREAM_JOBS, s.STREAM_EVENTS):
            try:
                await bus.js.stream_info(stream)
            except Exception:
                missing.append(stream)
        if missing:
            return warn(
                "nats",
                f"{url} ok, streams ausentes: {', '.join(missing)}",
                "rode: crew streams init (o crew up também cria)",
            )
        return ok("nats", f"{url} (JetStream, streams CREW_JOBS/CREW_EVENTS)")
    finally:
        await bus.close()


async def check_claude_auth(secrets: Secrets) -> Check:
    """Real agents run on the Claude subscription login; an API key would silently bill the API instead."""
    if secrets.anthropic_api_key is not None or os.environ.get("ANTHROPIC_API_KEY"):
        return warn(
            "claude-auth",
            "ANTHROPIC_API_KEY definida: agentes vão cobrar na API, não na assinatura",
            "remova a chave do .env e do ambiente pra usar o login da assinatura",
        )
    exe = find_claude_cli()
    if exe is None:
        return warn("claude-auth", "claude.exe ausente, login não verificado", "veja o check claude-cli")
    hint = "rode: claude auth login"
    try:
        proc = await asyncio.to_thread(
            subprocess.run, [exe, "auth", "status"], capture_output=True, timeout=30, check=False
        )
        info = json.loads(proc.stdout.decode(errors="replace"))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return warn("claude-auth", "não consegui ler `claude auth status`", hint)
    if not info.get("loggedIn"):
        return fail("claude-auth", "claude.exe não está logado", hint)
    plan = info.get("subscriptionType") or "sem assinatura"
    return ok("claude-auth", f"logado via {info.get('authMethod', '?')} (plano {plan})")


async def check_repo(cfg: CrewConfig, name: str, *, run_tests: bool) -> list[Check]:
    repo = cfg.repo(name)
    tag = f"repo:{name}"
    if not repo.path.is_dir():
        return [fail(tag, f"{repo.path} não existe", "corrija o path em [[repos]]")]
    if not await git.ok(repo.path, "rev-parse", "--git-dir"):
        return [fail(tag, f"{repo.path} não é um repositório git", "rode git init ou corrija o path")]
    if not await git.ok(repo.path, "rev-parse", "--verify", "--quiet", f"{repo.base_branch}^{{commit}}"):
        return [fail(tag, f"branch base {repo.base_branch!r} não existe", "corrija base_branch em [[repos]]")]
    checks = [ok(tag, f"{repo.path} (base {repo.base_branch})")]
    if run_tests:
        checks.append(await check_test_cmd(name, repo.test_cmd, repo.path))
    return checks


async def check_test_cmd(name: str, cmd: str, cwd: Path) -> Check:
    tag = f"test_cmd:{name}"

    def _run() -> subprocess.CompletedProcess[bytes]:
        # the command comes from the user's own crew.toml; it needs a shell for npm/.cmd shims on Windows
        return subprocess.run(
            cmd, cwd=cwd, shell=True, capture_output=True, timeout=TEST_CMD_TIMEOUT_S, check=False
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return warn(
            tag,
            f"`{cmd}` passou de {TEST_CMD_TIMEOUT_S:g}s",
            "o Tester vai estourar o timeout; use um test_cmd mais rápido",
        )
    except OSError as e:
        return fail(tag, f"`{cmd}` não executou: {e}", "corrija test_cmd em [[repos]]")
    if proc.returncode == 0:
        return ok(tag, f"`{cmd}` passou")
    tail = (proc.stdout + proc.stderr).decode(errors="replace").strip().splitlines()[-1:] or [""]
    return warn(
        tag,
        f"`{cmd}` saiu com código {proc.returncode}: {tail[0][:120]}",
        "a suíte já falha antes de qualquer mudança; os agentes vão herdar essas falhas",
    )


async def check_docker(cfg: CrewConfig) -> Check | None:
    """Only when some repo uses the sandbox (D41): the Docker engine must be up."""
    images = sorted({r.sandbox_image for r in cfg.repos if r.sandbox_image})
    if not images:
        return None
    hint = "abra o Docker Desktop (o sandbox dos agentes roda em container)"
    exe = shutil.which("docker")
    if exe is None:
        return fail(
            "docker", "docker não encontrado", "instale o Docker Desktop: winget install Docker.DockerDesktop"
        )
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            [exe, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return fail("docker", f"docker falhou: {e}", hint)
    if proc.returncode != 0:
        return fail("docker", "engine parado", hint)
    version = proc.stdout.decode(errors="replace").strip()
    return ok("docker", f"engine {version} · sandbox: {', '.join(images)}")


def check_sandbox(cfg: CrewConfig) -> list[Check]:
    """Warn per repo without ``sandbox_image``: its agents run Bash on the host, guarded only by hooks."""
    return [
        warn(
            f"sandbox:{r.name}",
            "sem sandbox_image: os agentes rodam comandos direto na sua máquina",
            "as guardas são um filtro de política, não um sandbox; defina sandbox_image (ex.: node:22) "
            "em [[repos]] se o repo não for descartável",
        )
        for r in cfg.repos
        if not r.sandbox_image
    ]


def check_frontend_dist(dist: Path | None) -> Check:
    """The gateway serves the UI from ``frontend/dist``; without the build, ``/`` is a 404."""
    if dist is None or (dist / "index.html").is_file():
        return ok("frontend", f"{dist} (build pronto)" if dist else "UI desativada")
    return fail(
        "frontend",
        f"{dist} sem build: a UI não vai abrir",
        "rode: cd frontend && npm install && npm run build",
    )


def check_workspace_root(cfg: CrewConfig) -> Check:
    root = cfg.workspace.root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".crew-doctor"
        probe.write_text("x", "utf-8")
        probe.unlink()
    except OSError as e:
        return fail("workspace", f"{root} sem escrita: {e}", "ajuste [workspace].root")
    return ok("workspace", f"{root} ({cfg.workspace.mode})")


def check_data_dir() -> Check:
    home = crew_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".crew-doctor"
        probe.write_text("x", "utf-8")
        probe.unlink()
    except OSError as e:
        return fail("data-dir", f"{home} sem escrita: {e}", "defina CREW_HOME para um diretório gravável")
    return ok("data-dir", str(home))


def check_gateway_port(cfg: CrewConfig) -> Check:
    host, port = cfg.gateway.host, cfg.gateway.port
    with socket.socket() as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return warn(
                "gateway",
                f"{host}:{port} já em uso",
                "se o crew up já roda, ignore; senão mude [gateway].port",
            )
    return ok("gateway", f"{host}:{port} livre")


# ============================================================================ orchestration


async def run_checks(
    config_path: Path | None = None,
    *,
    run_tests: bool = True,
    secrets: Secrets | None = None,
    dist: Path | None = DEFAULT_DIST,
) -> list[Check]:
    secrets = secrets or Secrets()
    results: list[Check] = []
    cfg_check, cfg = check_config(config_path)
    results.append(cfg_check)
    results.append(await check_git())
    results.append(check_git_bash())
    results.append(await check_claude_cli())
    results.append(check_data_dir())
    results.append(check_frontend_dist(dist))
    results.append(await check_claude_auth(secrets))
    if cfg is None:
        return results
    results.append(await check_nats(cfg))
    results.append(check_workspace_root(cfg))
    if (docker := await check_docker(cfg)) is not None:
        results.append(docker)
    results.append(check_gateway_port(cfg))
    results.extend(check_sandbox(cfg))
    for repo in cfg.repos:
        results.extend(await check_repo(cfg, repo.name, run_tests=run_tests))
    return results


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0


def render(checks: list[Check], style: Callable[[str, str], str]) -> list[str]:
    """Human output, one block per check. ``style(text, status)`` colours the marker."""
    marks: dict[Status, str] = {"ok": "OK  ", "warn": "WARN", "fail": "FAIL"}
    lines: list[str] = []
    for c in checks:
        lines.append(f"{style(marks[c.status], c.status)} {c.name}: {c.detail}")
        if c.hint and c.status != "ok":
            lines.append(f"       -> {c.hint}")
    fails = sum(c.status == "fail" for c in checks)
    warns = sum(c.status == "warn" for c in checks)
    lines.append("")
    lines.append(
        "tudo certo" if not fails and not warns else f"{fails} problema(s) bloqueante(s), {warns} aviso(s)"
    )
    return lines
