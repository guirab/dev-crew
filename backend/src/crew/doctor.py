"""``crew doctor``: checks the environment and says exactly what is missing and how to fix it."""

from __future__ import annotations

import asyncio
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

from .azure.mcp_client import AzureError, McpToolCaller, build_server_params
from .azure.service import McpAzureBackend
from .bus import Bus
from .bus import subjects as s
from .config import ConfigError, CrewConfig, Secrets, crew_home, find_config_path, load_config
from .workspace import git

Status = Literal["ok", "warn", "fail"]
TEST_CMD_TIMEOUT_S = 120.0
GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


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
    found = shutil.which("bash") or next((p for p in GIT_BASH_CANDIDATES if Path(p).is_file()), None)
    if found is None:
        return warn(
            "git-bash",
            "bash.exe não encontrado",
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


async def check_node() -> Check:
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    exe = shutil.which(npx)
    if exe is None:
        return warn(
            "node/npx",
            f"{npx} não encontrado",
            "só é necessário pro Azure DevOps MCP: winget install OpenJS.NodeJS.LTS",
        )
    try:
        proc = await asyncio.to_thread(
            subprocess.run, [exe, "--version"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return warn("node/npx", f"{npx} falhou: {e}", "reinstale o Node.js LTS")
    return ok("node/npx", f"{npx} {proc.stdout.decode(errors='replace').strip()}")


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


def check_anthropic_key(secrets: Secrets) -> Check:
    if secrets.anthropic_api_key is not None or os.environ.get("ANTHROPIC_API_KEY"):
        return ok("ANTHROPIC_API_KEY", "definida")
    return warn(
        "ANTHROPIC_API_KEY",
        "ausente",
        "necessária pros agentes reais (preencha o .env); com --fake-agents não é preciso",
    )


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


async def check_azure(cfg: CrewConfig, secrets: Secrets, *, backend: McpAzureBackend | None = None) -> Check:
    if cfg.azure is None:
        return ok("azure", "não configurado (só tarefas manuais)")
    pat = secrets.azure_devops_pat_b64.get_secret_value() if secrets.azure_devops_pat_b64 else None
    own_caller: McpToolCaller | None = None
    try:
        if backend is None:
            own_caller = McpToolCaller(build_server_params(cfg.azure, pat))
            backend = McpAzureBackend(own_caller, cfg.azure)
        items = await asyncio.wait_for(backend.list_work_items(), 150)
    except AzureError as e:
        return fail(
            "azure",
            str(e),
            "confira AZURE_DEVOPS_PAT_B64 (base64 de email:pat) e organization/project/team",
        )
    except TimeoutError:
        return fail(
            "azure", "MCP não respondeu em 150s", "teste manualmente: npx -y @azure-devops/mcp@<versão> <org>"
        )
    except Exception as e:
        return fail("azure", f"{type(e).__name__}: {e}", "veja o log do crew doctor com --verbose")
    finally:
        if own_caller is not None:
            await own_caller.close()
    if not items:
        return ok(
            "azure",
            f"{cfg.azure.organization}/{cfg.azure.project}: conectou, sprint atual sem itens seus",
        )
    return ok(
        "azure",
        f"{cfg.azure.organization}/{cfg.azure.project}: {len(items)} item(ns), "
        f"ex.: #{items[0].id} {items[0].title[:50]}",
    )


# ============================================================================ orchestration


async def run_checks(
    config_path: Path | None = None,
    *,
    run_tests: bool = True,
    check_azure_too: bool = True,
    secrets: Secrets | None = None,
) -> list[Check]:
    secrets = secrets or Secrets()
    results: list[Check] = []
    cfg_check, cfg = check_config(config_path)
    results.append(cfg_check)
    results.append(await check_git())
    results.append(check_git_bash())
    results.append(await check_claude_cli())
    results.append(await check_node())
    results.append(check_data_dir())
    results.append(check_anthropic_key(secrets))
    if cfg is None:
        return results
    results.append(await check_nats(cfg))
    results.append(check_workspace_root(cfg))
    results.append(check_gateway_port(cfg))
    for repo in cfg.repos:
        results.extend(await check_repo(cfg, repo.name, run_tests=run_tests))
    if check_azure_too:
        results.append(await check_azure(cfg, secrets))
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
