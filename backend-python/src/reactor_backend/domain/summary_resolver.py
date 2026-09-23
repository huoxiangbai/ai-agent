"""Summary replay result resolver.

Ported from ``SummaryReplayResultResolver``. The ledger stores the final answer
verbatim (including the ``$$$`` artifact call-out section); replay must not strip
it. ``fileList``/``artifactRefs`` are always empty — the frontend maps files from
the session file table instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reactor_backend.domain.execution_ledger_constants import (
    ARTIFACT_DELIMITER,
    ARTIFACT_KEY_SEPARATOR_REGEX,
)

_SPLIT_PATTERN = re.compile(ARTIFACT_KEY_SEPARATOR_REGEX)


@dataclass(frozen=True)
class ResolvedSummary:
    summary_text: str
    file_list: list[dict[str, object]] = field(default_factory=list)
    artifact_refs: list[dict[str, object]] = field(default_factory=list)
    artifact_keys: list[str] = field(default_factory=list)


def resolve(raw_summary_text: str | None) -> ResolvedSummary:
    raw = raw_summary_text if raw_summary_text is not None else ""
    parts = raw.split(ARTIFACT_DELIMITER, 1)
    requested_keys = _split_artifact_items(parts[1]) if len(parts) == 2 else []
    return ResolvedSummary(
        summary_text=raw,
        file_list=[],
        artifact_refs=[],
        artifact_keys=requested_keys,
    )


def _split_artifact_items(artifact_section: str) -> list[str]:
    if artifact_section is None or artifact_section.strip() == "":
        return []
    result: list[str] = []
    for part in _SPLIT_PATTERN.split(artifact_section):
        trimmed = part.strip()
        if trimmed:
            result.append(trimmed)
    return result
