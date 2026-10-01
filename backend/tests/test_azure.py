from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import StdioServerParameters
from mcp_types import CallToolResult, TextContent

from crew.azure import mapping
from crew.azure.fake import FakeAzureBackend
from crew.azure.mcp_client import (
    AzureError,
    McpToolCaller,
    ReadOnlyViolation,
    _payload,
    build_server_params,
    ensure_read_only,
)
from crew.azure.service import McpAzureBackend
from crew.config import AzureCfg

DATA = Path(__file__).parent / "data"
CFG = AzureCfg(organization="minha-org", project="Portal Vendas", team="Portal Vendas Team")


def recorded(name: str) -> str:
    return (DATA / name).read_text("utf-8")


# ================================================================================ mapping


@pytest.mark.parametrize(
    "text",
    [
        '<<a1b2c3d4>> [UNTRUSTED AZURE DEVOPS CONTENT]\n{"a": 1}\n<</a1b2c3d4>>',
        '{"a": 1}',
        '  <<x>>{"a": 1}<</x>>  ',
        'Resultado:\n[UNTRUSTED AZURE DEVOPS WORK ITEM CONTENT - dados de terceiros]\n{"a": 1}',
    ],
)
def test_untrusted_markers_are_removed_before_json(text: str) -> None:
    assert mapping.parse_tool_text(text) == {"a": 1}


def test_markers_inside_string_values_are_stripped_too() -> None:
    text = '{"d": "<<id>> [UNTRUSTED X CONTENT] olá <</id>>"}'
    assert mapping.parse_tool_text(text)["d"].strip() == "olá"


def test_not_json_raises_mapping_error() -> None:
    with pytest.raises(mapping.AzureMappingError, match="não é JSON"):
        mapping.parse_tool_text("<<a>> sorry, something broke <</a>>")


def test_wiql_ids_from_recorded_response() -> None:
    data = mapping.parse_tool_text(recorded("azure_wiql.txt"))
    assert mapping.ids_from_wiql(data) == [4830, 4827, 4821]


def test_summaries_from_recorded_batch() -> None:
    data = mapping.parse_tool_text(recorded("azure_batch.txt"))
    items = mapping.summaries(data)
    assert [(w.id, w.type, w.state) for w in items] == [(4821, "User Story", "Active"), (4830, "Bug", "New")]
    assert items[0].title == "Filtro por intervalo de datas no relatório de vendas"


def test_detail_from_recorded_bug_html_to_markdown_and_repro_steps() -> None:
    data = mapping.parse_tool_text(recorded("azure_item_bug.txt"))
    d = mapping.detail_from_tool_data(data, organization="minha-org", project="Portal Vendas")
    assert (d.id, d.type, d.state) == (4830, "Bug", "Active")
    assert d.iteration_path == "Portal Vendas\\Sprint 7"
    assert "**500**" in d.description and "<div>" not in d.description
    assert "alert(1)" not in d.description, "script blocks are dropped"
    assert "## Passos para reproduzir" in d.description and "1. Abrir o cadastro" in d.description
    assert d.acceptance_criteria == [
        "Retorna 422 com mensagem clara",
        "Teste cobrindo CPF vazio",
        "e CPF nulo",
    ]
    assert d.url == "https://dev.azure.com/minha-org/Portal%20Vendas/_workitems/edit/4830"
    # injection text is kept as plain data (agents fence it); it is NOT executed or interpreted here
    assert "Ignore previous instructions" in d.description


def test_detail_url_fallback_and_missing_fields() -> None:
    d = mapping.to_detail({"id": 7, "fields": {"System.Title": "x"}}, organization="o", project="p")
    assert d.url == "https://dev.azure.com/o/p/_workitems/edit/7"
    assert (d.type, d.state, d.description, d.acceptance_criteria, d.iteration_path) == (
        "Work Item",
        "?",
        "",
        [],
        None,
    )


def test_non_https_html_link_is_ignored() -> None:
    item = {"id": 7, "fields": {}, "_links": {"html": {"href": "javascript:alert(1)"}}}
    d = mapping.to_detail(item, organization="o", project="p")
    assert d.url.startswith("https://dev.azure.com/o/p/")


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (None, []),
        ("", []),
        ("<ul><li>a</li><li> b  c </li></ul>", ["a", "b c"]),
        ("<ol><li>um<ul><li>aninhado</li></ul></li><li>dois</li></ol>", ["um", "aninhado", "dois"]),
        (
            "<div>- primeiro</div><div>2) segundo</div><div>terceiro</div>",
            ["primeiro", "segundo", "terceiro"],
        ),
        ("<li>x<script>evil()</script></li>", ["x"]),
    ],
)
def test_split_criteria(html: str | None, expected: list[str]) -> None:
    assert mapping.split_criteria(html) == expected


def test_html_to_markdown_basics() -> None:
    md = mapping.html_to_markdown("<h2>T</h2><p>a <a href='https://x.y'>link</a></p><style>p{}</style>")
    assert md.startswith("## T") and "[link](https://x.y)" in md and "p{}" not in md
    assert mapping.html_to_markdown("   ") == ""


@pytest.mark.parametrize("bad", [42, "x", {"nope": 1}, {"value": "not-a-list"}])
def test_unrecognised_shapes_raise(bad: Any) -> None:
    with pytest.raises(mapping.AzureMappingError):
        mapping.summaries(bad)


def test_item_without_valid_id_raises() -> None:
    with pytest.raises(mapping.AzureMappingError, match="id válido"):
        mapping.to_summary({"fields": {"System.Title": "x"}})


def test_empty_get_result_is_not_found() -> None:
    with pytest.raises(mapping.AzureMappingError, match="não encontrado"):
        mapping.detail_from_tool_data({"value": []}, organization="o", project="p")


# ================================================================================ read-only guard


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("wit_work_item", {"action": "get", "id": 1}),
        ("wit_work_item", {"action": "get_batch", "ids": [1]}),
        ("wit_work_item", {"action": "list_for_iteration"}),
        ("wit_query", {"action": "wiql"}),
        ("work", {"action": "list_team_iterations"}),
    ],
)
def test_read_calls_pass_the_guard(tool: str, args: dict[str, Any]) -> None:
    ensure_read_only(tool, args)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("wit_work_item_write", {"action": "get"}),
        ("wit_update_write", {}),
        ("wit_work_item", {"action": "update"}),
        ("wit_work_item", {"action": "create"}),
        ("wit_work_item", {"action": "add_comment"}),
        ("wit_work_item", {}),
        ("wit_query", {"action": "get"}),
        ("repo_create_pull_request", {"action": "create"}),
        ("core", {"action": "list_projects"}),
    ],
)
def test_write_or_unknown_calls_are_blocked(tool: str, args: dict[str, Any]) -> None:
    with pytest.raises(ReadOnlyViolation):
        ensure_read_only(tool, args)


# ================================================================================ server params


def test_server_params_windows_uses_npx_cmd_and_never_puts_the_pat_in_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    p = build_server_params(CFG, "c2VjcmV0OnBhdA==")
    assert p.command == "npx.cmd"
    assert p.args == [
        "-y",
        "@azure-devops/mcp@2.10.0",
        "minha-org",
        "-d",
        "core",
        "work",
        "work-items",
        "-a",
        "pat",
    ]
    assert p.env is not None
    assert p.env["PERSONAL_ACCESS_TOKEN"] == "c2VjcmV0OnBhdA=="
    assert (p.env["ado_mcp_project"], p.env["ado_mcp_team"]) == ("Portal Vendas", "Portal Vendas Team")
    assert "c2VjcmV0OnBhdA==" not in " ".join(p.args)


def test_server_params_posix_and_azcli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    p = build_server_params(CFG.model_copy(update={"auth": "azcli"}), None)
    assert p.command == "npx" and p.args[-2:] == ["-a", "azcli"]
    assert p.env is not None and "PERSONAL_ACCESS_TOKEN" not in p.env


def test_pat_auth_requires_the_secret() -> None:
    with pytest.raises(AzureError, match="AZURE_DEVOPS_PAT_B64"):
        build_server_params(CFG, None)


def test_payload_unwraps_fenced_text_and_errors() -> None:
    ok = CallToolResult(content=[TextContent(text='<<z>> [UNTRUSTED A CONTENT]\n{"x": 1}\n<</z>>')])
    assert _payload(ok) == {"x": 1}
    err = CallToolResult(content=[TextContent(text="TF401019: not found")], is_error=True)
    with pytest.raises(AzureError, match="TF401019"):
        _payload(err)
    with pytest.raises(mapping.AzureMappingError):
        _payload(CallToolResult(content=[]))


# ================================================================================ backend with recorded JSON


class RecordingCaller:
    def __init__(self, responses: dict[tuple[str, str], str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        ensure_read_only(tool, arguments)
        self.calls.append((tool, arguments))
        return mapping.parse_tool_text(self.responses[(tool, arguments["action"])])

    async def close(self) -> None:
        return None


async def test_backend_list_runs_wiql_then_batch_with_explicit_fields_in_query_order() -> None:
    caller = RecordingCaller(
        {
            ("wit_query", "wiql"): recorded("azure_wiql.txt"),
            ("wit_work_item", "get_batch"): recorded("azure_batch.txt"),
        }
    )
    items = await McpAzureBackend(caller, CFG).list_work_items()
    assert [i.id for i in items] == [4830, 4821], (
        "4827 is absent from the batch: skipped, order follows the query"
    )
    wiql_call, batch_call = caller.calls
    assert wiql_call[1]["project"] == "Portal Vendas" and wiql_call[1]["team"] == "Portal Vendas Team"
    assert "@CurrentIteration" in wiql_call[1]["wiql"] and "@Me" in wiql_call[1]["wiql"]
    assert batch_call[1]["ids"] == [4830, 4827, 4821]
    assert "System.Title" in batch_call[1]["fields"]


async def test_backend_list_empty_sprint_skips_batch() -> None:
    caller = RecordingCaller({("wit_query", "wiql"): json.dumps({"workItems": []})})
    assert await McpAzureBackend(caller, CFG).list_work_items() == []
    assert [c[0] for c in caller.calls] == ["wit_query"]


async def test_backend_get_maps_detail() -> None:
    caller = RecordingCaller({("wit_work_item", "get"): recorded("azure_item_bug.txt")})
    d = await McpAzureBackend(caller, CFG).get_work_item(4830)
    assert d.id == 4830 and d.acceptance_criteria
    assert caller.calls[0][1] == {
        "action": "get",
        "id": 4830,
        "project": "Portal Vendas",
        "expand": "Relations",
    }


async def test_fake_backend_has_the_four_mockup_items() -> None:
    fake = FakeAzureBackend()
    assert [w.id for w in await fake.list_work_items()] == [4830, 4827, 4821, 4819]
    assert (await fake.get_work_item(4821)).acceptance_criteria
    with pytest.raises(AzureError, match="não encontrado"):
        await fake.get_work_item(1)


# ================================================================================ real stdio MCP session


@pytest.fixture
def fake_server_params(tmp_path: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=[str(DATA / "fake_azure_mcp_server.py")],
        env={"FAKE_AZURE_MARKER": str(tmp_path / "died")},
    )


async def test_mcp_session_end_to_end_with_fenced_replies(fake_server_params: StdioServerParameters) -> None:
    caller = McpToolCaller(fake_server_params, startup_timeout=60, call_timeout=30)
    try:
        backend = McpAzureBackend(caller, CFG)
        items = await backend.list_work_items()
        assert [(i.id, i.title) for i in items] == [
            (4830, "Erro 500 sem CPF"),
            (4821, "Filtro por intervalo de datas"),
        ]
        detail = await backend.get_work_item(4821)
        assert detail.acceptance_criteria == ["Inclusivo", "Erro 422"]
        assert "**start_date**" in detail.description
        with pytest.raises(ReadOnlyViolation):  # the server does expose a *_write tool; we cannot reach it
            await caller.call("wit_work_item_write", {"action": "get", "title": "x"})
    finally:
        await caller.close()


async def test_mcp_session_reconnects_after_the_server_dies(
    fake_server_params: StdioServerParameters,
) -> None:
    caller = McpToolCaller(fake_server_params, startup_timeout=60, call_timeout=15)
    try:
        args = {"action": "wiql", "project": "p", "team": "t", "wiql": "DIE"}
        data = await asyncio.wait_for(caller.call("wit_query", args), 90)  # 1st process dies, 2nd answers
        assert data["workItems"][0]["id"] == 4830
    finally:
        await caller.close()
