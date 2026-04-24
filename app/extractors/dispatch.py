from pathlib import Path

from app.file_validation import CSV_MIME, PDF_MIME, XLSX_MIME
from app.extractors.base import ExtractionError, ExtractionPayload
from app.extractors.csv import extract_csv
from app.extractors.pdf import extract_pdf
from app.extractors.spreadsheet import extract_xlsx


def extract_document(
    path: Path | str,
    detected_content_type: str,
    original_filename: str | None = None,
) -> ExtractionPayload:
    path = Path(path)

    if detected_content_type == PDF_MIME:
        return extract_pdf(path)
    if detected_content_type == XLSX_MIME:
        return extract_xlsx(path)
    if detected_content_type == CSV_MIME:
        return extract_csv(path, original_filename=original_filename)

    raise ExtractionError(
        "UNSUPPORTED_FILE_TYPE",
        f"No extractor is registered for {detected_content_type}.",
    )
