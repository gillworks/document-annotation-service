import logging
import time
from typing import Any

from anthropic import Anthropic
from anthropic import APITimeoutError as AnthropicTimeoutError
from anthropic import RateLimitError as AnthropicRateLimitError
from openai import OpenAI
from openai import APITimeoutError as OpenAITimeoutError
from openai import RateLimitError as OpenAIRateLimitError

from app.annotation_schema import AnnotationResult
from app.annotators.agent_tools import DocumentTools, verify_citation
from app.annotators.anthropic import TOOL_NAME as ANTHROPIC_TOOL_NAME
from app.annotators.anthropic import first_tool_payload, response_usage as anthropic_response_usage
from app.annotators.base import (
    MAX_PROMPT_TEXT_CHARS,
    UNTRUSTED_CONTENT_INSTRUCTION,
    Annotation,
    AnnotationError,
    Annotator,
    format_annotation_tasks,
    render_untrusted_block,
    validate_annotation_payload,
)
from app.config import Settings
from app.models import DocumentJob

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - exercised only when optional dependency is absent locally.
    END = "__end__"
    StateGraph = None


logger = logging.getLogger(__name__)
MAX_AGENT_VERIFICATION_CALLS = 16
MAX_AGENT_TOOL_CALLS = MAX_AGENT_VERIFICATION_CALLS


class AgentAnnotator(Annotator):
    def __init__(self, settings: Settings) -> None:
        if StateGraph is None:
            raise AnnotationError(
                "UNKNOWN_WORKER_ERROR",
                "ANNOTATOR_MODE=agent requires langgraph to be installed.",
            )
        self.settings = settings
        if settings.annotator_provider == "anthropic":
            self.client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds)
        else:
            self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)
        self.graph = self._build_graph()

    def annotate(self, job: DocumentJob, extraction: dict[str, Any]) -> Annotation:
        state = {
            "job": job,
            "extraction": extraction,
            "tools": DocumentTools(extraction),
            "annotation_tasks": list(getattr(job, "annotation_tasks", None) or []),
            "deadline": time.monotonic() + self.settings.llm_timeout_seconds,
            "agent_step": 0,
            "tool_calls": 0,
            "context": "",
            "context_truncated": False,
            "draft": None,
            "result": None,
            "usage": {},
        }
        final_state = self.graph.invoke(state)
        result = final_state.get("result")
        if result is None:
            raise AnnotationError("LLM_SCHEMA_VALIDATION_FAILED", "Agent did not produce an annotation result.")

        usage = dict(final_state.get("usage") or {})
        return Annotation(
            result=result,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            usage={
                "provider": self.settings.annotator_provider,
                "annotator_mode": "agent",
                "model": self.settings.annotator_model,
                "agent_tool_calls": final_state.get("tool_calls", 0),
                "agent_verification_calls": final_state.get("tool_calls", 0),
                "agent_context_chars": len(final_state.get("context") or ""),
                "agent_context_truncated": bool(final_state.get("context_truncated", False)),
                **usage,
            },
        )

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("plan", self._plan)
        graph.add_node("act", self._act)
        graph.add_node("verify", self._verify)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("plan")
        graph.add_edge("plan", "act")
        graph.add_edge("act", "verify")
        graph.add_edge("verify", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _plan(self, state: dict[str, Any]) -> dict[str, Any]:
        self._check_deadline(state)
        context, truncated = build_document_context(state["extraction"])
        state["context"] = context
        state["context_truncated"] = truncated
        return state

    def _act(self, state: dict[str, Any]) -> dict[str, Any]:
        self._check_deadline(state)
        tools: DocumentTools = state["tools"]
        state["draft"], state["usage"] = self._create_cited_draft(state, tools)
        return state

    def _verify(self, state: dict[str, Any]) -> dict[str, Any]:
        self._check_deadline(state)
        draft: AnnotationResult = state["draft"]
        payload = draft.model_dump(mode="json")
        tools: DocumentTools = state["tools"]

        for item in citation_bearing_items(payload):
            verified_citations = []
            for citation in list(item.get("citations") or []):
                if state["tool_calls"] >= MAX_AGENT_VERIFICATION_CALLS:
                    citation["verification_status"] = "unverified"
                    verified_citations.append(citation)
                    continue

                started_at = time.monotonic()
                state["tool_calls"] += 1
                checked = verify_citation(citation, tools)
                self._log_agent_step(
                    state,
                    tool=verification_tool_name(citation),
                    args=verification_args(citation),
                    duration_ms=duration_ms(started_at),
                    verification_status=checked.get("verification_status"),
                )
                verified_citations.append(checked)
            item["citations"] = verified_citations

        state["result"] = validate_annotation_payload(payload)
        return state

    def _finalize(self, state: dict[str, Any]) -> dict[str, Any]:
        self._check_deadline(state)
        if state.get("result") is None:
            state["result"] = validate_annotation_payload(state["draft"].model_dump(mode="json"))
        return state

    def _create_cited_draft(self, state: dict[str, Any], tools: DocumentTools) -> tuple[AnnotationResult, dict[str, int]]:
        self._check_deadline(state)
        job = state["job"]
        messages = build_agent_messages(
            job=job,
            extraction=state["extraction"],
            annotation_tasks=state["annotation_tasks"],
            context=state["context"],
            context_truncated=state["context_truncated"],
            sections=tools.list_sections(),
        )
        if self.settings.annotator_provider == "anthropic":
            return self._create_anthropic_cited_draft(state, messages)
        return self._create_openai_cited_draft(state, messages)

    def _create_openai_cited_draft(
        self, state: dict[str, Any], messages: list[dict[str, str]]
    ) -> tuple[AnnotationResult, dict[str, int]]:
        try:
            response = self.client.responses.parse(
                model=self.settings.annotator_model,
                input=messages,
                text_format=AnnotationResult,
                timeout=max(self._remaining_timeout(state), 1.0),
            )
        except OpenAITimeoutError as exc:
            raise AnnotationError("LLM_TIMEOUT", f"OpenAI agent annotation timed out: {exc}") from exc
        except OpenAIRateLimitError as exc:
            raise AnnotationError("LLM_RATE_LIMITED", f"OpenAI agent rate limit hit: {exc}") from exc
        except Exception as exc:
            raise AnnotationError("UNKNOWN_WORKER_ERROR", f"OpenAI agent annotation failed: {exc}") from exc

        if response.output_parsed is None:
            raise AnnotationError("LLM_SCHEMA_VALIDATION_FAILED", "OpenAI agent response did not include parsed output.")
        return validate_annotation_payload(response.output_parsed.model_dump(mode="json")), openai_response_usage(response)

    def _create_anthropic_cited_draft(
        self, state: dict[str, Any], messages: list[dict[str, str]]
    ) -> tuple[AnnotationResult, dict[str, int]]:
        try:
            response = self.client.messages.create(
                model=self.settings.annotator_model,
                max_tokens=2400,
                system=messages[0]["content"],
                messages=[{"role": "user", "content": messages[1]["content"]}],
                tools=[
                    {
                        "name": ANTHROPIC_TOOL_NAME,
                        "description": "Record the grounded structured document annotation.",
                        "input_schema": AnnotationResult.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": ANTHROPIC_TOOL_NAME},
                timeout=max(self._remaining_timeout(state), 1.0),
            )
        except AnthropicTimeoutError as exc:
            raise AnnotationError("LLM_TIMEOUT", f"Anthropic agent annotation timed out: {exc}") from exc
        except AnthropicRateLimitError as exc:
            raise AnnotationError("LLM_RATE_LIMITED", f"Anthropic agent rate limit hit: {exc}") from exc
        except Exception as exc:
            raise AnnotationError("UNKNOWN_WORKER_ERROR", f"Anthropic agent annotation failed: {exc}") from exc

        return validate_annotation_payload(first_tool_payload(response)), anthropic_response_usage(response)

    def _log_agent_step(
        self,
        state: dict[str, Any],
        *,
        tool: str,
        args: dict[str, Any],
        duration_ms: int,
        verification_status: str | None = None,
    ) -> None:
        state["agent_step"] += 1
        payload = {
            "job_id": str(state["job"].id),
            "agent_step": state["agent_step"],
            "tool": tool,
            "tool_args": args,
            "duration_ms": duration_ms,
        }
        if verification_status:
            payload["verification_status"] = verification_status
        logger.info("agent tool step", extra=payload)

    def _check_deadline(self, state: dict[str, Any]) -> None:
        if self._remaining_timeout(state) <= 0:
            raise AnnotationError("LLM_TIMEOUT", "Agent run exceeded LLM_TIMEOUT_SECONDS.")

    def _remaining_timeout(self, state: dict[str, Any]) -> float:
        return float(state["deadline"] - time.monotonic())


def build_agent_messages(
    *,
    job: DocumentJob,
    extraction: dict[str, Any],
    annotation_tasks: list[str],
    context: str,
    context_truncated: bool,
    sections: list[str],
) -> list[dict[str, str]]:
    metadata = extraction.get("metadata") or {}
    tasks = format_annotation_tasks(annotation_tasks)
    system = (
        "You are a grounded document annotation agent. Use only the provided source document context. "
        f"{UNTRUSTED_CONTENT_INSTRUCTION} "
        "Return a schema-valid annotation. Include citations only when the cited snippet appears verbatim "
        "in the source document context. Prefer concise exact snippets for entities, dates, risks, and "
        "action items. Do not include sensitive values in pii_detected."
    )
    truncation_note = (
        "The source document context was truncated to fit the annotation prompt."
        if context_truncated
        else "The full extracted source document context is included."
    )
    metadata_block = "\n".join(
        [
            f"Filename: {job.original_filename}",
            f"Detected content type: {job.detected_content_type}",
            f"Extraction metadata: {metadata}",
            f"Available sections: {sections}",
        ]
    )
    user = (
        f"{render_untrusted_block('FILE AND EXTRACTION METADATA', metadata_block)}\n\n"
        f"{render_untrusted_block('ANNOTATION TASK HINTS', tasks)}\n\n"
        f"{truncation_note}\n\n"
        f"{render_untrusted_block('SOURCE DOCUMENT CONTEXT', context)}\n\n"
        "Limit total citations to the strongest 8-12 snippets. "
        "Use page_number for PDF context and sheet_name for spreadsheet context."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_document_context(extraction: dict[str, Any]) -> tuple[str, bool]:
    text = str(extraction.get("text") or "")
    if len(text) <= MAX_PROMPT_TEXT_CHARS:
        return text, False
    return text[:MAX_PROMPT_TEXT_CHARS], True


def citation_bearing_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for key in ("key_entities", "important_dates", "action_items", "risks"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                items.append(item)
    return items


def verification_tool_name(citation: dict[str, Any]) -> str:
    if citation.get("page_number") is not None:
        return "get_page"
    if citation.get("sheet_name"):
        return "get_sheet_sample"
    return "source_text"


def verification_args(citation: dict[str, Any]) -> dict[str, Any]:
    if citation.get("page_number") is not None:
        return {"page_number": citation.get("page_number")}
    if citation.get("sheet_name"):
        return {"sheet_name": citation.get("sheet_name")}
    return {}


def duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def openai_response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    return {
        key: value
        for key, value in {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }.items()
        if value is not None
    }
