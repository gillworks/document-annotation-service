from pathlib import Path
from zipfile import BadZipFile, ZipFile


class UnsupportedFileTypeError(Exception):
    pass


PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"
OCTET_STREAM_MIME = "application/octet-stream"

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".csv"}
DECLARED_MIME_BY_EXTENSION = {
    ".pdf": {PDF_MIME, OCTET_STREAM_MIME},
    ".xlsx": {XLSX_MIME, OCTET_STREAM_MIME},
    ".csv": {CSV_MIME, "application/csv", "text/plain", "application/vnd.ms-excel", OCTET_STREAM_MIME},
}


def detect_content_type(filename: str, header_bytes: bytes, path: Path | None = None) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError("Supported uploads must use .pdf, .xlsx, or .csv extensions.")

    if suffix == ".pdf" and header_bytes.startswith(b"%PDF-"):
        return PDF_MIME

    if suffix == ".xlsx" and header_bytes.startswith(b"PK") and looks_like_xlsx(path):
        return XLSX_MIME

    if suffix == ".csv" and looks_like_text(header_bytes):
        return CSV_MIME

    raise UnsupportedFileTypeError(
        "Supported uploads are .pdf, .xlsx, and .csv with recognizable file headers."
    )


def validate_declared_content_type(filename: str, declared_content_type: str | None) -> None:
    if not declared_content_type:
        return

    suffix = Path(filename).suffix.lower()
    allowed = DECLARED_MIME_BY_EXTENSION.get(suffix)
    if allowed is None:
        raise UnsupportedFileTypeError("Supported uploads must use .pdf, .xlsx, or .csv extensions.")

    base_type = declared_content_type.split(";", maxsplit=1)[0].strip().lower()
    if base_type not in allowed:
        raise UnsupportedFileTypeError(
            f"Declared content type {declared_content_type!r} does not match file extension {suffix!r}."
        )


def looks_like_xlsx(path: Path | None) -> bool:
    if path is None:
        return True
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
    except (BadZipFile, OSError):
        return False

    return "[Content_Types].xml" in names and "xl/workbook.xml" in names


def looks_like_text(header_bytes: bytes) -> bool:
    if not header_bytes:
        return True
    if b"\x00" in header_bytes:
        return False
    try:
        header_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return True
