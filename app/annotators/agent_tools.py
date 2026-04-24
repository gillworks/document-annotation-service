import re
from dataclasses import dataclass
from typing import Any


MAX_SNIPPET_CHARS = 240


@dataclass(frozen=True)
class SearchResult:
    page: int | None
    sheet_name: str | None
    snippet: str
    score: int


class DocumentTools:
    def __init__(self, extraction: dict[str, Any]) -> None:
        self.extraction = extraction

    def search_document(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        terms = tokenize(query)
        if not terms:
            return []

        results = []
        for record in self._records():
            lower_text = record["text"].lower()
            score = sum(lower_text.count(term) for term in terms)
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    page=record.get("page_number"),
                    sheet_name=record.get("sheet_name"),
                    snippet=best_snippet(record["text"], terms),
                    score=score,
                )
            )

        results.sort(key=lambda result: (-result.score, result.page or 0, result.sheet_name or ""))
        return [
            {
                "page": result.page,
                "sheet_name": result.sheet_name,
                "snippet": result.snippet,
                "score": result.score,
            }
            for result in results[: max(1, min(top_k, 20))]
        ]

    def get_page(self, page_number: int) -> str:
        for page in self.extraction.get("pages") or []:
            if page.get("page_number") == page_number:
                return str(page.get("text") or "")
        return ""

    def list_sections(self) -> list[str]:
        pages = [
            f"Page {page.get('page_number')}"
            for page in self.extraction.get("pages") or []
            if page.get("page_number") is not None
        ]
        sheets = [
            str(sheet.get("name"))
            for sheet in self.extraction.get("sheets") or []
            if sheet.get("name")
        ]
        return pages or sheets or ["Document"]

    def get_sheet_sample(self, sheet_name: str, rows: int = 20) -> str:
        for sheet in self.extraction.get("sheets") or []:
            if str(sheet.get("name") or "") == sheet_name:
                sample_rows = list(sheet.get("sample_rows") or [])[: max(1, min(rows, 50))]
                lines = [
                    f"Sheet: {sheet.get('name')}",
                    f"Rows: {sheet.get('row_count')}, Columns: {sheet.get('column_count')}",
                ]
                headers = sheet.get("headers") or []
                if headers:
                    lines.append("Headers: " + ", ".join(str(value) for value in headers))
                for row in sample_rows:
                    lines.append(" | ".join(str(value) for value in row))
                return "\n".join(lines)
        return ""

    def source_for_citation(self, citation: dict[str, Any]) -> str:
        page_number = citation.get("page_number")
        if page_number is not None:
            try:
                return self.get_page(int(page_number))
            except (TypeError, ValueError):
                return ""

        sheet_name = citation.get("sheet_name")
        if sheet_name:
            return self.get_sheet_sample(str(sheet_name), rows=50)

        return str(self.extraction.get("text") or "")

    def _records(self) -> list[dict[str, Any]]:
        records = []
        for page in self.extraction.get("pages") or []:
            records.append(
                {
                    "page_number": page.get("page_number"),
                    "sheet_name": None,
                    "text": str(page.get("text") or ""),
                }
            )
        for sheet in self.extraction.get("sheets") or []:
            records.append(
                {
                    "page_number": None,
                    "sheet_name": sheet.get("name"),
                    "text": render_sheet_text(sheet),
                }
            )
        if not records:
            records.append(
                {
                    "page_number": None,
                    "sheet_name": None,
                    "text": str(self.extraction.get("text") or ""),
                }
            )
        return records


def verify_annotation_payload(payload: dict[str, Any], tools: DocumentTools) -> dict[str, Any]:
    verified = dict(payload)
    for key in ("key_entities", "important_dates", "action_items", "risks"):
        items = verified.get(key) or []
        for item in items:
            if isinstance(item, dict):
                item["citations"] = [
                    verify_citation(citation, tools)
                    for citation in list(item.get("citations") or [])
                    if isinstance(citation, dict)
                ]
    return verified


def verify_citation(citation: dict[str, Any], tools: DocumentTools) -> dict[str, Any]:
    checked = dict(citation)
    snippet = str(checked.get("snippet") or "")
    source = tools.source_for_citation(checked)

    if not snippet.strip() or not source.strip():
        checked["verification_status"] = "unverified"
        return checked

    normalized_snippet = normalize_text(snippet)
    normalized_source = normalize_text(source)
    if normalized_snippet and normalized_snippet in normalized_source:
        checked["verification_status"] = "verified"
        return checked

    revised = closest_source_window(snippet, source)
    if revised:
        checked["snippet"] = revised
        checked["verification_status"] = "revised"
        return checked

    checked["verification_status"] = "unverified"
    return checked


def render_sheet_text(sheet: dict[str, Any]) -> str:
    lines = [
        f"Sheet: {sheet.get('name')}",
        f"Rows: {sheet.get('row_count')}, Columns: {sheet.get('column_count')}",
    ]
    headers = sheet.get("headers") or []
    if headers:
        lines.append("Headers: " + ", ".join(str(value) for value in headers))
    for row in sheet.get("sample_rows") or []:
        lines.append(" | ".join(str(value) for value in row))
    return "\n".join(lines)


def best_snippet(text: str, terms: list[str]) -> str:
    lower_text = text.lower()
    index = min(
        [position for term in terms if (position := lower_text.find(term)) >= 0],
        default=0,
    )
    start = max(index - MAX_SNIPPET_CHARS // 3, 0)
    end = min(start + MAX_SNIPPET_CHARS, len(text))
    return " ".join(text[start:end].split())


def closest_source_window(snippet: str, source: str) -> str | None:
    terms = set(tokenize(snippet))
    if not terms:
        return None

    best_score = 0
    best_window = None
    words = source.split()
    for index in range(0, len(words), 20):
        window = " ".join(words[index : index + 40])
        score = len(terms.intersection(tokenize(window)))
        if score > best_score:
            best_score = score
            best_window = window

    if best_window and best_score >= max(2, len(terms) // 2):
        return best_window[:MAX_SNIPPET_CHARS]
    return None


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9$][A-Za-z0-9$.,_-]*", text)]


def normalize_text(text: str) -> str:
    return " ".join(text.split()).lower()
