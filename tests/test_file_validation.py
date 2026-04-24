from pathlib import Path
from zipfile import ZipFile

import pytest

from app.file_validation import (
    CSV_MIME,
    PDF_MIME,
    XLSX_MIME,
    UnsupportedFileTypeError,
    detect_content_type,
    validate_declared_content_type,
)


def test_detects_pdf_by_extension_and_magic_bytes() -> None:
    assert detect_content_type("invoice.pdf", b"%PDF-1.4\n") == PDF_MIME


def test_detects_csv_as_utf8_text() -> None:
    assert detect_content_type("contacts.csv", b"name,email\nAda,ada@example.com\n") == CSV_MIME


def test_detects_xlsx_by_zip_container_entries(tmp_path: Path) -> None:
    path = tmp_path / "transactions.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("xl/workbook.xml", "<workbook />")

    assert detect_content_type("transactions.xlsx", path.read_bytes()[:8192], path) == XLSX_MIME


def test_rejects_zip_without_xlsx_workbook(tmp_path: Path) -> None:
    path = tmp_path / "not-a-workbook.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr("notes.txt", "not a workbook")

    with pytest.raises(UnsupportedFileTypeError):
        detect_content_type("not-a-workbook.xlsx", path.read_bytes()[:8192], path)


def test_rejects_declared_mime_that_conflicts_with_extension() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        validate_declared_content_type("invoice.pdf", "text/csv")


def test_allows_octet_stream_for_cli_uploads() -> None:
    validate_declared_content_type("invoice.pdf", "application/octet-stream")
