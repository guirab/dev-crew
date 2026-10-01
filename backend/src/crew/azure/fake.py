"""Fake Azure backend (``--fake-azure`` / ``CREW_FAKE_AZURE=1``): the 4 work items of the mockup."""

from __future__ import annotations

from ..contracts import WorkItemDetail, WorkItemSummary
from .mcp_client import AzureError

_ITEMS: tuple[WorkItemDetail, ...] = (
    WorkItemDetail(
        id=4830,
        type="Bug",
        title="Erro 500 ao salvar cliente sem CPF",
        state="Active",
        description=(
            "Ao salvar um cliente sem CPF a API responde 500.\n\n"
            "## Passos para reproduzir\n\n1. Abrir o cadastro de cliente\n2. Deixar o CPF vazio\n3. Salvar"
        ),
        acceptance_criteria=["Cliente sem CPF é salvo ou rejeitado com 422 e mensagem clara"],
        iteration_path="Sprint 7",
        url="https://dev.azure.com/fake-org/fake-project/_workitems/edit/4830",
    ),
    WorkItemDetail(
        id=4827,
        type="User Story",
        title="Dashboard de metas por vendedor",
        state="New",
        description="Como gerente quero ver a meta e o realizado de cada vendedor no mês.",
        acceptance_criteria=["Mostra meta e realizado por vendedor", "Filtro por mês"],
        iteration_path="Sprint 7",
        url="https://dev.azure.com/fake-org/fake-project/_workitems/edit/4827",
    ),
    WorkItemDetail(
        id=4821,
        type="User Story",
        title="Filtro por intervalo de datas no relatório de vendas",
        state="Active",
        description="Como analista quero filtrar o relatório de vendas por intervalo de datas.",
        acceptance_criteria=[
            "Intervalo inclusivo nas duas pontas",
            "start_date > end_date retorna erro de validação",
            "Sem regressão na suíte existente",
        ],
        iteration_path="Sprint 7",
        url="https://dev.azure.com/fake-org/fake-project/_workitems/edit/4821",
    ),
    WorkItemDetail(
        id=4819,
        type="Task",
        title="Atualizar SDK de pagamentos pra v5",
        state="Active",
        description="Atualizar o SDK de pagamentos para a v5 mantendo a API pública.",
        acceptance_criteria=["Suíte de pagamentos verde após a atualização"],
        iteration_path="Sprint 7",
        url="https://dev.azure.com/fake-org/fake-project/_workitems/edit/4819",
    ),
)


class FakeAzureBackend:
    async def list_work_items(self) -> list[WorkItemSummary]:
        return [WorkItemSummary(id=w.id, type=w.type, title=w.title, state=w.state) for w in _ITEMS]

    async def get_work_item(self, work_item_id: int) -> WorkItemDetail:
        for w in _ITEMS:
            if w.id == work_item_id:
                return w
        raise AzureError(f"work item {work_item_id} não encontrado")

    async def close(self) -> None:
        return None
