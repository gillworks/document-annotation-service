from typing import Any


def normalize_annotation_tasks(value: str | None) -> list[str]:
    if not value:
        return []
    return [task for task in (part.strip() for part in value.split(",")) if task]


def same_annotation_tasks(job: Any, annotation_tasks: list[str]) -> bool:
    return list(getattr(job, "annotation_tasks", None) or []) == annotation_tasks
