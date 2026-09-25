"""Jackson-compatible body coercion.

The shapes here are what Spring's default ``ObjectMapper`` does to the admin
POJOs. Anything Pydantic would turn into a 422 + ``{"detail": ...}`` is a drift
these pins are here to prevent.
"""

from __future__ import annotations

import pytest

from reactor_backend.api.body_coercion import (
    BodyError,
    coerce_body_optional_int,
    coerce_body_primitive_int,
    coerce_body_string,
    coerce_body_string_list,
    parse_json_object,
)


def test_parse_rejects_missing_empty_and_malformed_as_400() -> None:
    for raw in (b"", b"   ", b"not json", b"{", b"[1,2]", b'"str"', b"123", b"true"):
        with pytest.raises(BodyError) as raised:
            parse_json_object(raw)
        assert raised.value.status_code == 400, raw


def test_parse_maps_json_null_to_500() -> None:
    # A present ``null`` token is a present body: Jackson returns Java null and
    # ``toCommand(null)`` NPEs inside a controller with no try/catch.
    with pytest.raises(BodyError) as raised:
        parse_json_object(b"null")
    assert raised.value.status_code == 500


def test_parse_returns_object() -> None:
    assert parse_json_object(b'{"a":1}') == {"a": 1}
    assert parse_json_object(b"{}") == {}


def test_string_fields_are_not_trimmed() -> None:
    assert coerce_body_string("  s1  ", "sessionId") == "  s1  "
    assert coerce_body_string(None, "sessionId") is None


def test_string_fields_accept_scalar_coercion() -> None:
    # Jackson's String codec: String.valueOf on numbers/booleans.
    assert coerce_body_string(123, "title") == "123"
    assert coerce_body_string(True, "title") == "true"
    assert coerce_body_string(False, "title") == "false"
    assert coerce_body_string(1.5, "title") == "1.5"


def test_string_fields_reject_structured_values() -> None:
    for value in (["a"], {"k": 1}):
        with pytest.raises(BodyError) as raised:
            coerce_body_string(value, "title")
        assert raised.value.status_code == 400


def test_boxed_integer_null_stays_null() -> None:
    # ``Integer sortOrder``: JSON null -> Java null (then sortOrder null -> 0 in the
    # repository adapter). Distinct from the primitive case below.
    assert coerce_body_optional_int(None, "sortOrder") is None
    assert coerce_body_optional_int(0, "sortOrder") == 0
    assert coerce_body_optional_int(-3, "sortOrder") == -3


def test_primitive_integer_null_is_zero() -> None:
    # ``int pageNo``: FAIL_ON_NULL_FOR_PRIMITIVES is off, so JSON null -> 0.
    assert coerce_body_primitive_int(None, "pageNo") == 0
    assert coerce_body_primitive_int(5, "pageNo") == 5


def test_integer_coercion_matches_jackson_scalars() -> None:
    assert coerce_body_optional_int("7", "sortOrder") == 7
    assert coerce_body_optional_int(" 7 ", "sortOrder") == 7
    assert coerce_body_optional_int("+7", "sortOrder") == 7
    assert coerce_body_optional_int(True, "sortOrder") == 1
    assert coerce_body_optional_int(False, "sortOrder") == 0
    # ACCEPT_FLOAT_AS_INT is on: whole floats coerce, fractional floats fail.
    assert coerce_body_optional_int(2.0, "sortOrder") == 2
    for bad in (2.5, "abc", "", "   ", "0x10", ["1"], {"k": 1}):
        with pytest.raises(BodyError):
            coerce_body_optional_int(bad, "sortOrder")


def test_integer_range_is_java_int() -> None:
    assert coerce_body_optional_int(2147483647, "sortOrder") == 2147483647
    assert coerce_body_optional_int(-2147483648, "sortOrder") == -2147483648
    for bad in (2147483648, -2147483649):
        with pytest.raises(BodyError):
            coerce_body_optional_int(bad, "sortOrder")


def test_string_list_coerces_elements_and_keeps_nulls() -> None:
    assert coerce_body_string_list(None, "tags") is None
    assert coerce_body_string_list([], "tags") == []
    assert coerce_body_string_list(["a", None, 3], "tags") == ["a", None, "3"]


def test_string_list_rejects_non_arrays_and_bad_elements() -> None:
    with pytest.raises(BodyError):
        coerce_body_string_list("a", "tags")
    with pytest.raises(BodyError):
        coerce_body_string_list(["ok", {"k": 1}], "tags")
