from pathlib import Path

from pypdf import PdfReader

from app.extractors.base import ExtractionError, ExtractionPayload, truncate_text


def extract_pdf(path: Path) -> ExtractionPayload:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractionError(
                    "PDF_TEXT_EXTRACTION_EMPTY",
                    "PDF is encrypted and cannot be read without a password.",
                ) from exc

        pages = []
        parts = []
        warnings = []

        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            pages.append({"page_number": index, "text": text})
            if text:
                parts.append(f"Page {index}\n{text}")

        full_text, truncated = truncate_text("\n\n".join(parts))
        if truncated:
            warnings.append("extraction text truncated to 60000 characters")

        if not full_text.strip():
            raise ExtractionError(
                "PDF_TEXT_EXTRACTION_EMPTY",
                "No machine-readable text was extracted from the PDF. OCR is not enabled.",
            )

        return ExtractionPayload(
            source_type="pdf",
            text=full_text,
            pages=pages,
            metadata={
                "page_count": len(reader.pages),
                "sheet_count": None,
                "has_tables": has_table_like_text(full_text),
            },
            warnings=warnings,
        )
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("UNKNOWN_WORKER_ERROR", f"PDF extraction failed: {exc}") from exc


def has_table_like_text(text: str) -> bool:
    lower_text = text.lower()
    table_markers = ("qty", "amount", "subtotal", "total due", "table")
    return sum(1 for marker in table_markers if marker in lower_text) >= 2
