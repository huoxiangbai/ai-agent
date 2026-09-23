"""GenUI tree / patch normalization and validation.

Ported from ``org.wwz.ai.domain.agent.runtime.tool.common.canvas.GenUiSchema``
and the ``GenUiCatalog.ALLOWED_KINDS`` whitelist. Input boundary only — this
module never persists canvas state nor applies JSON Patch.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_MAX_DEPTH = 24
DEFAULT_MAX_NODES = 200

NODE_KEYS = frozenset({"nodeId", "kind", "props", "children", "type"})
PATCH_OPS = frozenset({"add", "replace", "remove"})

# ``GenUiCatalog.ALLOWED_KINDS`` — the catalog's kind column, verbatim.
ALLOWED_KINDS = frozenset(
    {
        "AspectBox",
        "Skeleton",
        "Stat",
        "Progress",
        "Avatar",
        "Image",
        "Video",
        "Model3D",
        "LiveCamera",
        "Icon",
        "Table",
        "TableRow",
        "TableCell",
        "List",
        "ListItem",
        "CodeBlock",
        "Chart",
        "ParametricLab",
        "PythagorasLab",
        "GeometryLab",
        "InteractiveLab",
        "ConceptDemo",
        "AnimStepLab",
        "KnowledgeDemo",
        "BindScope",
        "ReactiveScope",
        "Quiz",
        "WorkedExample",
        "BeforeAfter",
        "CompareSlider",
        "NumberLine",
        "CoordinateGrid",
        "Card",
        "WeatherCard",
        "DataCard",
        "MetricCard",
        "ProfileCard",
        "MediaCard",
        "AlertCard",
        "TimelineCard",
        "SlideDeck",
        "Slide",
        "KpiBoard",
        "FeatureGrid",
        "Stepper",
        "QuoteCard",
        "ImageGallery",
        "KeyValueList",
        "SectionHeader",
        "Button",
        "InteractiveButton",
        "ToggleButton",
        "LinkButton",
        "Input",
        "Select",
        "Chip",
        "ChipGroup",
        "Form",
        "NumberInput",
        "Switch",
        "Slider",
        "FileInput",
        "Textarea",
        "HostedCanvasFrame",
        "HtmlFrame",
        "ThreeJsFrame",
        "JsonDebug",
    }
)


class GenUiSchemaError(ValueError):
    """Java ``IllegalArgumentException`` from the GenUI input boundary."""


def is_allowed_kind(kind: str | None) -> bool:
    return kind is not None and kind in ALLOWED_KINDS


def string_val(value: Any) -> str | None:
    """Java ``stringVal``: ``null`` in, ``null`` out; otherwise trimmed ``String.valueOf``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def cast_map(raw: Mapping[Any, Any]) -> dict[str, Any]:
    """Stringify keys, drop null keys, preserve insertion order."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key is not None:
            out[str(key)] = value
    return out


def validate_ui_tree(
    raw: Any,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise GenUiSchemaError("tree must be an object")
    tree = cast_map(raw)
    envelope = _normalize_envelope(tree)
    root_obj = envelope.get("root")
    if not isinstance(root_obj, Mapping):
        raise GenUiSchemaError("root must be an object")
    root = _normalize_node(cast_map(root_obj))
    # Overwrite in place keeps ``schemaVersion, root`` key order.
    envelope["root"] = root
    total, depth = _count_nodes_depth(root, 1)
    if depth > max_depth:
        raise GenUiSchemaError(f"tree depth {depth} exceeds max {max_depth}")
    if total > max_nodes:
        raise GenUiSchemaError(f"tree node count {total} exceeds max {max_nodes}")
    return envelope


def validate_ui_patch(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise GenUiSchemaError("patch payload must be an object")
    payload = cast_map(raw)
    patches = payload.get("patches")
    if not isinstance(patches, Sequence) or isinstance(patches, (str, bytes)):
        raise GenUiSchemaError("patches must be a non-empty array")
    if len(patches) == 0:
        raise GenUiSchemaError("patches must be a non-empty array")
    if len(patches) > 200:
        raise GenUiSchemaError("patches exceeds max 200")
    normalized: list[dict[str, Any]] = []
    for item in patches:
        if not isinstance(item, Mapping):
            raise GenUiSchemaError("each patch must be an object")
        patch = cast_map(item)
        op = string_val(patch.get("op"))
        path = string_val(patch.get("path"))
        if op not in PATCH_OPS:
            raise GenUiSchemaError("patch.op must be add|replace|remove")
        if path is None or not path.startswith("/"):
            raise GenUiSchemaError(
                "patch.path must be an RFC6901 pointer starting with /"
            )
        out: dict[str, Any] = {"op": op, "path": path}
        if op != "remove":
            if "value" not in patch:
                raise GenUiSchemaError(f"patch.value required for op={op}")
            out["value"] = patch["value"]
        normalized.append(out)
    result: dict[str, Any] = {"patches": normalized}
    if payload.get("canvas_id") is not None:
        result["canvas_id"] = str(payload["canvas_id"])
    if payload.get("seq") is not None:
        result["seq"] = payload["seq"]
    return result


def _normalize_envelope(tree: dict[str, Any]) -> dict[str, Any]:
    # Accepts {tree:{...}, canvas_id?}, {schemaVersion, root} / {root}, or a bare root.
    nested = tree.get("tree")
    if isinstance(nested, Mapping) and all(k in ("tree", "canvas_id") for k in tree):
        return _normalize_envelope(cast_map(nested))
    if "root" in tree or "schemaVersion" in tree:
        root = tree.get("root")
        if not isinstance(root, Mapping):
            raise GenUiSchemaError("envelope requires root object")
        return {"schemaVersion": "1", "root": cast_map(root)}
    if "kind" in tree or "type" in tree:
        return {"schemaVersion": "1", "root": tree}
    raise GenUiSchemaError(
        "invalid tree envelope; expected {schemaVersion,root} or bare root"
    )


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    kind = string_val(node.get("kind"))
    if kind is None:
        kind = string_val(node.get("type"))
    if kind is None:
        raise GenUiSchemaError("node.kind is required")
    if not is_allowed_kind(kind):
        raise GenUiSchemaError(
            f"unsupported kind: {kind}; call list_ui_components"
        )
    node_id = string_val(node.get("nodeId"))
    if node_id is None:
        # Java mints "n_" + first 12 hex of a fresh UUID — non-deterministic.
        node_id = "n_" + uuid.uuid4().hex[:12]
    out: dict[str, Any] = {"nodeId": node_id, "kind": kind}

    props: dict[str, Any] = {}
    raw_props = node.get("props")
    if isinstance(raw_props, Mapping):
        props.update(cast_map(raw_props))
    # Models often lift props onto the node top level; hoist them without
    # clobbering the reserved keys.
    for key, value in node.items():
        if key in NODE_KEYS:
            continue
        props.setdefault(key, value)
    _lift_alias(props, "text", "value")
    _lift_alias(props, "title", "value")
    _lift_alias(props, "content", "value")
    _lift_alias(props, "label", "value")
    _lift_alias(props, "url", "src")
    _lift_alias(props, "imageUrl", "src")
    _lift_alias(props, "href", "url")
    out["props"] = props

    children: list[dict[str, Any]] = []
    raw_children = node.get("children")
    if isinstance(raw_children, Sequence) and not isinstance(
        raw_children, (str, bytes)
    ):
        for child in raw_children:
            if isinstance(child, Mapping):
                children.append(_normalize_node(cast_map(child)))
            elif child is not None:
                raise GenUiSchemaError(
                    "children must be node objects, not primitives"
                )
    out["children"] = children
    return out


def _lift_alias(props: dict[str, Any], from_key: str, to_key: str) -> None:
    if to_key not in props and from_key in props:
        props[to_key] = props[from_key]


def _count_nodes_depth(node: Mapping[str, Any], depth: int) -> tuple[int, int]:
    total = 1
    max_depth = depth
    children = node.get("children")
    if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
        for child in children:
            if isinstance(child, Mapping):
                sub_total, sub_depth = _count_nodes_depth(child, depth + 1)
                total += sub_total
                max_depth = max(max_depth, sub_depth)
    return total, max_depth


def dumps(value: Any) -> str:
    """fastjson-compatible compact JSON (used by callers needing text)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
