"""The scripted (fake) agents: scenario, real file edits, timing."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from crew.agents.fake import FAKE_COSTS, QUESTIONS, ScriptedRunner, commit_subject
from crew.agents.progress import ProgressLine
from crew.agents.settings import AgentRuntimeSettings
from crew.agents.specs import COMMIT_SUBJECT_MAX, SPECS
from crew.bus import FatalJobError
from crew.contracts import (
    AgentJob,
    DevResult,
    Feedback,
    InterviewResult,
    InterviewTurn,
    Plan,
    PlanFile,
    ReviewResult,
    TestResult,
)

from .factories import make_job, make_plan, make_repo, make_spec, make_turn

REPO = Path(__file__).resolve().parents[3]
SAMPLE = REPO / "fixtures" / "sample-repo"


class Recorder:
    def __init__(self) -> None:
        self.lines: list[ProgressLine] = []
        self.sleeps: list[float] = []

    async def emit(self, line: ProgressLine) -> None:
        self.lines.append(line)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    @property
    def texts(self) -> list[str]:
        return [line.text for line in self.lines]


def runner(rec: Recorder, *, speed: float = 1000.0, escalate: bool = False) -> ScriptedRunner:
    settings = AgentRuntimeSettings(model="fake", fake=True, fake_speed=speed, fake_escalate=escalate)
    return ScriptedRunner(settings, sleep=rec.sleep)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    dest = tmp_path / "wt"
    shutil.copytree(SAMPLE, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dest


def plan_for_sample() -> Plan:
    return make_plan()  # shop/report.py (M) + tests/test_report.py (M)


# ---------------------------------------------------------------------------------- interviewer
def turns(n: int) -> list[InterviewTurn]:
    return [
        InterviewTurn(question=QUESTIONS[i], answer=f"resposta {i}", accepted_recommendation=i == 0)
        for i in range(n)
    ]


@pytest.mark.parametrize(("asked", "expected"), [(0, QUESTIONS[:2]), (2, QUESTIONS[2:])])
async def test_interviewer_asks_the_mockup_questions_in_rounds(
    asked: int, expected: tuple[object, ...]
) -> None:
    rec = Recorder()
    job = make_job("interviewer", history=turns(asked))
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, InterviewResult)
    assert out.kind == "question"
    assert out.spec is None
    assert out.questions == list(expected)
    assert all(q.recommendation for q in out.questions)


async def test_interviewer_is_done_after_three_answers_with_a_consolidated_spec() -> None:
    rec = Recorder()
    job = make_job("interviewer", history=turns(3), spec=make_spec(decisions=[]))
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, InterviewResult)
    assert out.kind == "done"
    assert out.questions == []
    assert out.spec is not None
    assert out.spec.decisions == [
        "Fora de escopo: resposta 0",
        "Critérios de aceite: resposta 1",
        "Restrições: resposta 2",
    ]
    assert out.spec.out_of_scope == ["resposta 0"]
    assert out.spec.acceptance_criteria == ["resposta 1"]
    assert out.spec.constraints == ["resposta 2"]
    assert out.spec.title == job.spec.title


async def test_interviewer_with_arbitrary_history_topics_still_closes() -> None:
    rec = Recorder()
    history = [make_turn("Tópico A"), make_turn("Tópico B"), make_turn("Tópico C")]
    out = (await runner(rec).run(make_job("interviewer", history=history), rec.emit)).output
    assert isinstance(out, InterviewResult)
    assert out.kind == "done"
    assert len(out.spec.decisions) == 3  # type: ignore[union-attr]


# ---------------------------------------------------------------------------------- planner
async def test_planner_returns_a_four_step_plan() -> None:
    rec = Recorder()
    out = (await runner(rec).run(make_job("planner"), rec.emit)).output
    assert isinstance(out, Plan)
    assert len(out.steps) == 4
    assert {f.change for f in out.files} == {"A", "M"}
    assert out.acceptance_criteria[-1] == "Sem regressão na suíte existente"
    assert rec.texts[:3] == [
        "Lendo tarefa e critérios de aceite",
        "Explorando repo (Grep/Read nos módulos afetados)",
        "Montando passos, arquivos e critérios",
    ]


async def test_planner_acknowledges_the_adjustment() -> None:
    rec = Recorder()
    feedback = Feedback(kind="plan_adjust", text="incluir paginação")
    await runner(rec).run(make_job("planner", feedback=feedback), rec.emit)
    assert rec.texts[0] == 'Revendo plano: "incluir paginação"'


async def test_planner_uses_spec_criteria_when_present() -> None:
    rec = Recorder()
    job = make_job("planner", spec=make_spec(acceptance_criteria=["Intervalo inclusivo"]))
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, Plan)
    assert out.acceptance_criteria == ["Intervalo inclusivo", "Sem regressão na suíte existente"]


# ---------------------------------------------------------------------------------- developer
async def test_developer_edits_real_files_and_the_sample_suite_still_passes(worktree: Path) -> None:
    rec = Recorder()
    job = make_job("developer", workspace=worktree)
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, DevResult)
    assert out.round == 1
    assert [(f.path, f.change) for f in out.files_changed] == [
        ("shop/report.py", "M"),
        ("tests/test_report.py", "M"),
    ]
    assert "crew-fake (rodada 1): implementação do plano" in (worktree / "shop" / "report.py").read_text(
        "utf-8"
    )
    assert rec.texts == ["Editando shop/report.py", "Editando tests/test_report.py"]
    proc = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


async def test_developer_creates_modifies_and_deletes_per_plan(tmp_path: Path) -> None:
    (tmp_path / "old.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "mod.ts").write_text("export const a = 1;", encoding="utf-8")
    plan = make_plan().model_copy(
        update={
            "files": [
                PlanFile(path="web/components/Feature.tsx", change="A"),
                PlanFile(path="tests/test_new.py", change="A"),
                PlanFile(path="mod.ts", change="M"),
                PlanFile(path="old.py", change="D"),
                PlanFile(path="data.json", change="M"),
            ]
        }
    )
    job = make_job("developer", workspace=tmp_path).model_copy(update={"plan": plan})
    rec = Recorder()
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, DevResult)
    assert (tmp_path / "web" / "components" / "Feature.tsx").read_text("utf-8").startswith("// crew-fake")
    assert "def test_placeholder_written_by_fake_agent" in (tmp_path / "tests" / "test_new.py").read_text(
        "utf-8"
    )
    assert (tmp_path / "mod.ts").read_text("utf-8").startswith("export const a = 1;\n// crew-fake")
    assert not (tmp_path / "old.py").exists()
    assert not (tmp_path / "data.json").exists()  # JSON cannot hold comments: skipped, not reported
    assert [f.path for f in out.files_changed] == [
        "web/components/Feature.tsx",
        "tests/test_new.py",
        "mod.ts",
        "old.py",
    ]


async def test_developer_correction_round_touches_existing_files_only(worktree: Path) -> None:
    rec = Recorder()
    first = make_job("developer", workspace=worktree)
    await runner(rec).run(first, rec.emit)
    failing = TestResult(
        ok=False,
        passed=1,
        total=2,
        failures=[
            __import__("crew.contracts", fromlist=["TestFailure"]).TestFailure(
                test="t.py::test_x", message="m"
            )
        ],
        command="pytest",
    )
    rec2 = Recorder()
    second = make_job(
        "developer", workspace=worktree, attempt=2, feedback=Feedback(kind="test_failures", test=failing)
    )
    out = (await runner(rec2).run(second, rec2.emit)).output
    assert isinstance(out, DevResult)
    assert out.round == 2
    assert rec2.texts[0] == "Corrigindo: test_x"
    text = (worktree / "shop" / "report.py").read_text("utf-8")
    assert "crew-fake (rodada 1)" in text
    assert "crew-fake (rodada 2): correção do feedback" in text


async def test_developer_without_workspace_reports_the_plan_files_and_writes_nothing() -> None:
    rec = Recorder()
    out = (await runner(rec).run(make_job("developer"), rec.emit)).output
    assert isinstance(out, DevResult)
    assert len(out.files_changed) == 2


@pytest.mark.parametrize("evil", ["../escape.py", "/etc/passwd", "sub/../../escape.py"])
async def test_developer_refuses_plan_paths_outside_the_worktree(tmp_path: Path, evil: str) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    plan = make_plan().model_copy(update={"files": [PlanFile(path=evil, change="A")]})
    job = make_job("developer", workspace=wt).model_copy(update={"plan": plan})
    rec = Recorder()
    with pytest.raises(FatalJobError, match="fora do worktree"):
        await runner(rec).run(job, rec.emit)
    assert not (tmp_path / "escape.py").exists()


# ---------------------------------------------------------------------------------- tester
async def test_tester_first_attempt_fails_with_two_failures_and_writes_a_test(worktree: Path) -> None:
    rec = Recorder()
    job = make_job("tester", workspace=worktree)
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, TestResult)
    assert out.ok is False
    assert (out.passed, out.total) == (46, 48)
    assert len(out.failures) == 2
    assert all(len(f.message) <= 400 for f in out.failures)
    assert out.command == "python -m pytest -q"
    assert len(out.tests_written) == 1
    written = worktree / out.tests_written[0]
    assert written.is_file()
    compile(written.read_text("utf-8"), str(written), "exec")
    assert rec.texts == ["Escrevendo testes de integração", "$ python -m pytest -q"]


async def test_tester_second_attempt_passes() -> None:
    rec = Recorder()
    out = (await runner(rec).run(make_job("tester", attempt=2), rec.emit)).output
    assert isinstance(out, TestResult)
    assert out.ok is True
    assert (out.passed, out.total, out.coverage) == (48, 48, 0.87)
    assert out.failures == []
    assert out.tests_written == []
    assert rec.texts[0] == "Rodando a suíte de novo"


@pytest.mark.parametrize("attempt", [1, 2, 3, 7])
async def test_tester_always_fails_in_escalate_mode(attempt: int) -> None:
    rec = Recorder()
    out = (await runner(rec, escalate=True).run(make_job("tester", attempt=attempt), rec.emit)).output
    assert isinstance(out, TestResult)
    assert out.ok is False
    assert len(out.failures) == 2


async def test_tester_test_command_comes_from_the_repo() -> None:
    rec = Recorder()
    job = make_job("tester", attempt=2, repo=make_repo(test_cmd="npm test"))
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, TestResult)
    assert out.command == "npm test"
    assert "$ npm test" in rec.texts


# ---------------------------------------------------------------------------------- reviewer
async def test_reviewer_round_one_requests_changes_with_one_major_and_one_minor() -> None:
    rec = Recorder()
    out = (await runner(rec).run(make_job("reviewer"), rec.emit)).output
    assert isinstance(out, ReviewResult)
    assert out.verdict == "changes_requested"
    assert sorted(c.severity for c in out.comments) == ["major", "minor"]
    assert out.commit_message is None
    paths = {f.path for f in make_plan().files}
    assert {c.file for c in out.comments} <= paths
    assert rec.texts == [
        "$ git diff — lendo alterações",
        "Checando segurança, padrões do repo e aderência ao plano",
    ]


async def test_reviewer_round_two_approves_resolves_comments_and_writes_the_commit() -> None:
    rec = Recorder()
    first = (await runner(rec).run(make_job("reviewer"), rec.emit)).output
    assert isinstance(first, ReviewResult)
    job = make_job("reviewer", attempt=2, feedback=Feedback(kind="review_comments", review=first))
    out = (await runner(rec).run(job, rec.emit)).output
    assert isinstance(out, ReviewResult)
    assert out.verdict == "approved"
    assert len(out.comments) == 2
    assert all(c.resolved for c in out.comments)
    assert out.commit_message is not None
    subject, _, body = out.commit_message.partition("\n")
    assert subject == "feat: filtro por intervalo de datas no relatório de vendas"
    assert len(subject) <= COMMIT_SUBJECT_MAX
    assert "- bind params na query e datas em UTC (review)" in body
    assert "Refs:" not in out.commit_message


def test_commit_subject_is_capped_at_72_chars_on_a_word_boundary() -> None:
    subject = commit_subject(
        "feat", "Permitir filtrar o relatório de vendas por data inicial e final e também por vendedor"
    )
    assert len(subject) <= COMMIT_SUBJECT_MAX
    assert subject.startswith("feat: permitir filtrar")
    assert subject.endswith("…")


# ---------------------------------------------------------------------------------- generic
@pytest.mark.parametrize("agent", ["interviewer", "planner", "developer", "tester", "reviewer"])
async def test_every_fake_output_passes_the_real_semantic_check_and_reports_cost(agent: str) -> None:
    rec = Recorder()
    outcome = await runner(rec).run(make_job(agent), rec.emit)  # type: ignore[arg-type]
    spec = SPECS[agent]  # type: ignore[index]
    assert isinstance(outcome.output, spec.output)
    assert spec.check is None or spec.check(outcome.output) is None
    assert outcome.cost_usd == FAKE_COSTS[agent]
    assert outcome.session_id is not None
    assert outcome.session_id.startswith(f"fake-{agent}-")
    assert rec.lines
    assert all(line.kind == "tool" for line in rec.lines)


async def test_delays_are_proportional_to_the_speed() -> None:
    normal, fast = Recorder(), Recorder()
    job = make_job("planner")
    await runner(normal, speed=1.0).run(job, normal.emit)
    await runner(fast, speed=4.0).run(job, fast.emit)
    assert normal.sleeps == [1.0, 1.3, 1.0]
    assert fast.sleeps == [x / 4 for x in normal.sleeps]


async def test_zero_or_negative_speed_does_not_divide_by_zero() -> None:
    rec = Recorder()
    await runner(rec, speed=0).run(make_job("planner"), rec.emit)
    assert all(s > 1e3 for s in rec.sleeps)  # effectively "paused", never an exception


def test_fake_job_type_is_the_contract_job() -> None:
    assert isinstance(make_job("planner"), AgentJob)
