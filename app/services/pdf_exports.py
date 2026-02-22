"""PDF and ZIP exports for grouped company order reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import BytesIO
import re
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile


from app.utils.pdf_fonts import register_pdf_font

CompanyKey = tuple[str, str, str]


def _reportlab():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    return {
        "colors": colors,
        "A4": A4,
        "ParagraphStyle": ParagraphStyle,
        "getSampleStyleSheet": getSampleStyleSheet,
        "PageBreak": PageBreak,
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def sanitize_filename(value: str, max_length: int = 80) -> str:
    """Return a filesystem-friendly filename fragment."""
    normalized = re.sub(r"[\\/:*?\"<>|]+", "_", (value or "").strip())
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("._")
    return (normalized or "firma")[:max_length]


def _format_decimal_pln(value: Decimal | int | float) -> str:
    return f"{Decimal(value):.2f}"


def _company_key(order: dict[str, Any]) -> CompanyKey:
    return (
        str(order.get("company_name") or "Brak firmy"),
        str(order.get("company_address") or ""),
        str(order.get("company_zip") or ""),
    )


def group_orders_by_company(orders_df: Iterable[dict[str, Any]]) -> dict[CompanyKey, list[dict[str, Any]]]:
    grouped: dict[CompanyKey, list[dict[str, Any]]] = defaultdict(list)
    for order in orders_df:
        grouped[_company_key(order)].append(order)
    return dict(grouped)


def _sorted_company_keys(grouped: dict[CompanyKey, list[dict[str, Any]]]) -> list[CompanyKey]:
    return sorted(grouped.keys(), key=lambda key: (key[0].lower(), key[1].lower(), key[2].lower()))


def _build_styles() -> dict[str, Any]:
    font_name = register_pdf_font()
    rl = _reportlab()
    styles = rl["getSampleStyleSheet"]()
    return {
        "font_name": font_name,  # type: ignore[dict-item]
        "title": rl["ParagraphStyle"]("PdfTitle", parent=styles["Title"], fontName=font_name),
        "heading": rl["ParagraphStyle"]("PdfHeading2", parent=styles["Heading2"], fontName=font_name),
        "order_heading": rl["ParagraphStyle"]("PdfHeading4", parent=styles["Heading4"], fontName=font_name),
        "normal": rl["ParagraphStyle"]("PdfNormal", parent=styles["Normal"], fontName=font_name),
    }


def _company_section_story(orders: list[dict[str, Any]], company_key: CompanyKey, styles: dict[str, Any], meta: dict[str, Any]) -> list[Any]:
    company_name, company_address, company_zip = company_key
    story: list[Any] = []
    rl = _reportlab()
    story.append(rl["Paragraph"](f"Firma: {company_name}", styles["heading"]))
    if company_address or company_zip:
        story.append(rl["Paragraph"](f"Adres: {company_address} {company_zip}".strip(), styles["normal"]))
    story.append(rl["Paragraph"](f"Data raportu: {meta.get('today', date.today().isoformat())}", styles["normal"]))
    story.append(rl["Spacer"](1, 10))

    if not orders:
        story.append(rl["Paragraph"]("Brak zamówień dla tej firmy.", styles["normal"]))
        return story

    item_summary: dict[str, int] = defaultdict(int)
    for order in orders:
        for item in order.get("order_lines") or []:
            item_name = item.get("name") or "Pozycja"
            item_summary[item_name] += int(item.get("qty") or 0)

    summary_table = rl["Table"](
        [["Item", "Ilość"], *[[name, str(qty)] for name, qty in sorted(item_summary.items(), key=lambda x: x[0].lower())]],
        colWidths=[360, 100],
    )
    summary_table.setStyle(
        rl["TableStyle"](
            [
                ("BACKGROUND", (0, 0), (-1, 0), rl["colors"].lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, rl["colors"].black),
                ("FONTNAME", (0, 0), (-1, -1), styles["font_name"]),
            ]
        )
    )
    story.append(summary_table)
    story.append(rl["Spacer"](1, 10))

    story.append(rl["Paragraph"]("Lista zamówień", styles["heading"]))
    for order in orders:
        payment = order.get("payment_status") or order.get("payment_method") or "-"
        story.append(rl["Paragraph"](f"Nr zamówienia: {order.get('order_number') or '-'} • #{order.get('id', '-')} • {order.get('time', '-')} • Płatność: {payment}", styles["order_heading"]))
        story.append(rl["Paragraph"](f"Klient: {order.get('user_name') or order.get('customer_identifier') or '-'}", styles["normal"]))
        story.append(rl["Paragraph"](f"Uwagi: {order.get('notes') or '-'}", styles["normal"]))
        for item in order.get("order_lines") or []:
            unit_price = item.get("unit_price") or item.get("price") or 0
            story.append(rl["Paragraph"](f"• {item.get('name', 'Pozycja')} x{item.get('qty', 0)} ({_format_decimal_pln(unit_price)} zł)", styles["normal"]))
        story.append(rl["Paragraph"](f"Razem: {_format_decimal_pln(order.get('total_amount') or 0)} zł", styles["normal"]))
        story.append(rl["Paragraph"]("_" * 110, styles["normal"]))

    return story


def render_pdf_for_company(orders_df: Iterable[dict[str, Any]], company_key: CompanyKey, meta: dict[str, Any], output_path_or_bytes: str | None = None) -> bytes:
    """Generate report PDF for exactly one company and return bytes."""
    styles = _build_styles()
    grouped = group_orders_by_company(orders_df)
    company_orders = grouped.get(company_key, [])

    story: list[Any] = [
        _reportlab()["Paragraph"](f"Zamówienia — {meta.get('today', date.today().isoformat())}", styles["title"]),
        _reportlab()["Paragraph"](f"Wygenerowano: {meta.get('generated_at', '-')}", styles["normal"]),
        _reportlab()["Spacer"](1, 10),
    ]
    story.extend(_company_section_story(company_orders, company_key, styles, meta))

    buffer = BytesIO()
    rl = _reportlab()
    rl["SimpleDocTemplate"](buffer, pagesize=rl["A4"]).build(story)
    payload = buffer.getvalue()
    if output_path_or_bytes:
        with open(output_path_or_bytes, "wb") as output_file:
            output_file.write(payload)
    return payload


def render_pdf_combined(all_orders_df: Iterable[dict[str, Any]], meta: dict[str, Any]) -> bytes:
    """Generate one PDF containing all companies, one company per page."""
    styles = _build_styles()
    grouped = group_orders_by_company(all_orders_df)
    keys = _sorted_company_keys(grouped)

    story: list[Any] = [
        _reportlab()["Paragraph"](f"Raport zamówień (zbiorczy) — {meta.get('today', date.today().isoformat())}", styles["title"]),
        _reportlab()["Paragraph"](f"Wygenerowano: {meta.get('generated_at', '-')}", styles["normal"]),
        _reportlab()["Spacer"](1, 12),
    ]

    for index, key in enumerate(keys):
        orders = grouped[key]
        story.extend(_company_section_story(orders, key, styles, meta))
        if index < len(keys) - 1:
            story.append(_reportlab()["PageBreak"]())

    buffer = BytesIO()
    rl = _reportlab()
    rl["SimpleDocTemplate"](buffer, pagesize=rl["A4"]).build(story)
    return buffer.getvalue()


def render_pdf_zip_per_company(all_orders_df: Iterable[dict[str, Any]], meta: dict[str, Any]) -> bytes:
    """Generate ZIP archive with one company PDF per file."""
    grouped = group_orders_by_company(all_orders_df)
    keys = _sorted_company_keys(grouped)
    report_date = meta.get("today", date.today().isoformat())

    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for key in keys:
            company_pdf = render_pdf_for_company(all_orders_df, key, meta)
            company_name = sanitize_filename(key[0])
            filename = f"Raport_zamowien_{report_date}_{company_name}.pdf"
            archive.writestr(filename, company_pdf)
    return zip_buffer.getvalue()
