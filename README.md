# Document Annotation Service

Small event-driven document annotation service scaffolded for the take-home prompt. It implements durable queue processing, document extraction, structured AI annotation, and an optional agent mode for cited annotations: uploads are streamed to shared storage, a queued job row is committed to Postgres, and a worker extracts and annotates the document asynchronously.

## Quick Start

Prereqs: Docker Desktop or Docker Engine with Compose v2.

```bash
cp .env.example .env
# Either set the API key for ANNOTATOR_PROVIDER, or set ANNOTATOR_MODE=mock for keyless local runs.
# Set ANNOTATOR_MODE=agent for grounded, cited annotations.
docker compose up
```

Upload a sample document:

```bash
curl -F "file=@samples/invoice.pdf" http://localhost:8000/documents
```

Poll for status:

```bash
curl http://localhost:8000/jobs/<job_id>
```

FastAPI docs are available at http://localhost:8000/docs.
Postgres is available for local GUI clients on `localhost:55432` with database/user/password `annotations`.

## Current Phase

Implemented from `plan.md` Phase 1 through the primary Phase 5 stretch:

- FastAPI app with `POST /documents` and `GET /jobs/{job_id}`.
- Chunked upload write with SHA-256 calculated in the same pass.
- Postgres `document_jobs` schema managed by Alembic.
- Postgres-as-queue worker claiming with `FOR UPDATE SKIP LOCKED`.
- Worker lifecycle updates: `queued` -> `processing` / `validating_file` -> `extracting_text` -> `storing_extraction` -> `calling_llm` -> `validating_output` -> `storing_result` -> `completed`.
- Stale `processing` job sweeper and retry/backoff helpers.
- PDF text extraction with page boundaries and scanned-PDF failure handling.
- XLSX workbook extraction with sheet metadata, sample rows, headers, and table-like signals.
- CSV extraction with delimiter detection, sample rows, row counts, and inferred column types.
- Pydantic annotation schema with broad entity types and structured result validation.
- `mock`, `single_call`, and `agent` strategies with OpenAI or Anthropic provider selection.
- Deterministic mock annotations for keyless local demos and hermetic tests.
- LangGraph-backed agent mode with deterministic document tools, cited annotations, citation verification, and per-step structured logs.
- Usage and configurable estimated-cost accounting on completed annotation jobs.
- Magic-byte/file-container validation for PDFs, XLSX workbooks, and CSV text.
- JSON structured application and worker logs.
- Focused pytest coverage for uploads, validation, queue guardrails, schema validation, and upload-volume behavior.
- `migrate` one-shot Compose service that waits for Postgres health.
- API and worker services wait for migrations before starting.
- Postgres published on host port `55432` for TablePlus/Postico inspection without colliding with local `5432`.
- Shared `uploads` Docker volume mounted into API and worker.
- `.env.example` plus startup fail-fast for missing provider config unless `ANNOTATOR_MODE=mock`.
- Unknown jobs return `404 {"detail":"Job not found"}`.

Use `ANNOTATOR_MODE=mock` to run the full extraction and annotation pipeline without a provider key or network cost. Non-mock modes fail fast on startup if the selected provider key is missing. Use `ANNOTATOR_PROVIDER=openai` with `OPENAI_API_KEY`, or `ANNOTATOR_PROVIDER=anthropic` with `ANTHROPIC_API_KEY`.

## Agent Mode

`ANNOTATOR_MODE` controls the annotation strategy:

- `single_call`: one schema-constrained provider call after extraction.
- `agent`: LangGraph `plan -> act -> verify -> finalize` flow.
- `mock`: deterministic local annotation with no provider key.

`ANNOTATOR_PROVIDER` controls the model backend for non-mock modes:

- `openai`
- `anthropic`

Single-call mode may populate best-effort risks, action items, PII categories, and citations, but any citation it emits is forced to `verification_status: "unverified"` and a warning is added because no document tool verified it. Agent mode drafts from the extracted document context, then uses deterministic document tools to verify citations:

- `get_page(page_number)` returns PDF page text.
- `list_sections()` returns page labels or sheet names.
- `get_sheet_sample(sheet_name, rows)` returns bounded spreadsheet samples.

The agent does not browse the web and does not write to the database directly. The worker remains responsible for persistence after the agent emits a schema-valid result. Agent mode enforces a citation-verification cap, applies `LLM_TIMEOUT_SECONDS` to the full run, validates the final output with the same Pydantic schema as other modes, and logs each verification step with `job_id`, `agent_step`, `tool`, `tool_args`, `duration_ms`, and citation verification status. Retrieval/RAG is intentionally deferred to Phase 6.

Every stored annotation includes `usage.provider` and `usage.annotator_mode` for provenance. Agent mode is the only path that may persist `verification_status: "verified"` or `"revised"`.

You can bias agent output with upload-time tasks:

```bash
curl -F "file=@samples/service_agreement.pdf" \
  -F "annotation_tasks=risks,payment_terms,parties" \
  http://localhost:8000/documents
```

## Samples

The `samples/` directory includes PDF, XLSX, and CSV fixtures. See `samples/README.md` for expected extraction highlights.

Useful examples:

```bash
curl -F "file=@samples/invoice.pdf" http://localhost:8000/documents
curl -F "file=@samples/service_agreement.pdf" http://localhost:8000/documents
curl -F "file=@samples/research_abstract.pdf" http://localhost:8000/documents
curl -F "file=@samples/transactions.xlsx" http://localhost:8000/documents
curl -F "file=@samples/contacts.csv" http://localhost:8000/documents
```

## Tests

Run the hermetic unit tests from the host:

```bash
python3 -m pytest
```

Run a full local smoke test manually:

```bash
docker compose up --build
curl -F "file=@samples/invoice.pdf" http://localhost:8000/documents
curl http://localhost:8000/jobs/<job_id>
docker compose logs -f worker
```

The expected completed job includes structured annotation `result` and `usage`. Add `?include_extraction=true` when you want the full extracted text payload for debugging.

## API

### `POST /documents`

Accepts multipart upload. Optional idempotency can be passed as `Idempotency-Key` header or `idempotency_key` form field. Agent mode can also use optional `annotation_tasks`, a comma-separated form field such as `risks,payment_terms,parties`.

Response:

```json
{
  "job_id": "4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44",
  "status": "queued",
  "status_url": "/jobs/4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44"
}
```

### `GET /jobs/{job_id}`

Returns job state. In the current flow, queued jobs should move to `completed` shortly after the worker extracts and annotates the document. The full extraction payload is omitted by default to keep status responses readable:

```json
{
  "job_id": "4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44",
  "status": "completed",
  "stage": "completed",
  "created_at": "2026-04-24T02:12:00Z",
  "updated_at": "2026-04-24T02:12:00Z",
  "result": {
    "schema_version": "1",
    "document_type": "invoice",
    "summary": "Synthetic invoice annotation for invoice.pdf: ...",
    "key_entities": [
      {
        "name": "invoice.pdf",
        "type": "filename",
        "confidence": 1.0,
        "citations": []
      }
    ],
    "important_dates": [],
    "action_items": [],
    "risks": [],
    "pii_detected": {
      "present": false,
      "types": [],
      "count": 0
    },
    "keywords": ["invoice"],
    "metadata": {
      "detected_language": "en",
      "page_count": 1,
      "sheet_count": null,
      "has_tables": true
    },
    "warnings": ["annotator: mock mode - result is synthetic"]
  },
  "usage": {
    "provider": "mock",
    "annotator_mode": "mock",
    "model": "mock",
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0
  },
  "error": null
}
```

For debugging extraction output, request it explicitly:

```bash
curl "http://localhost:8000/jobs/<job_id>?include_extraction=true"
```

## Design Notes

- Postgres is the durable queue: a committed `queued` row is the event the worker claims.
- Uploads are written before DB insert; if DB persistence fails, the API removes the new file.
- Files are stored outside the web root in `UPLOAD_DIR`.
- Content type detection is intentionally small for Phase 1 and supports `.pdf`, `.xlsx`, and `.csv`.
- `ANNOTATOR_MODE=mock` is available so reviewers can boot the stack without a provider key.
- `ANNOTATOR_MODE` and `ANNOTATOR_PROVIDER` are separate so either provider can back either single-call or agent execution.

## Tradeoffs

- **Postgres-as-queue:** keeps enqueueing atomic with job creation and avoids a Redis/Celery dependency for the take-home. At higher throughput, this could move to SQS/Pub/Sub/Kafka with an outbox pattern.
- **Local shared volume:** simple reviewer setup and proves API/worker decoupling. Production should move uploads to object storage with encryption, lifecycle policy, and malware scanning.
- **Bounded structured workflow by default:** the standard annotators use extraction tools plus one schema-enforced annotation call for latency, cost, and simpler failure handling. `agent` mode is a deliberate second strategy when grounded citations justify the extra steps.
- **Mock annotator:** makes the full pipeline deterministic and zero-cost locally. Real provider behavior still needs evals before production use.
- **Flexible JSONB result storage:** speeds iteration on schemas for the take-home. Production search/reporting may warrant normalized annotation tables or a separate analytics index.

## Production Readiness

Before exposing this beyond local review, add:

- Authentication and tenant-scoped authorization.
- Object storage for uploads and retention/deletion policies.
- OCR or document-intelligence fallback for scanned PDFs.
- Provider rate-limit handling with dead-letter/admin retry workflows.
- Metrics for queue depth, oldest queued job, failures by code, latency, and estimated cost.
- Secrets management instead of local `.env` files.
- Golden evals based on `samples/README.md` plus regression thresholds for extraction and annotation quality.
