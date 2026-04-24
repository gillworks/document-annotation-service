# Document Annotation Service

An event-driven document annotation service: upload a PDF or spreadsheet, get a `job_id` back immediately, and poll for an LLM-extracted structured annotation. The architecture is async by design so processing can take longer than any HTTP timeout, and the annotation strategy is deliberately _layered_ — a fast, schema-enforced single LLM call by default, plus an optional **LangGraph agent mode** that produces page-anchored, verified citations when grounding actually matters.

## TL;DR

- **Two endpoints, three annotator strategies, one durable queue.** `POST /documents` returns `202 Accepted` with a `job_id` while a worker processes the document asynchronously. `GET /jobs/{job_id}` returns the structured annotation when ready.
- **Postgres is both the job store _and_ the queue.** A committed `queued` row is the event the worker reacts to (`FOR UPDATE SKIP LOCKED`). No separate broker, no API/broker dual-write to fail.
- **Three annotator modes share one interface.** `mock` (deterministic, keyless, $0), `single_call` (one schema-enforced call to OpenAI or Anthropic — the default), and `agent` (LangGraph plan→act→verify→finalize that returns citations the worker forces unverified for single-call output and only the agent's `verify` node may mark `verified`).

```yaml
service: document-annotation-service
endpoints: [POST /documents, GET /jobs/{job_id}, GET /healthz, GET /readyz]
annotator_modes: [mock, single_call, agent]
providers: [openai, anthropic]
agent_framework: langgraph (plan -> act -> verify -> finalize)
queue: postgres-as-queue (FOR UPDATE SKIP LOCKED + sweeper)
result_schema: app/annotation_schema.py (schema_version "1", with citations + verification_status)
key_files:
  - app/annotators/agent.py            # LangGraph agent + tool dispatch
  - app/annotators/agent_tools.py      # deterministic document tools + verify_citation
  - app/annotators/base.py             # single-call boundary (forces unverified status)
  - app/annotation_schema.py           # output contract
  - app/queue.py                       # claim, sweep, retry/backoff
  - app/worker.py                      # pipeline + retryable vs deterministic errors
  - app/main.py                        # HTTP layer + idempotency
  - tests/test_prompt_injection_guards.py
```

---

## Quick Start

Prereqs: Docker Desktop, or Docker Engine with Compose v2.

```bash
cp .env.example .env
# Set OPENAI_API_KEY (or ANTHROPIC_API_KEY with ANNOTATOR_PROVIDER=anthropic),
# OR set ANNOTATOR_MODE=mock to run end-to-end with no provider key.
docker compose up
```

Upload a sample document and poll:

```bash
JOB=$(curl -s -F "file=@samples/invoice.pdf" http://localhost:8000/documents | jq -r .job_id)
curl -s "http://localhost:8000/jobs/$JOB" | jq
```

FastAPI's interactive docs are at <http://localhost:8000/docs>. Postgres is published on `localhost:55432` (intentionally not `5432` — avoids colliding with a host install) for inspection with TablePlus or `psql`.

To bias agent annotations toward specific concerns, pass `annotation_tasks`:

```bash
curl -F "file=@samples/service_agreement.pdf" \
     -F "annotation_tasks=risks,payment_terms,parties" \
     http://localhost:8000/documents
```

A reviewer with no API key can run the entire pipeline end-to-end with `ANNOTATOR_MODE=mock`. The mock annotator returns deterministic, schema-valid results derived from the extracted text and is also the default annotator in the test suite.

---

## What I Built

The take-home brief asked for an event-driven document annotation service that accepts uploads, returns a job ID immediately, processes documents asynchronously, and exposes a retrieval endpoint.

My read of the problem statement contains two structural pressures and one judgment call. The two pressures are **durability** (the job and its work must survive a crash between accepting an upload and finishing processing) and **decoupling** (the API must return _now_, the worker must process _later_, and they must never share a request handle). The judgment call is how to approach the phrase "AI agent should process the document", meaning whether to interpret the brief loosely as "run an LLM on it" or strictly as "build something agentic, with tool use and a decision loop."

I chose to answer all 3 in my implementation. **Durability** lives in Postgres: a committed `queued` row in `document_jobs` is itself the queue event, claimed by the worker with `SELECT … FOR UPDATE SKIP LOCKED`. There is no separate broker (no Redis, no Celery), so the API never has the dual-write problem of "row inserted but enqueue failed." A periodic sweeper requeues rows whose worker lock has gone stale. **Decoupling** is the standard async-job pattern: upload streams to a shared volume, validates magic bytes, computes SHA-256 in the same pass, commits a job row in one transaction, returns `202 Accepted`. The worker runs in its own container, polls Postgres, and writes back results.

Now, onto how I chose to answer the judgment call in my implementation. **The annotation step ships in three modes behind a single `Annotator` interface**: `mock` for keyless local runs and hermetic tests, `single_call` for a fast schema-enforced one-shot LLM call (the default and imo the right tool for bounded metadata extraction), and `agent` for a LangGraph flow that uses deterministic document tools to draft and then _verify_ citations grounded in the source. The single-call mode is cheaper and faster. The agent mode does something the single-call mode cannot do honestly: produce citations whose `verification_status` is `verified` because the agent's `verify` node has independently re-fetched the cited page and confirmed the snippet appears there. To be clear, the single-call model has seen the document text in its prompt too, but no code in that path checks its citation claims; the boundary forces every citation it emits to `unverified` regardless of what the model said. That distinction is enforced in code, not in prompts, and is the load-bearing decision of this submission.

---

## Reviewer's 90-Second Tour

If you have only 2 mins, the most informative files are:

| File                                    | Why it's worth reading                                                                                                                                                                  |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/annotators/agent.py`               | The LangGraph `plan → act → verify → finalize` graph, including the deadline-checked tool loop and the citation verification pass. ~340 lines.                                          |
| `app/annotators/base.py`                | `enforce_single_call_citation_provenance` — the code that prevents single-call modes from claiming `verified`. The trust boundary, in a single function.                                |
| `app/annotators/agent_tools.py`         | The deterministic tools the agent is allowed to call (`get_page`, `list_sections`, `get_sheet_sample`, `verify_citation`). Notice what's _not_ there: web search, DB writes.            |
| `app/queue.py`                          | `CLAIM_NEXT_JOB_SQL` (`FOR UPDATE SKIP LOCKED`), the sweeper, and the retry/backoff helper. The queue _is_ the table.                                                                   |
| `app/worker.py`                         | The pipeline: `validating_file → extracting_text → storing_extraction → calling_llm → validating_output → storing_result → completed`, plus the retryable-vs-deterministic error split. |
| `app/annotation_schema.py`              | The output contract: entities, dates, action items, risks, PII presence-only — every citation-bearing item carries `Citation` objects with a `verification_status`.                     |
| `tests/test_prompt_injection_guards.py` | Tests that assert untrusted document content is rendered inside fenced blocks with explicit "do not follow instructions" framing.                                                       |

---

## Example Outputs

These are the shapes a reviewer should expect when uploading the bundled samples. Cost values reflect the per-token rates set in `.env`; `mock` mode is always `$0`.

### `samples/invoice.pdf` — `single_call` mode (default)

```json
{
  "job_id": "f8a1c4b2-9d6e-4f01-8a12-b3c8e9d2f3a4",
  "status": "completed",
  "stage": "completed",
  "created_at": "2026-04-24T22:18:03Z",
  "updated_at": "2026-04-24T22:18:11Z",
  "result": {
    "schema_version": "1",
    "document_type": "invoice",
    "summary": "Invoice INV-2026-00142 from Acme Corporation to Wayne Enterprises for office equipment. Issued April 24, 2026; total due $15,388.12 by May 24, 2026.",
    "key_entities": [
      {
        "name": "Acme Corporation",
        "type": "organization",
        "confidence": 0.94,
        "citations": [
          {
            "snippet": "Acme Corporation",
            "page_number": 1,
            "sheet_name": null,
            "confidence": 0.7,
            "verification_status": "unverified"
          }
        ]
      },
      {
        "name": "Wayne Enterprises",
        "type": "organization",
        "confidence": 0.93,
        "citations": []
      },
      {
        "name": "$15,388.12",
        "type": "money",
        "confidence": 0.95,
        "citations": []
      }
    ],
    "important_dates": [
      { "label": "issued", "value": "2026-04-24", "citations": [] },
      { "label": "due", "value": "2026-05-24", "citations": [] }
    ],
    "action_items": [],
    "risks": [],
    "pii_detected": { "present": false, "types": [], "count": 0 },
    "keywords": ["invoice", "office equipment", "payment due"],
    "metadata": {
      "detected_language": "en",
      "page_count": 1,
      "sheet_count": null,
      "has_tables": true
    },
    "warnings": [
      "annotator: single-call citations are LLM-claimed, not verified by tool use"
    ]
  },
  "usage": {
    "provider": "openai",
    "annotator_mode": "single_call",
    "model": "gpt-4o-mini",
    "input_tokens": 1842,
    "output_tokens": 384,
    "estimated_cost_usd": 0.000507
  },
  "error": null
}
```

Note the explicit `verification_status: "unverified"` and the `warnings` entry. The single-call boundary forces both, regardless of what the model claimed in its raw response.

### `samples/service_agreement.pdf` — `agent` mode

```json
{
  "job_id": "2c9b1e7d-4a83-4b2c-9f50-1e8c3a7d6b09",
  "status": "completed",
  "stage": "completed",
  "result": {
    "schema_version": "1",
    "document_type": "master services agreement",
    "summary": "Master services agreement between Meridian Digital Solutions, Inc. and Northwind Traders, LLC effective May 1, 2026, covering payment terms, confidentiality, and termination.",
    "key_entities": [
      {
        "name": "Meridian Digital Solutions, Inc.",
        "type": "organization",
        "confidence": 0.97,
        "citations": [
          {
            "snippet": "Meridian Digital Solutions, Inc. (\"Provider\")",
            "page_number": 1,
            "confidence": 0.93,
            "verification_status": "verified"
          }
        ]
      },
      {
        "name": "Northwind Traders, LLC",
        "type": "organization",
        "confidence": 0.97,
        "citations": [
          {
            "snippet": "Northwind Traders, LLC (\"Client\")",
            "page_number": 1,
            "confidence": 0.92,
            "verification_status": "verified"
          }
        ]
      }
    ],
    "important_dates": [
      {
        "label": "effective_date",
        "value": "2026-05-01",
        "citations": [
          {
            "snippet": "shall be effective as of May 1, 2026",
            "page_number": 1,
            "confidence": 0.94,
            "verification_status": "verified"
          }
        ]
      }
    ],
    "action_items": [
      {
        "description": "Provider to deliver SOW within 10 business days of execution",
        "owner": "Provider",
        "deadline": null,
        "citations": [
          {
            "snippet": "deliver each Statement of Work within ten (10) business days",
            "page_number": 2,
            "confidence": 0.86,
            "verification_status": "verified"
          }
        ]
      }
    ],
    "risks": [
      {
        "description": "Liability cap limited to fees paid in the prior 12 months",
        "severity": "medium",
        "citations": [
          {
            "snippet": "total aggregate liability ... shall not exceed the fees paid or payable ... during the twelve (12) month period preceding the event",
            "page_number": 4,
            "confidence": 0.88,
            "verification_status": "verified"
          }
        ]
      },
      {
        "description": "Late payments accrue interest at 1.5% per month",
        "severity": "low",
        "citations": [
          {
            "snippet": "Late payments shall accrue interest at the rate of 1.5% per month",
            "page_number": 3,
            "confidence": 0.9,
            "verification_status": "verified"
          }
        ]
      }
    ],
    "pii_detected": { "present": false, "types": [], "count": 0 },
    "keywords": ["msa", "confidentiality", "termination", "liability"],
    "metadata": {
      "detected_language": "en",
      "page_count": 5,
      "sheet_count": null,
      "has_tables": false
    },
    "warnings": []
  },
  "usage": {
    "provider": "openai",
    "annotator_mode": "agent",
    "model": "gpt-4o-mini",
    "agent_tool_calls": 6,
    "agent_verification_calls": 6,
    "agent_context_chars": 8412,
    "agent_context_truncated": false,
    "input_tokens": 9420,
    "output_tokens": 1186,
    "estimated_cost_usd": 0.002126
  },
  "error": null
}
```

Every citation in this output has `verification_status: "verified"`. That tag is set by the agent's `verify` graph node only after the corresponding `get_page` call confirms the snippet appears in the source — there is no path through the code that allows the model to self-claim it.

### `samples/transactions.xlsx` — `mock` mode (no API key needed)

```json
{
  "job_id": "11a4d2f0-7b6c-4d09-9e23-08f4c2b9a1d3",
  "status": "completed",
  "stage": "completed",
  "result": {
    "schema_version": "1",
    "document_type": "spreadsheet",
    "summary": "Synthetic spreadsheet annotation for transactions.xlsx: Sheet: Summary | Rows: 6, Columns: 2 | Headers: Category, Total ...",
    "key_entities": [
      {
        "name": "transactions.xlsx",
        "type": "filename",
        "confidence": 1.0,
        "citations": []
      }
    ],
    "important_dates": [],
    "action_items": [],
    "risks": [],
    "pii_detected": { "present": false, "types": [], "count": 0 },
    "keywords": ["spreadsheet"],
    "metadata": {
      "detected_language": "en",
      "page_count": null,
      "sheet_count": 3,
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

Mock mode keeps the full async pipeline live — extraction, queue, worker, persistence — while costing nothing and requiring no API key. It's the entrypoint a reviewer can run in ~30 seconds without setup.

---

## My Design Decisions and Tradeoffs

These are the choices that materially shape my submission, with the alternative I rejected and the reason.

- **Event-driven via a durable event in Postgres, not a separate broker.** Inserting the `queued` row _is_ the event. The worker reacts by claiming it with `FOR UPDATE SKIP LOCKED`. The alternative is Redis + Celery, which I decided against because it introduces the classic dual-write bug (row inserted, enqueue fails) and adds a second dependency without earning it at this throughput. In production the same shape moves to SQS or Pub/Sub with a transactional outbox; the API and worker contracts do not change.
- **Three annotator modes behind one interface.** The standard request is bounded metadata extraction, which a single schema-enforced LLM call handles best — fast, cheap, easy to evaluate, single failure mode. The `agent` mode exists for a different problem — _grounded, verifiably cited annotation_ — which a single call can't deliver, because nothing in the single-call path confirms that emitted citations actually appear in the source. The model can quote what it saw in its prompt, but only the agent's `verify` node re-fetches each cited page via `get_page` and runs a deterministic match before stamping any citation `verified`. `mock` exists for keyless local review and hermetic tests. Routing between them is a product decision; switching modes is one env var.
- **The agent uses LangGraph, not a hand-rolled loop.** LangGraph's `StateGraph` makes the agent's flow auditable as a graph (`plan → act → verify → finalize`) rather than a tangle of nested calls. Each node logs structured per-step events. The framework cost is real (one dependency, one mental model) but pays for itself in legibility.
- **Citation verification is enforced in code at the annotator boundary, not in prompts.** `enforce_single_call_citation_provenance` walks the LLM output and forces every citation's `verification_status` to `unverified`, regardless of what the model claimed. Only the agent's `verify` node — which calls `get_page` and confirms the snippet appears verbatim — is allowed to set `verified`. Prompts can be ignored; code cannot.
- **Idempotency is two distinct things.** Transport-layer retry safety is a client-generated `Idempotency-Key` (Stripe / AWS pattern; the human user never sees one). Content identity is a SHA-256 stored on every job for audit, intentionally _not_ used for automatic dedupe — two users uploading the same document expect two annotation jobs. A short-window content guardrail is the next obvious add (see "What I'd improve").
- **No vector search, no Pinecone, no RAG.** Documents are bounded (25 MB, ≤ 60k char extraction text), processed once per job, and queried by a step-capped agent within a single document. BM25-style keyword tools over the already-extracted text are deterministic, zero-latency, and sufficient. Vector retrieval is the right tool for _cross-document corpora_, which belongs to the production extension (see "Designed, not shipped"). Adding Pinecone here would have been complexity that the problem doesn't demand.
- **Truncation, not chunking, for v1.** Documents over the prompt budget are truncated and a `warnings` entry is emitted. Chunked map-reduce extraction is the right production answer; for the take-home it would have replaced shipping the agent and was deferred intentionally.
- **JSONB result, not a normalized annotation table.** The schema will evolve. JSONB lets the contract iterate without migrations per field. Frequently queried fields (e.g. `document_type`, cost) are still promoted to columns where it matters. A production system would normalize hot fields after the schema stabilizes.
- **Local filesystem + shared Docker volume in dev; S3 in production.** The storage layer is behind a small interface so swapping is a single adapter, not a rewrite. The compose file mounts a named `uploads` volume into both API and worker so the worker can actually read what the API wrote — a one-line bug I tested for explicitly (`tests/test_shared_volume.py`).
- **No OCR for v1.** Scanned PDFs return a structured failure (`PDF_TEXT_EXTRACTION_EMPTY`) rather than silently producing empty annotations. The right OCR addition is Tesseract or a managed document-intelligence service behind the existing parser interface.
- **Postgres published on host port `55432`, not `5432`.** Reviewers commonly already have a local Postgres on `5432`. Using `55432:5432` avoids a noisy "port already in use" failure on first `docker compose up`.

---

## The Agent: Why It Exists, How It Works

The single-call modes are correct for most jobs. The agent is the right tool when you need a citation a human can trust.

### Graph

```
plan → act → verify → finalize
```

- **plan**: build the document context (full extracted text up to the prompt budget; truncation flag set otherwise) and the section/sheet list.
- **act**: call the configured provider (OpenAI Responses API or Anthropic tool-use) with the schema as a structured-output constraint, conditioned on `annotation_tasks` if supplied, and produce a _draft_ `AnnotationResult`. The draft may include citations the model believes are grounded.
- **verify**: walk every citation in the draft. For each, call `get_page` (or `get_sheet_sample` for spreadsheets) and call `verify_citation`, which checks whether the snippet appears verbatim — or close enough — in the actual page text. Set `verification_status` to `verified`, `unverified`, or `revised` based on what was found. The verification step is bounded by `MAX_AGENT_VERIFICATION_CALLS = 16` and by the wall-clock deadline derived from `LLM_TIMEOUT_SECONDS`.
- **finalize**: re-validate against the Pydantic schema and return.

### Tools the agent has

- `get_page(page_number)` — full text of one page (PDF) or sheet (XLSX).
- `list_sections()` — page labels or sheet names so the agent can plan over structure.
- `get_sheet_sample(sheet_name, rows)` — bounded spreadsheet sampling.
- `verify_citation` — internal, used during the verify node.

### Tools the agent doesn't have, and why

- **No web search / browsing.** An agent that can browse is a different product and a different risk profile. This agent only knows the document.
- **No database writes.** Persistence stays in worker code. The LLM never mutates state directly; it only emits a schema-valid `AnnotationResult` that the worker validates and persists.
- **No retrieval over other documents.** The corpus for any one job is one document. Cross-document retrieval is a production-extension concern, not an agent concern.

### Per-step observability

Every verification call emits a structured log line with `job_id`, `agent_step`, `tool`, `tool_args`, `duration_ms`, and the resulting `verification_status`. The completed job's `usage` block also records `agent_tool_calls`, `agent_verification_calls`, `agent_context_chars`, and `agent_context_truncated`. The agent's behavior is fully reconstructible from logs and the stored job — there is no opaque "the agent did stuff" black box.

### `annotation_tasks`

`POST /documents` accepts an optional `annotation_tasks` form field — a comma-separated list like `risks,payment_terms,parties`. The values are rendered into the agent's prompt as task hints. The plumbing is end-to-end (HTTP form → DB column → agent prompt) but the _output variance_ between task sets is currently subtle, because the annotation schema is shared across tasks. Making tasks load-bearing — task-specific schemas or required output sections — is one of the cleanest v2 features and is named in my "What I'd improve" section.

---

## Security & Safety

A take-home is not a finished security model, but several decisions in this submission _are_ safety-shaped on purpose.

### Prompt injection guards

One of the biggest LLM-specific risks in a document annotation service is the document itself instructing the model to do something hostile. This implementation:

- Renders all untrusted document content inside fenced blocks (`UNTRUSTED CONTENT BEGINS / ENDS`) using a single helper (`render_untrusted_block` in `app/annotators/base.py`).
- Adds an explicit system instruction (`UNTRUSTED_CONTENT_INSTRUCTION`) that tells the model to treat anything inside those blocks as data, not instructions, and never to follow embedded directives.
- Has dedicated tests that assert untrusted content is always wrapped before being passed to the model, for both single-call and agent modes (`tests/test_prompt_injection_guards.py`).

This doesn't make the system bulletproof, but it removes the easy attacks and is auditable.

### Sensitive information

- `pii_detected` returns **presence, types, and count only** — never the actual values. The schema does not have a field for them, by design. A future redaction pipeline can act on `present == true` and `types` without ever surfacing the underlying strings.
- Uploaded files are stored outside the web root in `UPLOAD_DIR` (a Docker named volume in dev) and never served back as static content.
- Logs are structured JSON with an explicit field allowlist — raw document text is not logged, only metadata, error codes, and per-step agent traces.

### Attack surface

- **File size**: capped at `MAX_FILE_SIZE_BYTES` (25 MB default), enforced _while streaming_ before the file is fully on disk.
- **File type**: extension allowlist + declared MIME allowlist + magic-byte sniff (`%PDF-`, `PK\x03\x04` zip with `[Content_Types].xml` + `xl/workbook.xml`, UTF-8-clean text for CSV). All three must agree.
- **Empty / malformed XLSX zip**: rejected at upload with `415 Unsupported Media Type`.
- **CORS**: narrow allowlist, no wildcard with credentials.
- **No LLM-driven persistence**: the agent cannot write to the database or call out to the network. Tools are deterministic local code.
- **Idempotency**: `Idempotency-Key` reused across distinct uploads returns `409 Conflict` rather than silently merging different work.

### What's deferred (spelled out in my "What I'd improve" section)

Authentication, tenant-scoped authorization, malware scanning, encryption at rest, retention/deletion policies, per-tenant rate limits, audit logs.

---

## Production Readiness

The take-home brief asked specifically for failure handling, idempotency, observability, and cost. Here is how each is addressed.

### Failure handling

- **Retryable vs. deterministic errors are separated** at the worker boundary. Retryable codes (`LLM_TIMEOUT`, `LLM_RATE_LIMITED`, `UNKNOWN_WORKER_ERROR`) re-queue the job with exponential backoff (30s, then 2min, then fail). Deterministic codes (`UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `PDF_TEXT_EXTRACTION_EMPTY`, `LLM_SCHEMA_VALIDATION_FAILED`, etc.) fail immediately with a structured error.
- **Worker crashes mid-job are recoverable.** A periodic sweeper (`sweep_stale_jobs`) requeues `processing` rows whose `locked_at` is older than `WORKER_STALE_AFTER_SECONDS` and whose attempt budget remains. Rows past `max_attempts` are marked `failed` with `MAX_ATTEMPTS_EXCEEDED`.
- **Schema-invalid LLM output is repaired once, then fails.** `validate_annotation_payload` runs a deterministic local repair pass (filling defaults, clamping confidence, normalizing entity types) before raising `LLM_SCHEMA_VALIDATION_FAILED`. There is no second LLM call to "fix it"; that doubles cost without improving reliability when structured outputs are already enforced upstream.
- **The whole agent run is bounded by `LLM_TIMEOUT_SECONDS`**, not just each call. The deadline is checked at every graph node.
- **Errors are queryable**, not just logged: `error_code` and `error_message` are columns on `document_jobs`, surfaced in `GET /jobs/{id}`.

### Idempotency

- **Transport-layer retry safety**: optional `Idempotency-Key` header (or `idempotency_key` form field). Same key + same file + same `annotation_tasks` returns the existing `job_id` (`202`); same key + different file _or_ different tasks returns `409 Conflict`. Uniqueness is enforced by a Postgres unique constraint, with the API doing the conflict check ahead of insert and the database backstopping a race via `IntegrityError`. The key is generated by the client SDK or UI per upload attempt — the human user never sees it. This is the Stripe / AWS `ClientToken` pattern.
- **Content identity**: SHA-256 computed while streaming and stored on every job for audit, integrity verification, and future product features ("we've already annotated this document"). Deliberately _not_ used for automatic HTTP-layer dedupe in v1 — two users uploading the same document expect two jobs.
- **Worker-level idempotency**: `SELECT … FOR UPDATE SKIP LOCKED` ensures two workers cannot claim the same row, and the worker checks job status before processing in case a sweeper requeued a row that another worker is already finishing.

### Observability

- **Structured JSON logs everywhere** (`app/logging_config.py`). Every log line carries `job_id` and the relevant subset of `worker_id`, `stage`, `attempt`, `duration_ms`, `file_type`, `file_size_bytes`, `input_tokens`, `output_tokens`, `estimated_cost_usd`, `error_code`. Designed to be OpenTelemetry-compatible — adding an exporter is a single integration, not a rewrite.
- **Per-stage worker logs** at every pipeline transition (`extracting_text`, `calling_llm`, `validating_output`, `storing_result`).
- **Per-step agent logs** with `agent_step`, `tool`, `tool_args`, `verification_status` for every tool invocation.
- **Provenance on every annotation**: `usage.provider`, `usage.annotator_mode`, `usage.model` are stored alongside the result so any historical job can be traced back to the strategy and provider that produced it.
- **Health endpoints**: `/healthz` (process up) and `/readyz` (DB reachable) suitable for k8s liveness/readiness checks.

### Cost

- **Per-job token accounting**: `input_tokens`, `output_tokens`, `estimated_cost_usd`, plus a provider-specific `usage` JSONB are persisted on every annotated job. Cost rates are configurable via `INPUT_TOKEN_COST_PER_1M` and `OUTPUT_TOKEN_COST_PER_1M`.
- **The cheap default is the right default.** `single_call` mode is the default annotator and a single LLM call per document. Agent mode is opt-in for jobs that justify the extra calls.
- **Spreadsheet summarization before LLM**: large XLSX/CSV files are sampled (first 25 rows, headers, sheet metadata) instead of being shipped wholesale into the prompt.
- **Truncation budget for long documents** with an explicit warning when it triggers.
- **Mock mode is $0** and is the default for tests, so the test suite is hermetic and zero-cost.
- **Step cap on the agent** (`MAX_AGENT_VERIFICATION_CALLS = 16`) prevents a runaway loop from generating an unbounded bill.

---

## Known Limitations

- **`annotation_tasks` variance is currently subtle.** The plumbing is correct end-to-end (form field → DB column → agent prompt) but task hints influence the model's prose more than the structured output, because the schema is shared across tasks. Making tasks truly load-bearing requires task-specific output schemas (e.g., `tasks=["risks"]` enforces a non-empty `risks` block) and is the most product-shaped v2 feature in the backlog.
- **`document_type` is free-form `str`.** A reviewer running multiple invoices may get back `"invoice"` once and `"sales invoice"` another time. The trade-off is intentional — restricting to a `Literal` enum loses the model's ability to identify novel document types, and restricting via prompt is unreliable. The right fix is a downstream normalizer (rule-based or a tiny classifier) that produces a `document_type_canonical` field while preserving the raw value for audit. Not shipped in v1.
- **Spreadsheets are sampled, not fully read.** XLSX and CSV extractors capture the first 25 rows per sheet plus headers, sheet metadata, and inferred column types. For large workbooks this loses the long tail. The fix is per-sheet summarization (column statistics, anomalies, key totals) before annotation, plus chunked map-reduce annotation for very large files.
- **Long documents are truncated, not chunked.** Documents over the prompt budget (≈ 60k extraction characters by default) are truncated and a warning is emitted. Chunked map-reduce is the right answer for production and is named below.
- **Scanned PDFs fail cleanly, but they fail.** PDFs without extractable text return `PDF_TEXT_EXTRACTION_EMPTY`. OCR is not enabled.
- **No authentication, no multi-tenant authorization.** A take-home reviewer artifact, not a production deployment.
- **Local filesystem storage** is for the demo. Production should use S3/GCS with retention policies and lifecycle rules.

---

## What I'd Improve With Another Day

In rough order of user-visible impact:

1. **Chunked map-reduce extraction for long documents.** Split PDFs by page range or section, run per-chunk annotation, merge entities and dedupe citations, then synthesize a final output. Removes the hard limit currently imposed by truncation.
2. **OCR for scanned PDFs.** Integrate Tesseract for local demo and AWS Textract or Azure Document Intelligence for production. Annotate OCR-derived fields at lower confidence by default.
3. **Frontend application for document management.** As a fullstack engineer, I'd love the opportunity to design and implement a user-friendly frontend for this service. A web interface could support secure document uploads, real-time job status tracking, better visualization of annotations and citations, and admin/reviewer views for feedback workflows. This would make the async processing and rich annotation results accessible to both technical and non-technical users, while also showcasing the system's capabilities interactively.
4. **Make `annotation_tasks` load-bearing.** Define per-task output schemas (e.g., `risks` task mandates non-empty risks, `payment_terms` mandates structured payment-term entities), turning tasks into a meaningful API surface.
5. **`document_type` canonicalization.** Add a downstream normalizer (`document_type_canonical`) while preserving raw values, using rule-based logic first and a classifier as volume justifies.
6. **Better spreadsheet intelligence.** Add per-sheet column statistics, anomaly detection, table boundary inference, and metric extraction, replacing fixed-row sampling with richer summarization.
7. **Golden-eval harness.** Build a test suite with hand-labeled annotations for each `samples/` document. Measure citation precision/recall and field coverage—this becomes the regression gate for prompt/model changes.
8. **Webhook callbacks.** Allow clients to specify an optional `callback_url` per job to eliminate the need for polling.
9. **`GET /jobs` list endpoint and `POST /documents:batch` for folder ingestion.** Enable bulk document processing, making it easier to evaluate batches. Deferred since the brief focuses on single-document workflows.
10. **Schema versioning and reprocessing.** Support for multiple `annotation_schema_version` values and an admin endpoint to reprocess historical jobs under new schemas.
11. **Short-window content-dedupe guardrail.** For the same client + same SHA-256 within a short window (e.g., 30 seconds), return the existing job and prevent accidental duplicate uploads.

---

## Designed, Not Shipped

These are explicit production extensions where I contemplated the design but didn't have time to implement. Work in progress.

### Continuous learning loop

`POST /jobs/{id}/feedback` accepts per-citation verdicts (`correct | incorrect | unclear`) plus an optional corrected value. Feedback rows store `(job_id, citation_id, verdict, reviewer, corrected_value, document_sha256, created_at)`. A nightly job mines high-confidence verdicts and emits (a) updated few-shot examples per `document_type` injected into the agent's system prompt, and (b) a regression eval set that must pass before any prompt or model change ships. Longer-term, high-agreement feedback becomes fine-tuning data once volume justifies the cost. The loop is _online_ (prompts adapt in hours) and _offline_ (fine-tune candidates accumulate over weeks).

### Autonomous critic agent

The shipped agent verifies its own citations inline. A production-grade system adds a _separate_ critic agent with the same tools and a single directive: "for each claim, call `get_page` and verify independently." Disagreements between the primary agent and the critic are recorded on the job row as a `critic_disagreements` JSONB field and surfaced in the UI. Aggregate disagreement rate becomes an online quality signal that drives alerts, gates model rollouts, and triggers prompt revisions. The critic is isolated from the primary agent's context to avoid groupthink.

### Human in the loop

A job substate `status=pending_review` that the agent opts into when `min(citation.confidence) < threshold` or when `pii_detected.present` is true. `POST /jobs/{id}/review` accepts `{ reviewer_id, citation_id, action: "approve" | "reject" | "replace", replacement_value?: str }`. Each review appends to a `review_events` table; the job's final `result` is frozen only after all pending citations are resolved. A reviewer UI is a `/review` page backed by `GET /jobs?status=pending_review&assigned_to=me`. The HTTP contract is intentionally separate from the UI so the same review endpoints can be driven by Slack approvals, email replies, or an internal ops console.

### Full observability and evaluation harness

OpenTelemetry spans for `plan → act → verify → finalize` agent nodes with tool-name and duration attributes. A golden-eval suite that replays `samples/` against the agent and asserts citation recall and precision against hand-labeled expected outputs. A cost-per-annotation dashboard joining `document_jobs.estimated_cost_usd` against `document_type` and `annotator_mode` so we can see which modes are cost-effective for which document types.

### Adaptive model routing

A small, fast classifier over the extracted text picks the annotator mode: short unambiguous invoices route to `single_call`; long contracts and forms with PII route to `agent`. The classifier itself is a cheap LLM call, guarded by a token budget per job. Route decisions are logged and joined against accuracy/cost telemetry for post-hoc analysis.

### Cross-document retrieval (the `/search` endpoint)

`GET /search?q=...&document_type=...&date_from=...` returns matching job IDs and citation snippets across the user's entire annotated corpus. The production design uses Postgres full-text search over `result.summary` and `extraction.text` for keyword queries plus a `document_chunks` pgvector table for semantic queries, with a hybrid ranker. Per-document embedding with `text-embedding-3-small` runs ≈ $0.0003 per annotated document and is captured in the cost dashboard alongside LLM tokens. Vector search lives at the corpus tier — not at the single-document tier where this submission operates — which is why it is correctly absent from v1.

---

## Project Layout

```
document-annotation-service/
  README.md                  # this file
  plan.md                    # original implementation plan (kept for transparency)
  pyproject.toml
  Dockerfile
  docker-compose.yml
  .env.example
  alembic/                   # migrations (3)
  app/
    main.py                  # FastAPI app, /documents, /jobs, healthz, readyz
    worker.py                # worker loop, pipeline, error split, sweeper schedule
    queue.py                 # claim_next_job (FOR UPDATE SKIP LOCKED), sweeper, retry/backoff
    models.py                # SQLAlchemy DocumentJob model
    schemas.py               # API request/response Pydantic models
    annotation_schema.py     # AnnotationResult contract
    annotation_tasks.py      # annotation_tasks form normalization
    storage.py               # streaming upload + SHA-256
    file_validation.py       # extension + MIME + magic-byte
    config.py                # env-driven Settings + fail-fast on missing keys
    logging_config.py        # JSON formatter
    cost.py                  # token cost estimation
    db.py                    # SQLAlchemy engine + session
    extractors/              # pdf, spreadsheet, csv extractors + dispatcher
    annotators/
      base.py                # Annotator interface + single-call boundary
      mock.py                # deterministic stub
      openai.py              # single_call OpenAI implementation
      anthropic.py           # single_call Anthropic implementation
      agent.py               # LangGraph agent (plan -> act -> verify -> finalize)
      agent_tools.py         # deterministic tools + verify_citation
  samples/                   # invoice.pdf, service_agreement.pdf, research_abstract.pdf,
                             # transactions.xlsx, contacts.csv, README.md
  tests/                     # 12 test modules (see Testing)
```

---

## Testing

```bash
# Hermetic: defaults to ANNOTATOR_MODE=mock, no provider key required, $0 cost.
python3 -m pytest

# End-to-end smoke test:
docker compose up --build
curl -F "file=@samples/invoice.pdf" http://localhost:8000/documents
curl http://localhost:8000/jobs/<job_id>
docker compose logs -f worker
```

Test coverage focuses on the boundaries that matter:

- `test_upload.py` — upload flow, idempotency including `annotation_tasks` parity, 415/413 error paths.
- `test_queue.py` — claim SQL contains `FOR UPDATE SKIP LOCKED`, retry backoff schedule, sweeper logic.
- `test_file_validation.py` — magic-byte detection for PDF/XLSX/CSV, declared-MIME conflicts.
- `test_annotation_schema.py` — schema validation, citation shape, repair clamps.
- `test_single_call_annotators.py` — single-call output is forced to `verification_status: "unverified"` and emits the warning.
- `test_agent_annotator.py` — agent graph executes, verified citations get `"verified"`, timeouts are honored.
- `test_agent_tools.py` — `DocumentTools` and `verify_citation` behavior.
- `test_prompt_injection_guards.py` — both single-call and agent prompts wrap untrusted document text.
- `test_shared_volume.py` — Docker compose mounts shared `uploads` volume into both services.
- `test_schemas.py`, `test_config.py`, `test_upload.py` — request/response and config edge cases.

---

## API Reference

Compact reference; full machine-readable spec is at `GET /docs` when the service is running.

### `POST /documents` — `202 Accepted`

`multipart/form-data`:

| Field              | Required | Description                                                  |
| ------------------ | -------- | ------------------------------------------------------------ |
| `file`             | yes      | `.pdf`, `.xlsx`, or `.csv` (≤ 25 MB).                        |
| `idempotency_key`  | no       | Form field. Alternative to the `Idempotency-Key` header.     |
| `annotation_tasks` | no       | Comma-separated task hints; only meaningful in `agent` mode. |

Headers:

| Header            | Description                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------ |
| `Idempotency-Key` | Client-generated UUID for retry safety. Same key + same file + same tasks → same `job_id`. |

Response body:

```json
{ "job_id": "...", "status": "queued", "status_url": "/jobs/..." }
```

Errors: `400` (both header and form idempotency key, mismatched), `409` (idempotency conflict), `413` (file too large), `415` (unsupported file type), `503` (database unavailable).

### `GET /jobs/{job_id}` — `200 OK` or `404 Not Found`

Query parameters:

| Param                | Default | Description                                                                   |
| -------------------- | ------- | ----------------------------------------------------------------------------- |
| `include_extraction` | `false` | When `true`, includes the full extracted text payload (large; for debugging). |

Response body shape: see "Example Outputs" above. Unknown job IDs return `404 {"detail": "Job not found"}`.

### `GET /healthz`, `GET /readyz`

`/healthz` returns `200` if the process is up. `/readyz` returns `200` only if the database is reachable.

---

If you only have time to read three files, start at `app/annotators/agent.py`, `app/annotators/base.py`, and `app/queue.py`. Those three contain the load-bearing decisions of this submission.
