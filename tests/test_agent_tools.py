from app.annotators.agent_tools import DocumentTools, verify_citation


def sample_extraction() -> dict:
    return {
        "source_type": "pdf",
        "text": "Page 1\nAcme Corporation pays invoices within 30 days.",
        "pages": [
            {
                "page_number": 1,
                "text": "Acme Corporation pays invoices within 30 days.",
            },
            {
                "page_number": 2,
                "text": "Late payments accrue interest after the due date.",
            },
        ],
        "sheets": [
            {
                "name": "Summary",
                "row_count": 2,
                "column_count": 2,
                "headers": ["Category", "Amount"],
                "sample_rows": [["Revenue", "$100"], ["Expense", "$25"]],
            }
        ],
    }


def test_search_document_returns_ranked_snippets() -> None:
    tools = DocumentTools(sample_extraction())

    results = tools.search_document("late payments", top_k=1)

    assert results == [
        {
            "page": 2,
            "sheet_name": None,
            "snippet": "Late payments accrue interest after the due date.",
            "score": 2,
        }
    ]


def test_get_page_and_sections() -> None:
    tools = DocumentTools(sample_extraction())

    assert tools.get_page(1) == "Acme Corporation pays invoices within 30 days."
    assert tools.list_sections() == ["Page 1", "Page 2"]


def test_get_sheet_sample_is_bounded() -> None:
    tools = DocumentTools(sample_extraction())

    sample = tools.get_sheet_sample("Summary", rows=1)

    assert "Sheet: Summary" in sample
    assert "Headers: Category, Amount" in sample
    assert "Revenue | $100" in sample
    assert "Expense | $25" not in sample


def test_verify_citation_marks_matching_snippet_verified() -> None:
    tools = DocumentTools(sample_extraction())

    citation = verify_citation(
        {
            "page_number": 1,
            "snippet": "Acme Corporation pays invoices within 30 days.",
            "confidence": 0.8,
        },
        tools,
    )

    assert citation["verification_status"] == "verified"


def test_verify_citation_marks_missing_snippet_unverified() -> None:
    tools = DocumentTools(sample_extraction())

    citation = verify_citation(
        {
            "page_number": 1,
            "snippet": "This text does not appear in the document.",
            "confidence": 0.8,
        },
        tools,
    )

    assert citation["verification_status"] == "unverified"
