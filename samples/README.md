# Sample Documents

These fixtures are small, known-good documents for local demos and future golden-eval coverage. They are intentionally synthetic.

## Expected Highlights

| File | Type | Expected extraction highlights |
| --- | --- | --- |
| `invoice.pdf` | PDF invoice | 1 page; invoice number `INV-2026-00142`; Acme Corporation; Wayne Enterprises; issued April 24, 2026; due May 24, 2026; total due `$15,388.12`; table-like line items. |
| `service_agreement.pdf` | PDF contract | 5 pages; master services agreement; Meridian Digital Solutions, Inc.; Northwind Traders, LLC; effective date, payment, confidentiality, and termination sections. |
| `research_abstract.pdf` | PDF research paper | 4 pages; academic/research document; adaptive neural architecture search; authors and institutional affiliations; abstract, methods, results, and conclusion-style sections. |
| `transactions.xlsx` | XLSX workbook | 3 sheets: `Summary`, `Q1_2026`, `Q2_2026`; transaction summary; category totals; sampled rows from each sheet; table-like spreadsheet metadata. |
| `contacts.csv` | CSV contacts list | 26 rows including header; comma delimiter; people, email, phone, company, role, department, city/state, and LinkedIn columns; sampled first 25 rows. |

## Golden-Eval Shape

A future eval harness should upload each file, wait for `status = completed`, and assert:

- `extraction.source_type` matches the file type.
- `extraction.metadata` contains the expected page, sheet, or row counts.
- `extraction.text` contains the listed highlights.
- `result.schema_version = "1"` once annotation is enabled.
- `result.document_type`, `key_entities`, `important_dates`, and `keywords` cover the expected highlights without requiring exact prose matches.
