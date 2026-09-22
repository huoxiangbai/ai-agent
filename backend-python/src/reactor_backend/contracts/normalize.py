from __future__ import annotations

from copy import deepcopy

from reactor_backend.contracts.models import JsonValue

_IGNORED = "<contract-ignored>"


def normalize_json(value: JsonValue, pointers: tuple[str, ...]) -> JsonValue:
    """Replace only explicitly allowlisted JSON-pointer locations.

    The extension token ``*`` applies the remainder of a pointer to every item
    in a mapping or list. Replacing instead of deleting preserves field presence,
    list length, and null/type comparisons around the ignored leaf.
    """

    normalized = deepcopy(value)
    for pointer in pointers:
        tokens = _parse_pointer(pointer)
        normalized = _replace(normalized, tokens)
    return normalized


def _parse_pointer(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer}")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _replace(value: JsonValue, tokens: tuple[str, ...]) -> JsonValue:
    if not tokens:
        return _IGNORED

    head, *tail_list = tokens
    tail = tuple(tail_list)
    if head == "*":
        if isinstance(value, dict):
            for key in list(value):
                value[key] = _replace(value[key], tail)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                value[index] = _replace(item, tail)
        return value

    if isinstance(value, dict) and head in value:
        value[head] = _replace(value[head], tail)
    elif isinstance(value, list):
        try:
            index = int(head)
        except ValueError:
            return value
        if 0 <= index < len(value):
            value[index] = _replace(value[index], tail)
    return value
