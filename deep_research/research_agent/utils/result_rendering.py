from __future__ import annotations

import re
from typing import Annotated

import jsonschema
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from research_agent.targets import get_target_definition
from research_agent.utils.json_utils import robust_json_loads


def _coerce_integers(value: object, schema: dict) -> object:
    if isinstance(value, dict):
        props = schema.get('properties', {})
        return {k: _coerce_integers(v, props.get(k, {})) for k, v in value.items()}
    if isinstance(value, list):
        item_schema = schema.get('items', {})
        return [_coerce_integers(item, item_schema) for item in value]
    if schema.get("type") == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _resolve_path(path: str, context: dict[str, object]):
    if path == "item":
        return context.get("item")
    target = context["root"]
    if path.startswith("item."):
        target = context.get("item", {})
        path = path[5:]
    elif path.startswith("root."):
        path = path[5:]

    if not path:
        return target

    current = target
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _evaluate_expression(expression: str, context: dict[str, object]) -> str:
    expression = expression.strip()
    if expression == "index":
        return str(context.get("index", ""))
    if expression.startswith("sum(") and expression.endswith(")"):
        inner = expression[4:-1]
        array_path, _, field_name = inner.partition("[].")
        values = _resolve_path(array_path, context)
        if not isinstance(values, list) or not field_name:
            return ""
        total = 0
        for value in values:
            if isinstance(value, dict):
                number = value.get(field_name)
                if isinstance(number, (int, float)):
                    total += number
        return str(int(total) if isinstance(total, float) and total.is_integer() else total)

    value = _resolve_path(expression, context)
    if value is None:
        return ""
    return str(value)


def _interpolate_text(template: str, context: dict[str, object]) -> str:
    result = template
    for match in re.finditer(r"\{([^{}]+)}", template):
        expression = match.group(1)
        result = result.replace(match.group(0), _evaluate_expression(expression, context))
    return result


def _render_blocks(spec: list[dict[str, object]], context: dict[str, object]) -> list[str]:
    output: list[str] = []
    for block in spec:
        block_type = block.get("type")
        if block_type == "heading":
            level_value = block.get("level", 1)
            level = int(str(level_value))
            value = _interpolate_text(str(block.get("value", "")), context)
            output.append(f"{'#' * level} {value}".rstrip())
        elif block_type == "text":
            output.append(_interpolate_text(str(block.get("value", "")), context))
        elif block_type == "separator":
            output.append(str(block.get("value", "---")))
        elif block_type == "bullet_list":
            values = _resolve_path(str(block.get("path", "")), context)
            if isinstance(values, list):
                for value in values:
                    output.append(f"- {value}")
        elif block_type == "repeat":
            items = _resolve_path(str(block.get("path", "")), context)
            body = block.get("body", [])
            if isinstance(items, list) and isinstance(body, list):
                for index, item in enumerate(items, start=1):
                    child_context = {"root": context["root"], "item": item, "index": index}
                    output.extend(_render_blocks(body, child_context))
        elif block_type == "if_present":
            value = _resolve_path(str(block.get("path", "")), context)
            body = block.get("body", [])
            if value and isinstance(body, list):
                output.extend(_render_blocks(body, context))
        else:
            raise ValueError(f"Unsupported render block type: {block_type}")
    return output


def _fill_defaults(target_id: str, payload: dict) -> dict:
    """Supply sensible default values for optional metadata fields before schema validation."""
    definition = get_target_definition(target_id)
    defaults = definition.get("defaults", [])
    if not isinstance(defaults, list):
        return payload

    items = payload.get("items") or payload.get("questions") or payload.get("slides") or []

    for rule in defaults:
        field = rule.get("field")
        if not field: continue
        condition = rule.get("if_null", False)
        if condition and payload.get(field): continue
        expr = rule.get("value")
        if not expr: continue

        if expr == "items":
            payload[field] = items
        elif expr.startswith("first_of:"):
            fields = expr[9:].split(",")
            for f in fields:
                val = payload.get(f.strip())
                if val:
                    if isinstance(val, list) and len(val) > 0:
                        payload[field] = val[0]
                    else:
                        payload[field] = val
                    break
        elif expr == "collect_unique:coverage_area":
            seen: list[str] = []
            for item in items:
                area = item.get("coverage_area", "")
                if area and area not in seen: seen.append(area)
            payload[field] = seen or ["General"]
        elif expr == "derive_dataset_name":
            domain = payload.get("domain", "")
            areas = payload.get("coverage_areas") or []
            if domain:
                payload[field] = f"{domain} Q&A Draft Set"
            elif areas:
                payload[field] = f"{areas[0]} Q&A Draft Set"
            else:
                payload[field] = "Golden Dataset Draft Set"
        elif expr == "derive_topic":
            first_val = ""
            if items:
                first_val = items[0].get("question") or items[0].get("title") or ""
            payload[field] = (first_val[:80] if first_val else "General")
        elif expr == "derive_objective":
            topic = payload.get("topic", "the subject")
            payload[field] = f"Assess knowledge and practical experience related to {topic}."
        elif expr == "dataset_size_calc":
            payload[field] = max(50, len(items) * 4)
        elif expr == "ensure_item_ids":
            for idx, item in enumerate(items, start=1):
                if not item.get("id"): item["id"] = str(idx)
        elif expr == "ensure_item_content":
            for item in items:
                if "content" not in item: item["content"] = ""
        else:
            payload[field] = expr
    return payload


def _render_payload(template: str, payload, render_spec: list[dict[str, object]]) -> str:
    if template == "markdown_blocks":
        context = {"root": payload, "item": payload, "index": 1}
        rendered = [block for block in _render_blocks(render_spec, context) if block != ""]
        return "\n\n".join(rendered).strip() + "\n"
    raise ValueError(f"Unsupported render template: {template}")


def _normalize_legacy_target_payload(target_id: str, payload: dict) -> dict:
    if target_id != "study-slides":
        return payload
    slides = payload.get("slides")
    if not isinstance(slides, list):
        return payload
    normalized_slides: list[dict] = []
    for slide in slides:
        if not isinstance(slide, dict):
            normalized_slides.append(slide)
            continue
        normalized_slide = dict(slide)
        if "bullets" not in normalized_slide and "content" in normalized_slide:
            content = normalized_slide.get("content")
            if isinstance(content, list):
                normalized_slide["bullets"] = [str(item) for item in content]
            elif isinstance(content, str):
                normalized_slide["bullets"] = [content]
        normalized_slide.pop("content", None)
        normalized_slide.pop("slide_number", None)
        normalized_slides.append(normalized_slide)
    payload = dict(payload)
    payload["slides"] = normalized_slides
    return payload


def _prepare_validated_payload(
        target_id: str, payload_json: str | dict
) -> tuple[dict | None, dict | None, str | None]:
    try:
        definition = get_target_definition(target_id)
    except ValueError as exc:
        return None, None, str(exc)

    if not definition.get("schema"):
        return None, None, (
            f"ERROR: Target '{target_id}' is an unstructured target. Do NOT use `render_target_output`! Use the `write_file` tool to save your final output directly "
            f"to `/final_report.md` as Markdown text. Do NOT just say you will write it; you must actually call the `write_file` tool with the text.")

    if isinstance(payload_json, dict):
        payload = payload_json
    else:
        try:
            payload = robust_json_loads(payload_json)
        except ValueError as exc:
            return None, None, f"Invalid JSON payload: {exc}"

    payload = _normalize_legacy_target_payload(target_id, payload)
    payload = _fill_defaults(target_id, payload)
    payload = _coerce_integers(payload, definition["schema"])

    # Ensure payload is a dict after coercion
    if not isinstance(payload, dict):
        return None, None, "Error: Payload coercion resulted in non-dict type"

    try:
        jsonschema.validate(instance=payload, schema=definition["schema"])
    except jsonschema.ValidationError as exc:
        return None, None, f"Schema validation failed for target '{target_id}': {exc.message}"

    return definition, payload, None


@tool(parse_docstring=True)
def render_target_output(
        target_id: str,
        payload_json: str | dict,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Render structured target output using a reusable target definition.

    Use this tool ONLY for structured output targets (targets with a JSON schema).
    DO NOT use this tool for 'Unstructured Markdown Document' targets.
    Provide the target id and a JSON payload that matches the selected target schema exactly.
    The payload may be either a JSON object string or a dict-like JSON object.
    NEVER put raw markdown into payload_json.

    Args:
        target_id: The target definition id to use for validation and rendering.
        payload_json: A JSON object string or dict matching the target schema.
        state: LangGraph state

    Returns:
        Rendered markdown output or a validation error message.
    """
    definition, payload, err = _prepare_validated_payload(target_id, payload_json)
    if err: return err
    return _render_payload(definition["render"]["template"], payload, definition["render"]["spec"])
