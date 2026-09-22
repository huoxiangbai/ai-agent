from __future__ import annotations

import json
import os
import re
from pathlib import Path

from reactor_backend.contracts.models import HttpCase, JsonValue, NormalizationRules

_ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def load_cases(path: Path) -> tuple[list[HttpCase], list[str]]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError("contract manifest must contain a cases array")
    cases: list[HttpCase] = []
    skipped: list[str] = []
    for item in raw["cases"]:
        if not isinstance(item, dict):
            raise ValueError("each contract case must be an object")
        name = _required_string(item, "name")
        expanded, missing = _expand(item)
        if missing:
            skipped.append(f"{name}: missing {', '.join(sorted(missing))}")
            continue
        if not isinstance(expanded, dict):
            raise AssertionError("expanded case must remain an object")
        normalization = expanded.get("normalization", {})
        if not isinstance(normalization, dict):
            raise ValueError(f"{name}: normalization must be an object")
        cases.append(
            HttpCase(
                name=name,
                method=_required_string(expanded, "method").upper(),
                path=_required_string(expanded, "path"),
                query=_string_dict(expanded.get("query", {}), name, "query"),
                headers=_string_dict(expanded.get("headers", {}), name, "headers"),
                json_body=_json_value(expanded.get("json_body")),
                compared_headers=tuple(_string_list(expanded.get("compared_headers", []), name)),
                normalization=NormalizationRules(
                    ignored_json_pointers=tuple(
                        _string_list(normalization.get("ignored_json_pointers", []), name)
                    ),
                    ignored_cookie_values=tuple(
                        _string_list(normalization.get("ignored_cookie_values", []), name)
                    ),
                ),
            )
        )
    return cases, skipped


def _expand(value: object) -> tuple[object, set[str]]:
    missing: set[str] = set()
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            resolved = os.environ.get(key)
            if resolved is None:
                missing.add(key)
                return match.group(0)
            return resolved

        return _ENV_PATTERN.sub(replace, value), missing
    if isinstance(value, list):
        output: list[object] = []
        for item in value:
            expanded, child_missing = _expand(item)
            output.append(expanded)
            missing.update(child_missing)
        return output, missing
    if isinstance(value, dict):
        output_dict: dict[str, object] = {}
        for key, item in value.items():
            expanded, child_missing = _expand(item)
            output_dict[str(key)] = expanded
            missing.update(child_missing)
        return output_dict, missing
    return value, missing


def _required_string(value: dict[object, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"{key} must be a non-empty string")
    return result


def _string_dict(value: object, case: str, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError(f"{case}: {field} must contain string keys and values")
    return dict(value)


def _string_list(value: object, case: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{case}: expected a string array")
    return list(value)


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError("json_body contains a non-JSON value")
