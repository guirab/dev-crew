# Spike S0: Claude Agent SDK (Python)

Data: 2026-10-01 · SDK instalado: `claude-agent-sdk 0.2.163` (CLI embutida esperada: 2.1.286; CLI nativa encontrada: 2.1.282) · `mcp 2.2.0` · Windows 11.

**Restrição:** sem `ANTHROPIC_API_KEY`. Tudo abaixo foi confirmado por introspecção, por teste local de tool/hook e por handshake com a CLI real **sem enviar prompt** (nenhuma chamada ao modelo). O que depende de chamada real está em "Fica pra validar com chave" (marcar `-m live`).

Reproduzir: `cd backend && uv run python scripts/spike_sdk.py` (offline), `--cli` (handshake com a CLI), `--live` (chave; teto de US$ 0,25).

## Resultado

| Verificar | Resultado | Evidência / decisão |
|---|---|---|
| `pip install claude-agent-sdk` no Win11 **sem Node** | **Parcial** | O wheel puro instalado pelo uv **não traz a CLI**: `_bundled/` só tem `.gitignore`. O PyPI não tem wheel `win_amd64` nas versões 0.2.157 e 0.2.160-0.2.163 (existe até a 0.2.159); o `uv.lock` só lista macOS/Linux. O SDK usa o `claude.exe` **nativo** (`~/.local/bin/claude.exe` / PATH; mínimo 2.0.0) e **recusa** o shim `claude.cmd` do npm. Node não é necessário. Decisão: `CREW_CLAUDE_CLI` opcional no runner; `crew doctor` deve checar `claude.exe`; ver `docs/contract-requests.md` item 1. |
| Tool `Bash` no Windows (Git Bash) | **Pendente (live)** | Git Bash está em `C:\Program Files\Git\bin\bash.exe` e no PATH; `CLAUDE_CODE_GIT_BASH_PATH` não é necessária (a CLI autodetecta; a variável existe pra caminho fora do PATH). Falta rodar um comando via tool Bash. |
| `ClaudeSDKClient.interrupt()` | **Existe** | `interrupt(self) -> None`. O runner chama `interrupt()` (timeout 3 s) ao ser cancelado e depois `disconnect()`; o cancelamento em si é `asyncio.Task.cancel()` (plano D3). |
| `can_use_tool` em `ClaudeAgentOptions` | **Existe** | Mas `allowed_tools` pré-aprova e ignora o callback (há `CanUseToolShadowedWarning`). **Não usado**; a guarda é só `PreToolUse`. |
| `output_format` (JSON schema) | **Existe** | Irrelevante: seguimos com `submit_*` (D5). |
| Hook `PreToolUse` com `permissionDecision: "deny"` | **Formato confirmado, efeito pendente (live)** | `HookMatcher(matcher=None, hooks=[fn])` (None = todas as tools), `fn(input, tool_use_id, context)`; retorno `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` (TypedDict `PreToolUseHookSpecificOutput`). O hook foi chamado direto nos testes (nega `git commit`, `Write` fora do worktree). A CLI real **aceitou o registro** de hooks no handshake. Falta confirmar que a CLI respeita o `deny` numa chamada real (`test_developer_cannot_commit`, `-m live`). Se não respeitar: parar e reavaliar (plano). |
| Tool `submit_*` (`@tool` + `create_sdk_mcp_server`) | **Confirmado** | `tool(name, desc, input_schema)` aceita um **JSON Schema completo** (`Plan.model_json_schema()`), que passa direto pro fio. O SDK valida `arguments` com `jsonschema` antes do handler e devolve `isError`. Teste `test_submit_wire.py` conduz o servidor in-process por JSON-RPC (initialize, tools/list, tools/call) como a CLI faria. Com a CLI real: `get_mcp_status()` mostra o servidor `crew` **connected** com a tool `submit_plan` (a CLI conecta em background após o handshake; fazer polling). Nome final `mcp__crew__submit_plan`: pendente de confirmar em chamada real. |
| `resume=<session_id>` | **Opção existe; efeito pendente (live)** | `ClaudeAgentOptions.resume`. Falta: contexto realmente retomado; se o `session_id` muda no resume; mensagem de erro de sessão inexistente (o runner trata `error` sem mensagem de assistente + `"no conversation found"` e recai para prompt completo). |
| `max_budget_usd`, `max_turns`, `ResultMessage.total_cost_usd` | **Existem** | Resultados de erro: `error_max_budget_usd`, `error_max_turns`. `ResultMessage` tem `total_cost_usd`, `session_id`, `num_turns`, `usage`, `is_error`, `api_error_status`, `errors`. Pendente (live): `total_cost_usd` é **cumulativo** entre `client.query()` da mesma sessão ou por turno? O runner assume cumulativo (usa o último). |
| IDs de modelo | **Confirmado na doc oficial** | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`) em platform.claude.com/docs/en/models/overview. |
| Prompt caching | **Pendente (live)** | Olhar `usage` (`cache_read_input_tokens`) no 2º turno. |

## Outras descobertas que mudaram o design

1. **`tools=[...]` restringe as built-ins** (`allowed_tools` só pré-aprova). O runner passa os dois, mais `disallowed_tools` (WebFetch, WebSearch, Agent, Task, PowerShell, Skill) e uma guarda que **nega por padrão** qualquer tool fora da lista. No Windows a CLI tem uma tool `PowerShell` própria: sem essa trava ela contornaria as guardas de Bash.
2. **`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`** (CLI >= 2.1.226, doc oficial) tira `ANTHROPIC_API_KEY`, `AZURE_*` e variáveis com `token/secret/key/password` do ambiente dos subprocessos da tool Bash. O runner define essa variável e `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` no `env` da sessão. Pendente (live): conferir com `printenv` (que a guarda de Bash já nega).
3. **`permission_mode`:** `default` (Planner/Reviewer/Entrevistador) e `acceptEdits` (Developer/Tester), nunca `bypassPermissions`. `dontAsk` existe, não usado.
4. **`system_prompt`:** o runner usa o preset `claude_code` com `append` de `_shared.md` + `<agente>.md` (instruções de tool/ambiente do preset ficam). Pendente (live): comparar com prompt só em string quanto a custo e comportamento.
5. **`setting_sources=[]` + `strict_mcp_config=True`:** a CLI não herda `.claude/`, `CLAUDE.md` nem MCPs do repo alvo.
6. A guarda lê `tool_input["command"]` da tool Bash e nega o campo `dangerouslyDisableSandbox` se vier (nome do campo conforme o schema da tool; confirmar o formato exato do `tool_input` em chamada real).
7. `ClaudeAgentOptions.sandbox` e `ClaudeAgentOptions.env` existem; `sandbox` não foi avaliado (M5).

## Limites das guardas (honestidade)

`agents/guards.py` é um **filtro de política**, não um sandbox. Cobre git (allowlist de leitura), instalação de dependências, rede, comandos destrutivos, escrita fora do worktree (léxica + realpath, incluindo junctions do Windows), expansão de chaves `{a,b}`, `cd`, subshells, `$(...)`, crases, heredocs, `bash -c` aninhado, segredos (`.env`, chaves, variáveis `*_KEY/TOKEN/SECRET`). Não impede um programa que o agente escreve e roda (`python script.py`, `node -e`, `awk 'BEGIN{system(...)}'`) de fazer qualquer coisa. Mitigações previstas: sandbox/Docker no M5 e verificação do diff pós-Tester (ver `docs/contract-requests.md`).

## Fica pra validar com chave (`-m live`)

Rodar `uv run python scripts/spike_sdk.py --live` e `uv run pytest -m live` (custa centavos; teto por job via `budget_usd`):

- [x] CLI respeita `permissionDecision: "deny"` do hook: `git commit --allow-empty -m x` bloqueado na chamada real (2026-10-05, login da assinatura, Sonnet).
- [x] Tool Bash executa no Windows via Git Bash (`python -m pytest -q` rodou; `CLAUDE_CODE_GIT_BASH_PATH` fixado por sessão). `printenv` não verificado (guarda nega).
- [ ] Nome final da tool (`mcp__crew__submit_*`) e comportamento "agente esquece o submit" (follow-up).
- [x] `resume`: mesma `session_id` no resume e contexto mantido (2026-10-05). Erro de sessão inexistente não testado.
- [ ] `total_cost_usd` cumulativo ou por turno; `usage` e cache.
- [ ] `max_budget_usd` estourado devolve `error_max_budget_usd`.
- [ ] Preset `claude_code` + append vs string pura.
- [ ] `interrupt()` durante tool longa e `Task.cancel()` sem deixar processo órfão (Windows).
