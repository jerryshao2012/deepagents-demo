"""Research Tools.

This module provides search and content processing utilities for the research agent,
using Tavily for URL discovery and fetching full webpage content.
"""

from __future__ import annotations

import json
import os
import re
from json import dumps as json_dumps
from pathlib import Path

import httpx
import jsonschema
import requests
from dotenv import load_dotenv
from langchain_core.tools import InjectedToolArg, tool
from langgraph.prebuilt import InjectedState
from markdownify import markdownify
from tavily import TavilyClient
from typing_extensions import Annotated, Literal

from research_agent.targets import get_target_definition
from utils import get_ssl_verify_config

load_dotenv()

verify_ssl = get_ssl_verify_config()
tavily_session = requests.Session()
tavily_session.verify = verify_ssl
tavily_client = TavilyClient(session=tavily_session)

SUPPORTED_DOC_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx", ".xlsx"}


def _run_tavily_search(query: str, max_results: int, topic: str, timeout: float = 60.0) -> dict:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not set")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "topic": topic,
        "include_answer": False,
        "include_raw_content": False,
    }
    response = tavily_client.session.post(
        f"{tavily_client.base_url}/search",
        data=json_dumps(payload),
        timeout=min(timeout, 120),
        verify=verify_ssl,
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    response_dict = response.json()
    if not isinstance(response_dict, dict):
        return {"results": []}
    response_dict.setdefault("results", [])
    return response_dict


def fetch_webpage_content(url: str, timeout: float = 10.0) -> str:
    """Fetch and convert webpage content to markdown."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        response = httpx.get(
            url=url,
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
        )
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as exc:
        return f"Error fetching content from {url}: {exc}"


def _extract_pdf_text(file_path: Path):
    try:
        print("Use docling for PDF text extraction.")
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(str(file_path))
        markdown_content = result.document.export_to_markdown()
        if markdown_content.strip():
            return markdown_content
    except Exception as e:
        # Fallback to pypdf if docling fails
        try:
            print("Falling back to pypdf for PDF text extraction.")
            import pypdf
            reader = pypdf.PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            return f"Error extracting PDF text: {e}"


def _extract_text_file(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def _extract_docx_text(file_path: Path) -> str:
    from docx import Document

    document = Document(str(file_path))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    return "\n".join(text for text in paragraphs if text)


def _extract_pptx_text(file_path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(str(file_path))
    slide_sections: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = [f"Slide {index}"]
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                parts.append(text.strip())

        notes_text = ""
        if slide.has_notes_slide and slide.notes_slide:
            notes = []
            for shape in slide.notes_slide.shapes:
                text = getattr(shape, "text", "")
                if text and text.strip():
                    notes.append(text.strip())
            notes_text = "\n".join(notes)
        if notes_text:
            parts.append(f"Speaker Notes:\n{notes_text}")
        slide_sections.append("\n".join(parts))

    return "\n\n".join(slide_sections)


def _extract_xlsx_text(file_path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(filename=str(file_path), read_only=True, data_only=True)
    sections: list[str] = []
    try:
        for worksheet in workbook.worksheets:
            rows: list[str] = []
            for row in worksheet.iter_rows(values_only=True):
                values = [str(value).strip() for value in row if value not in (None, "")]
                if values:
                    rows.append(" | ".join(values))
            body = "\n".join(rows) if rows else "(empty sheet)"
            sections.append(f"Sheet: {worksheet.title}\n{body}")
    finally:
        workbook.close()

    return "\n\n".join(sections)


def _extract_supported_document(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(file_path)
    if suffix in {".txt", ".md"}:
        return _extract_text_file(file_path)
    if suffix == ".docx":
        return _extract_docx_text(file_path)
    if suffix == ".pptx":
        return _extract_pptx_text(file_path)
    if suffix == ".xlsx":
        return _extract_xlsx_text(file_path)
    raise ValueError(f"Unsupported document type: {suffix}")


@tool(parse_docstring=True)
def tavily_search(
        query: str,
        max_results: Annotated[int, InjectedToolArg] = 1,
        topic: Annotated[Literal["general", "news", "finance"], InjectedToolArg] = "general",
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Search the web for information on a given query.

    Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 1)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')
        state: LangGraph state

    Returns:
        Formatted search results with full webpage content
    """
    if state:
        messages = state.get("messages", [])
        for msg in messages:
            content = getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", "")
            if isinstance(content, str) and "Do NOT use web search" in content:
                return "Note: Web search is disabled for this research task. Please use local documents or internal knowledge only."

    try:
        search_results = _run_tavily_search(
            query=query,
            max_results=max_results,
            topic=topic,
        )
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 401:
            return (
                "Tavily authentication failed (401 Unauthorized)."
                "Set a valid TAVILY_API_KEY environment variable and retry"
            )
        return f"Tavily request failed with HTTP {status_code}: {exc}"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"Tavily search failed: {exc}"

    result_texts = []
    for result in search_results.get("results", []):
        url = result["url"]
        title = result["title"]
        content = fetch_webpage_content(url)
        result_text = f"""## {title}
**URL:** {url}

{content}

---
"""
        result_texts.append(result_text)

    return f"""🔍 Found {len(result_texts)} result(s) for '{query}':

{chr(10).join(result_texts)}"""


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    Args:
        reflection: Detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


@tool(parse_docstring=True)
def read_doc_folder(folder_path: str) -> str:
    """Read and extract text from supported documents in a given folder.

    Use this tool when you need to research from local documents instead of or in addition
    to web search. Supported file types are PDF, text, Markdown, Word, PowerPoint, and Excel.

    Args:
        folder_path: The absolute or relative path to the folder containing document files.

    Returns:
        Extracted text from all supported documents or an error message.
    """
    folder = Path(folder_path)

    # If the folder doesn't exist, try resolving it relative to the deep_research package
    if not folder.exists():
        package_root = Path(__file__).resolve().parent.parent
        alternate_folder = package_root / folder_path
        if alternate_folder.exists() and alternate_folder.is_dir():
            folder = alternate_folder

    if not folder.exists():
        return f"Error: Folder {folder_path} does not exist."
    if not folder.is_dir():
        return f"Error: {folder_path} is not a folder."

    extracted_text: list[str] = []
    supported_files = sorted(
        file_path for file_path in folder.iterdir() if file_path.suffix.lower() in SUPPORTED_DOC_SUFFIXES
    )

    if not supported_files:
        return (
            f"No supported document files found in {folder_path}. "
            "Supported types: .pdf, .txt, .md, .docx, .pptx, .xlsx."
        )

    for file_path in supported_files:
        try:
            content = _extract_supported_document(file_path)
            extracted_text.append(f"--- Content of {file_path.name} ---\n{content}\n")
        except Exception as exc:
            extracted_text.append(f"--- Error reading {file_path.name}: {exc} ---\n")

    return "\n".join(extracted_text)


def _coerce_integers(value, schema):
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
    for match in re.finditer(r"\{([^{}]+)\}", template):
        expression = match.group(1)
        result = result.replace(match.group(0), _evaluate_expression(expression, context))
    return result


def _render_blocks(spec: list[dict[str, object]], context: dict[str, object]) -> list[str]:
    output: list[str] = []
    for block in spec:
        block_type = block.get("type")
        if block_type == "heading":
            level = int(block.get("level", 1))
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


def _render_payload(template: str, payload, render_spec: list[dict[str, object]]) -> str:
    if template == "markdown_blocks":
        context = {"root": payload, "item": payload, "index": 1}
        rendered = [block for block in _render_blocks(render_spec, context) if block != ""]
        return "\n\n".join(rendered).strip() + "\n"
    raise ValueError(f"Unsupported render template: {template}")


@tool(parse_docstring=True)
def render_target_output(target_id: str, payload_json: str) -> str:
    """Render structured target output using a reusable target definition.

    Use this tool for any structured output target. Provide the target id and a JSON
    payload that matches the selected target schema exactly.

    Args:
        target_id: The target definition id to use for validation and rendering.
        payload_json: A JSON object string matching the target schema.

    Returns:
        Rendered markdown output or a validation error message.
    """
    try:
        definition = get_target_definition(target_id)
    except ValueError as exc:
        return str(exc)
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        return f"Invalid JSON payload: {exc}"

    payload = _coerce_integers(payload, definition["schema"])

    try:
        jsonschema.validate(instance=payload, schema=definition["schema"])
    except jsonschema.ValidationError as exc:
        return f"Schema validation failed for target '{target_id}': {exc.message}"

    return _render_payload(definition["render"]["template"], payload, definition["render"]["spec"])
