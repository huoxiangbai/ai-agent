from __future__ import annotations

from copy import deepcopy

from reactor_backend.contracts.models import JsonValue

_IGNORED = "<contract-ignored>"


def normalize_json(value: JsonValue, pointers: tuple[str, ...]) -> JsonValue:
    """Replace only explicitly allowlisted JSON-pointer locations.

    The extension token ``*`` applies the remainder of a pointer to every item
    in a mapping or list. Replacing instead of deleting preserves field presence,
    list length, and null/type comparisons around the ignored leaf.

    A pointer whose final key is absent is a no-op on purpose: one pointer list
    also declares additive fields (see :func:`drop_additive`), and an additive
    field is by definition missing from at least one side. Malformed pointers
    still raise so a broken allowlist cannot be mistaken for a working one.
    """

    normalized = deepcopy(value)
    for pointer in pointers:
        tokens = _parse_pointer(pointer)
        normalized = _replace(normalized, tokens)
    return normalized


def drop_additive(
    golden: JsonValue,
    candidate: JsonValue,
    pointers: tuple[str, ...],
) -> JsonValue:
    """Remove candidate-only leaves named by ``pointers``.

    Only the candidate side is rewritten, so a field present in the golden but
    missing from the candidate always stays a difference: removal is breaking
    and an allowlist never suppresses it. A leaf present on both sides is left
    alone here; its value tolerance is applied at capture time by
    :func:`normalize_json`.

    List elements are never deleted — a longer list is a length difference, not
    an additive field. Declare an additive object at the shallowest root that
    exists on both sides (``/data/extra`` for a whole new ``extra`` object).
    """

    result = deepcopy(candidate)
    for pointer in pointers:
        result = _drop(result, golden, _parse_pointer(pointer))
    return result


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
            return value
        if isinstance(value, list | tuple):
            return [_replace(item, tail) for item in value]
        if tail:
            raise ValueError(f"cannot descend into {type(value).__name__} with pointer token '*'")
        return value

    if isinstance(value, dict):
        if head in value:
            value[head] = _replace(value[head], tail)
        elif tail:
            raise ValueError(f"unresolvable JSON pointer segment: {head!r}")
        return value

    if isinstance(value, list | tuple):
        index = _list_index(head, len(value))
        items = list(value)
        items[index] = _replace(items[index], tail)
        return items

    raise ValueError(f"cannot descend into {type(value).__name__} with pointer token {head!r}")


def _drop(candidate: JsonValue, golden: JsonValue, tokens: tuple[str, ...]) -> JsonValue:
    if not tokens:
        return candidate

    head, *tail_list = tokens
    tail = tuple(tail_list)

    if head == "*":
        if isinstance(candidate, dict):
            golden_map: dict[str, JsonValue] = golden if isinstance(golden, dict) else {}
            for key in list(candidate):
                if not tail:
                    if key not in golden_map:
                        del candidate[key]
                    continue
                candidate[key] = _drop(
                    candidate[key],
                    golden_map[key] if key in golden_map else None,
                    tail,
                )
            return candidate
        if isinstance(candidate, list | tuple):
            golden_list: list[JsonValue] = (
                list(golden) if isinstance(golden, list | tuple) else []
            )
            items = list(candidate)
            for index, item in enumerate(items):
                if not tail:
                    # List length is contract data: never delete elements.
                    continue
                items[index] = _drop(
                    item,
                    golden_list[index] if index < len(golden_list) else None,
                    tail,
                )
            return items
        return candidate

    if isinstance(candidate, dict):
        golden_map = golden if isinstance(golden, dict) else {}
        if head not in candidate:
            return candidate
        if not tail:
            if head not in golden_map:
                del candidate[head]
            return candidate
        candidate[head] = _drop(
            candidate[head],
            golden_map[head] if head in golden_map else None,
            tail,
        )
        return candidate

    if isinstance(candidate, list | tuple):
        index = _list_index(head, len(candidate))
        golden_list = list(golden) if isinstance(golden, list | tuple) else []
        items = list(candidate)
        items[index] = _drop(
            items[index],
            golden_list[index] if index < len(golden_list) else None,
            tail,
        )
        return items

    raise ValueError(f"cannot descend into {type(candidate).__name__} with pointer token {head!r}")


def _list_index(token: str, length: int) -> int:
    try:
        index = int(token)
    except ValueError as exc:
        raise ValueError(f"list index token must be an integer: {token!r}") from exc
    if not 0 <= index < length:
        raise ValueError(f"list index out of range: {token!r}")
    return index
