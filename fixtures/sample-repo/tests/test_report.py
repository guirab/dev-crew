from datetime import date
from decimal import Decimal

from shop import Sale, sales_report


def make_sales() -> list[Sale]:
    return [
        Sale(date(2026, 9, 1), "ana", Decimal("100.00")),
        Sale(date(2026, 9, 2), "bia", Decimal("250.50")),
        Sale(date(2026, 9, 3), "ana", Decimal("50.25")),
        Sale(date(2026, 9, 10), "caio", Decimal("250.50")),
    ]


def test_empty_report() -> None:
    report = sales_report([])
    assert report.count == 0
    assert report.total == Decimal(0)
    assert report.by_seller == []


def test_totals() -> None:
    report = sales_report(make_sales())
    assert report.count == 4
    assert report.total == Decimal("651.25")


def test_groups_by_seller_biggest_total_first_ties_by_name() -> None:
    report = sales_report(make_sales())
    assert [(s.seller, s.count, s.total) for s in report.by_seller] == [
        ("bia", 1, Decimal("250.50")),
        ("caio", 1, Decimal("250.50")),
        ("ana", 2, Decimal("150.25")),
    ]
