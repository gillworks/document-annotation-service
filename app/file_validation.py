from pathlib import Path


class UnsupportedFileTypeError(Exception):
    pass


PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"


def detect_content_type(filename: str, header_bytes: bytes) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf" and header_bytes.startswith(b"%PDF-"):
        return PDF_MIME

    if suffix == ".xlsx" and header_bytes.startswith(b"PK"):
        return XLSX_MIME

    if suffix == ".csv" and looks_like_text(header_bytes):
        return CSV_MIME

    raise UnsupportedFileTypeError(
        "Supported uploads are .pdf, .xlsx, and .csv with recognizable file headers."
    )


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
