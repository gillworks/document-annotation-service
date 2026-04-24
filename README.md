# Document Annotation Service

Small event-driven document annotation service scaffolded for the take-home prompt. Phase 4 implements durable queue processing, document extraction, and structured AI annotation: uploads are streamed to shared storage, a queued job row is committed to Postgres, and a worker extracts and annotates the document asynchronously.

## Quick Start

Prereqs: Docker Desktop or Docker Engine with Compose v2.

```bash
cp .env.example .env
# Either set OPENAI_API_KEY in .env, or set ANNOTATOR_MODE=mock for keyless local runs.
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

Implemented from `plan.md` Phase 1 through Phase 5 polish:

- FastAPI app with `POST /documents` and `GET /jobs/{job_id}`.
- Chunked upload write with SHA-256 calculated in the same pass.
- Postgres `document_jobs` schema managed by Alembic.
- Postgres-as-queue worker claiming with `FOR UPDATE SKIP LOCKED`.
- Worker lifecycle updates: `queued` -> `processing` / `validating_file` -> `extracting_text` -> `calling_llm` -> `validating_output` -> `storing_result` -> `completed`.
- Stale `processing` job sweeper and retry/backoff helpers.
- PDF text extraction with page boundaries and scanned-PDF failure handling.
- XLSX workbook extraction with sheet metadata, sample rows, headers, and table-like signals.
- CSV extraction with delimiter detection, sample rows, row counts, and inferred column types.
- Pydantic annotation schema with broad entity types and structured result validation.
- `mock`, `openai`, and `anthropic` annotator implementations behind one worker interface.
- Deterministic mock annotations for keyless local demos and hermetic tests.
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

Use `ANNOTATOR_MODE=mock` to run the full extraction and annotation pipeline without a provider key or network cost. Provider modes fail fast on startup if the relevant API key is missing.

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

The expected completed job includes `extraction`, structured annotation `result`, and `usage`.

## API

### `POST /documents`

Accepts multipart upload. Optional idempotency can be passed as `Idempotency-Key` header or `idempotency_key` form field.

Response:

```json
{
  "job_id": "4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44",
  "status": "queued",
  "status_url": "/jobs/4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44"
}
```

### `GET /jobs/{job_id}`

Returns job state. In Phase 4, queued jobs should move to `completed` shortly after the worker extracts and annotates the document:

```json
{
  "job_id": "4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44",
  "status": "completed",
  "stage": "completed",
  "created_at": "2026-04-24T02:12:00Z",
  "updated_at": "2026-04-24T02:12:00Z",
  "extraction": {
    "schema_version": "extraction.v1",
    "source_type": "pdf",
    "text": "Page 1\nInvoice INV-1001...",
    "metadata": {
      "page_count": 1,
      "sheet_count": null,
      "has_tables": false
    },
    "pages": [
      {
        "page_number": 1,
        "text": "Invoice INV-1001..."
      }
    ],
    "sheets": [],
    "warnings": []
  },
  "result": {
    "schema_version": "1",
    "document_type": "invoice",
    "summary": "Synthetic invoice annotation for invoice.pdf: ...",
    "key_entities": [
      {
        "name": "invoice.pdf",
        "type": "filename",
        "confidence": 1.0
      }
    ],
    "important_dates": [],
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
    "model": "mock",
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0
  },
  "error": null
}
```

## Design Notes

- Postgres is the durable queue: a committed `queued` row is the event the worker claims.
- Uploads are written before DB insert; if DB persistence fails, the API removes the new file.
- Files are stored outside the web root in `UPLOAD_DIR`.
- Content type detection is intentionally small for Phase 1 and supports `.pdf`, `.xlsx`, and `.csv`.
- `ANNOTATOR_MODE=mock` is available so reviewers can boot the stack without a provider key.

## Tradeoffs

- **Postgres-as-queue:** keeps enqueueing atomic with job creation and avoids a Redis/Celery dependency for the take-home. At higher throughput, this could move to SQS/Pub/Sub/Kafka with an outbox pattern.
- **Local shared volume:** simple reviewer setup and proves API/worker decoupling. Production should move uploads to object storage with encryption, lifecycle policy, and malware scanning.
- **Bounded structured workflow:** the worker uses extraction tools plus one schema-enforced annotation call instead of an open-ended agent loop. This keeps latency, cost, and failure handling easier to reason about.
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
