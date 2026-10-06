"""The submit_* tool: schema, validation, captor, semantic checks. No API involved."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from crew.agents.specs import SPECS
from crew.agents.submit import OK_TEXT, SubmitTool, full_tool_name, make_submit_tool
from crew.contracts import DevResult, InterviewResult, Plan, ReviewResult, TestResult

VALID_PLAN: dict[str, Any] = {
    "summary": "Adicionar filtro por datas.",
    "steps": ["a", "b"],
    "files": [{"path": "shop/report.py", "change": "M"}],
    "acceptance_criteria": ["intervalo inclusivo"],
    "test_strategy": "unit",
}


def text_of(result: dict[str, Any]) -> str:
    return str(result["content"][0]["text"])


def test_full_name_has_the_mcp_prefix() -> None:
    assert full_tool_name("submit_plan") == "mcp__crew__submit_plan"
    assert make_submit_tool(Plan, "submit_plan").full_name == "mcp__crew__submit_plan"


def test_schema_comes_from_the_pydantic_model() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    schema = tool.sdk_tool.input_schema
    assert isinstance(schema, dict)
    assert schema == Plan.model_json_schema()
    assert schema["type"] == "object"
    assert {"summary", "steps", "files", "acceptance_criteria", "test_strategy"} <= set(schema["required"])
    assert tool.sdk_tool.name == "submit_plan"


@pytest.mark.parametrize("agent", ["interviewer", "planner", "developer", "tester", "reviewer"])
def test_every_agent_schema_is_valid_json_schema(agent: str) -> None:
    spec = SPECS[agent]  # type: ignore[index]
    schema = make_submit_tool(spec.output, spec.submit_name).sdk_tool.input_schema
    assert isinstance(schema, dict)
    jsonschema.Draft202012Validator.check_schema(schema)


async def test_valid_payload_is_captured() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    assert tool.captured is None
    result = await tool.handle(VALID_PLAN)
    assert "is_error" not in result
    assert text_of(result) == OK_TEXT
    assert isinstance(tool.captured, Plan)
    assert tool.captured.summary == "Adicionar filtro por datas."
    assert tool.rejections == 0


async def test_invalid_payload_returns_readable_errors_and_captures_nothing() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    result = await tool.handle({**VALID_PLAN, "steps": "not a list", "files": [{"path": "x", "change": "Z"}]})
    assert result["is_error"] is True
    text = text_of(result)
    assert "submit_plan" in text
    assert "steps" in text
    assert "files.0.change" in text
    assert tool.captured is None
    assert tool.rejections == 1


async def test_missing_and_extra_fields_are_reported() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    result = await tool.handle({"summary": "x", "surprise": 1})
    text = text_of(result)
    assert result["is_error"] is True
    assert "steps" in text
    assert "surprise" in text


async def test_agent_can_fix_and_resubmit() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    await tool.handle({})
    assert tool.captured is None
    await tool.handle(VALID_PLAN)
    assert tool.captured is not None
    assert tool.rejections == 1


async def test_last_valid_submission_wins() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    await tool.handle(VALID_PLAN)
    await tool.handle({**VALID_PLAN, "summary": "segunda versão"})
    assert tool.captured is not None
    assert tool.captured.summary == "segunda versão"


async def test_semantic_check_rejects_with_the_message() -> None:
    spec = SPECS["reviewer"]
    tool = SubmitTool(ReviewResult, spec.submit_name, check=spec.check)
    result = await tool.handle({"verdict": "approved", "comments": []})
    assert result["is_error"] is True
    assert "commit_message" in text_of(result)
    assert tool.captured is None


async def test_test_failure_message_length_is_enforced_by_the_contract() -> None:
    tool = make_submit_tool(TestResult, "submit_test_result")
    result = await tool.handle(
        {
            "ok": False,
            "passed": 1,
            "total": 2,
            "command": "pytest",
            "failures": [{"test": "t", "message": "x" * 401}],
        }
    )
    assert result["is_error"] is True
    assert "failures.0.message" in text_of(result)


def test_server_exposes_the_tool_under_the_crew_name() -> None:
    tool = make_submit_tool(DevResult, "submit_dev_result")
    server = tool.server()
    assert server["type"] == "sdk"
    assert server["name"] == "crew"


async def test_the_sdk_server_validates_the_wire_schema_before_the_handler() -> None:
    """jsonschema (inside the SDK) rejects what the schema forbids, without reaching our handler."""
    tool = make_submit_tool(InterviewResult, "submit_interview")
    schema = tool.sdk_tool.input_schema
    assert isinstance(schema, dict)
    jsonschema.validate(
        {"kind": "question", "questions": [{"topic": "t", "question": "q", "recommendation": "r"}]}, schema
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"kind": "maybe"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"kind": "done", "extra": 1}, schema)
