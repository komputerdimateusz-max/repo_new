from io import BytesIO
from zipfile import ZipFile

import pytest

from app.services.pdf_exports import (
    group_orders_by_company,
    render_pdf_combined,
    render_pdf_zip_per_company,
    sanitize_filename,
)


def _sample_orders():
    return [
        {
            "id": 1,
            "time": "10:00",
            "company_name": "ACME",
            "company_address": "ul. Testowa 1",
            "company_zip": "00-001",
            "user_name": "Jan",
            "order_lines": [{"name": "Zupa", "qty": 1, "unit_price": 12}],
            "total_amount": "12.00",
            "payment_status": "PAID",
        },
        {
            "id": 2,
            "time": "11:00",
            "company_name": "Beta Sp. z o.o.",
            "company_address": "",
            "company_zip": "",
            "user_name": "Ala",
            "order_lines": [{"name": "Pierogi", "qty": 2, "unit_price": 18}],
            "total_amount": "36.00",
            "payment_status": "PENDING",
            "notes": None,
        },
    ]


def test_group_orders_by_company_counts() -> None:
    grouped = group_orders_by_company(_sample_orders())
    assert len(grouped) == 2
    assert sum(len(items) for items in grouped.values()) == 2


def test_render_combined_and_zip_no_crash_with_single_company_and_missing_optional_fields() -> None:
    pytest.importorskip("reportlab")
    one_company = [{"id": 3, "company_name": "Solo", "order_lines": [], "total_amount": "0"}]
    meta = {"today": "2026-01-01", "generated_at": "2026-01-01 10:00"}

    pdf_bytes = render_pdf_combined(one_company, meta)
    assert pdf_bytes.startswith(b"%PDF")

    zip_bytes = render_pdf_zip_per_company(one_company, meta)
    with ZipFile(BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        assert len(names) == 1
        assert names[0].endswith("Solo.pdf")


def test_sanitize_filename() -> None:
    assert sanitize_filename(' Firma:/\\*?"<>| test  ') == "Firma_test"
