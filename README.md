# Document Annotation Service

Small event-driven document annotation service scaffolded for the take-home prompt. Phase 1 implements the durable API skeleton: uploads are streamed to shared storage, a queued job row is committed to Postgres, and job status can be read by ID.

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

## Current Phase

Implemented from `plan.md` Phase 1:

- FastAPI app with `POST /documents` and `GET /jobs/{job_id}`.
- Chunked upload write with SHA-256 calculated in the same pass.
- Postgres `document_jobs` schema managed by Alembic.
- `migrate` one-shot Compose service that waits for Postgres health.
- API and worker services wait for migrations before starting.
- No host Postgres port published by default.
- Shared `uploads` Docker volume mounted into API and worker.
- `.env.example` plus startup fail-fast for missing provider config unless `ANNOTATOR_MODE=mock`.
- Unknown jobs return `404 {"detail":"Job not found"}`.

The worker is intentionally a no-op placeholder in Phase 1. Queue claiming, document extraction, and annotation are Phase 2 onward.

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

Returns queued job state in Phase 1:

```json
{
  "job_id": "4edb40bd-b34d-4ce1-a7c4-01a7d28dbf44",
  "status": "queued",
  "stage": "queued",
  "created_at": "2026-04-24T02:12:00Z",
  "updated_at": "2026-04-24T02:12:00Z",
  "result": null,
  "usage": null,
  "error": null
}
```

## Design Notes

- Postgres is the durable queue: a committed `queued` row is the event the future worker will claim.
- Uploads are written before DB insert; if DB persistence fails, the API removes the new file.
- Files are stored outside the web root in `UPLOAD_DIR`.
- Content type detection is intentionally small for Phase 1 and supports `.pdf`, `.xlsx`, and `.csv`.
- `ANNOTATOR_MODE=mock` is available so reviewers can boot the stack without a provider key.
