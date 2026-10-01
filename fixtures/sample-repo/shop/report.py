"""Relatório de vendas sobre uma lista em memória."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Sale:
    sold_on: date
    seller: str
    amount: Decimal


@dataclass(frozen=True)
class SellerTotal:
    seller: str
    count: int
    total: Decimal


@dataclass(frozen=True)
class SalesReport:
    count: int
    total: Decimal
    by_seller: list[SellerTotal]


def sales_report(sales: Iterable[Sale]) -> SalesReport:
    """Soma as vendas e agrupa por vendedor (maior total primeiro, empate por nome)."""
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for sale in sales:
        counts[sale.seller] += 1
        totals[sale.seller] += sale.amount

    by_seller = sorted(
        (SellerTotal(seller, counts[seller], totals[seller]) for seller in totals),
        key=lambda item: (-item.total, item.seller),
    )
    return SalesReport(
        count=sum(counts.values()),
        total=sum(totals.values(), Decimal(0)),
        by_seller=by_seller,
    )
