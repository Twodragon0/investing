import time
from typing import Any, Dict, Optional


def _format_extras(extras: Optional[Dict[str, Any]]) -> str:
    if not extras:
        return ""

    fields = []
    for key in sorted(extras.keys()):
        value = extras[key]
        fields.append(f"{key}={value}")
    return " " + " ".join(fields)


def log_collection_summary(
    logger: Any,
    collector: str,
    source_count: int,
    unique_items: int,
    post_created: int,
    started_at: float,
    extras: Optional[Dict[str, Any]] = None,
) -> None:
    duration = max(0.0, time.monotonic() - started_at)
    extra_fields = _format_extras(extras)
    logger.info(
        "collection-summary collector=%s source_count=%d unique_items=%d post_created=%d duration=%.2fs%s",
        collector,
        max(0, source_count),
        max(0, unique_items),
        max(0, post_created),
        duration,
        extra_fields,
    )
