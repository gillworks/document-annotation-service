import csv as csv_module
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.extractors.base import (
    MAX_SAMPLE_ROWS,
    ExtractionError,
    ExtractionPayload,
    stringify_cell,
    truncate_text,
)


def extract_csv(path: Path, original_filename: str | None = None) -> ExtractionPayload:
    try:
        display_name = original_filename or path.name
        sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
        dialect = csv_module.Sniffer().sniff(sample) if sample.strip() else csv_module.excel
        has_header = csv_module.Sniffer().has_header(sample) if sample.strip() else False

        rows: list[list[str]] = []
        total_rows = 0
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as csv_file:
            reader = csv_module.reader(csv_file, dialect)
            for row in reader:
                total_rows += 1
                if len(rows) < MAX_SAMPLE_ROWS:
                    rows.append([stringify_cell(value) for value in row])

        headers = rows[0] if has_header and rows else []
        data_rows = rows[1:] if headers else rows
        column_types = infer_column_types(headers, data_rows)
        text, truncated = truncate_text(render_csv_text(headers, data_rows, total_rows, dialect))

        warnings = []
        if total_rows > MAX_SAMPLE_ROWS:
            warnings.append(f"csv sampled first {MAX_SAMPLE_ROWS} rows")
        if truncated:
            warnings.append("extraction text truncated to 60000 characters")

        return ExtractionPayload(
            source_type="csv",
            text=text,
            sheets=[
                {
                    "name": display_name,
                    "row_count": total_rows,
                    "column_count": max((len(row) for row in rows), default=0),
                    "headers": headers,
                    "sample_rows": data_rows,
                    "column_types": column_types,
                }
            ],
            metadata={
                "page_count": None,
                "sheet_count": 1,
                "sheet_names": [display_name],
                "row_count": total_rows,
                "delimiter": dialect.delimiter,
                "has_tables": total_rows > 0,
            },
            warnings=warnings,
        )
    except Exception as exc:
        raise ExtractionError(
            "SPREADSHEET_PARSE_FAILED",
            f"CSV extraction failed: {exc}",
        ) from exc


def infer_column_types(headers: list[str], rows: list[list[str]]) -> dict[str, str]:
    if not rows:
        return {}

    column_count = max(len(row) for row in rows)
    names = headers or [f"column_{index + 1}" for index in range(column_count)]
    inferred: dict[str, str] = {}
    for index in range(column_count):
        values = [row[index] for row in rows if index < len(row) and row[index]]
        inferred[names[index] if index < len(names) else f"column_{index + 1}"] = infer_type(values)
    return inferred


def infer_type(values: list[str]) -> str:
    if not values:
        return "empty"
    if all(value.lower() in {"true", "false", "yes", "no"} for value in values):
        return "boolean"
    if all(is_int(value) for value in values):
        return "integer"
    if all(is_number(value) for value in values):
        return "number"
    if all(is_date_like(value) for value in values):
        return "date"
    return "string"


def is_int(value: str) -> bool:
    try:
        int(value.replace(",", ""))
    except ValueError:
        return False
    return True


def is_number(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def is_date_like(value: str) -> bool:
    for parser in (date.fromisoformat, datetime.fromisoformat):
        try:
            parser(value)
            return True
        except ValueError:
            pass
    return False


def render_csv_text(
    headers: list[str],
    rows: list[list[str]],
    total_rows: int,
    dialect: csv_module.Dialect,
) -> str:
    lines = [f"CSV rows: {total_rows}", f"Delimiter: {dialect.delimiter!r}"]
    if headers:
        lines.append("Headers: " + ", ".join(headers))
    for row in rows:
        if any(row):
            lines.append(" | ".join(row))
    return "\n".join(lines)
