"""Research Tools.

This module provides search and content processing utilities for the research agent,
using Tavily for URL discovery and fetching full webpage content.
"""

from __future__ import annotations

import datetime
import html
import os
import random
import re
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import create_file_data
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from research_agent.utils.content_extractors import _extract_supported_document
# Import modularized utilities and tools
from research_agent.utils.knowledge_filesystem import (  # noqa: F401
    MAX_GLOB_DEPTH,
    MAX_FILES_TO_READ,
    MAX_TOTAL_SIZE_MB,
    SUPPORTED_DOC_SUFFIXES,
    REPORTS_OUTPUT_FOLDER,
    _folder_listing_cache,
    _normalize_path_for_filesystem_tools,
    _get_extracted_path,
    _resolve_doc_output_subfolder,
    ls,
    glob,
    read_file,
)
from research_agent.utils.result_rendering import (  # noqa: F401
    _prepare_validated_payload,
    render_target_output,
)
from research_agent.utils.web_search import (  # noqa: F401
    tavily_search,
)


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
    # Ensure output directory exists for logging reflections
    output_dir = Path(os.environ.get("OUTPUT_FOLDER", "./output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # Log the reflection to a dedicated research log file
    log_file = output_dir / "research_reflection.log"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] REFLECTION:\n{reflection}\n")
        f.write("-" * 80 + "\n")

    return f"Reflection recorded: {reflection}"


@tool(parse_docstring=True)
def read_doc_folder(
        folder_path: str,
        specific_files: list[str] | None = None,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Read and extract text from supported documents in a given folder.

    Use this tool when you need to research from local documents instead of or in addition
    to web search. Supported file types are PDF, text, Markdown, Word, PowerPoint, and Excel.

    If the folder contains a large number of files or the total size is very large,
    this tool will return a summary of the contents instead of all text.
    You can then use the `specific_files` argument to read particular documents of interest.

    Args:
        folder_path: The absolute or relative path to the folder containing document files.
        specific_files: Optional list of filenames within the folder to read specifically.
            If provided, only these files will be processed, bypassing general limits.
        state: LangGraph state (injected automatically, do not supply).

    Returns:
        Extracted text from supported documents, a summary for large folders, or an error message.
    """
    configured_doc_folder: str | None = None
    if state and isinstance(state, dict):
        configured_doc_folder = state.get("doc_folder")

    # Fallback: subagent state schemas may not include doc_folder, so the
    # orchestrator also persists it as an environment variable.
    if not configured_doc_folder:
        configured_doc_folder = os.environ.get("DOC_FOLDER")

    if not configured_doc_folder:
        return (
            "Error: No document folder has been configured for this research task. "
            "Pass --doc-folder <path> when invoking the CLI, or include the folder path "
            "(e.g. '--doc-folder ./docs/policy/') in your message when using the API. "
            "Do NOT attempt to read from any other filesystem path."
        )

    allowed_root = Path(configured_doc_folder).resolve()
    folder = Path(folder_path).resolve()
    try:
        folder.relative_to(allowed_root)
    except ValueError:
        print(
            f"[read_doc_folder] Redirecting '{folder_path}' → '{allowed_root}' (only the configured doc_folder is permitted).")
        folder = allowed_root

    if not folder.exists(): return f"Error: Folder '{folder}' does not exist."
    if not folder.is_dir(): return f"Error: '{folder}' is not a directory."

    specific_set = set(specific_files) if specific_files else None

    # Cached folder listing
    cache_key = str(folder.resolve())
    if cache_key in _folder_listing_cache:
        supported_files = _folder_listing_cache[cache_key]
    else:
        all_candidates: list[Path] = []
        for file_path in folder.rglob("*"):
            if len(file_path.relative_to(folder).parts) > MAX_GLOB_DEPTH:
                continue
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_DOC_SUFFIXES:
                all_candidates.append(file_path)
        supported_files = sorted(all_candidates)
        _folder_listing_cache[cache_key] = supported_files

    if not supported_files:
        return f"No supported document files found in {folder_path}. Supported types: .pdf, .txt, .md, .docx, .pptx, .xlsx."

    if specific_set:
        files_to_process = [f for f in supported_files if f.name in specific_set]
        if not files_to_process:
            return f"None of the requested files were found in {folder_path}. Available: {', '.join(f.name for f in supported_files[:10])}..."
    else:
        total_files = len(supported_files)
        total_size_mb = sum(f.lstat().st_size for f in supported_files) / (1024 * 1024)

        if total_files > MAX_FILES_TO_READ or total_size_mb > MAX_TOTAL_SIZE_MB:
            avg_size_mb = total_size_mb / total_files if total_files > 0 else 0
            max_files_by_size = max(1, int(MAX_TOTAL_SIZE_MB / avg_size_mb)) if avg_size_mb > 0 else MAX_FILES_TO_READ
            sample_size = min(MAX_FILES_TO_READ, total_files, max_files_by_size)
            auto_sample = [f.name for f in random.sample(supported_files, sample_size)]
            preview_list = "\n".join(f"- {f.name} ({f.lstat().st_size / 1024:.1f} KB)" for f in supported_files[:60])
            if total_files > 60: preview_list += f"\n... and {total_files - 60} more files (not shown)."
            auto_sample_str = ", ".join(f'"{n}"' for n in auto_sample)
            return (
                f"TOOL RESULT — folder too large to read all at once: {total_files} files, {total_size_mb:.1f} MB (limits: {MAX_FILES_TO_READ} files / {MAX_TOTAL_SIZE_MB} MB).\n\n"
                "ACTION REQUIRED — do NOT ask the user for confirmation. You MUST immediately:\n"
                f"1. Call read_doc_folder again on '{folder_path}' with specific_files set to the auto-sample below.\n"
                "2. Continue research using those documents.\n\n"
                f"Pre-built diverse auto-sample ({len(auto_sample)} files, evenly spread across the directory):\n"
                f"[{auto_sample_str}]\n\n"
                f"Full file listing (first 60 of {total_files}):\n{preview_list}"
            )
        files_to_process = supported_files

    extracted_text: list[str] = []
    processed_files: list[str] = []
    failed_files: list[str] = []
    output_subfolder = _resolve_doc_output_subfolder(folder)

    for file_path in files_to_process:
        target_path = _get_extracted_path(file_path, output_subfolder)
        if target_path.exists():
            print(f"Skipping {file_path.name}, already extracted to {target_path}")
            try:
                content = target_path.read_text(encoding="utf-8")
                processed_files.append(f"{file_path.name} (skipped, loaded from {target_path})")
                extracted_text.append(f"--- Content of {file_path.name} (from cache) ---\n{content}\n")
                continue
            except Exception as exc:
                print(f"Failed to read existing extract {target_path}: {exc}. Re-extracting...")

        print(f"Processing document: {file_path.name}...")
        try:
            content = _extract_supported_document(file_path)
            saved_path = _save_extracted_content(file_path, content, output_folder=output_subfolder)
            processed_files.append(f"{file_path.name} (saved to {saved_path})")
            extracted_text.append(f"--- Content of {file_path.name} ---\n{content}\n")
        except Exception as exc:
            failed_files.append(file_path.name)
            extracted_text.append(f"--- Error reading {file_path.name}: {exc} ---\n")

    summary_lines = [f"Processed {len(processed_files)}/{len(files_to_process)} supported file(s) from {folder}."]
    if processed_files: summary_lines.append(f"Files processed: {', '.join(processed_files)}")
    if failed_files: summary_lines.append(f"Files failed: {', '.join(failed_files)}")
    summary_lines.append(
        "\nIMPORTANT: Use ONLY the file paths listed above. Do NOT reference "
        "filenames from the user's prompt if they differ from the actual files "
        "discovered here. If you need to read individual files, use the exact "
        "paths shown in 'Files processed' above with the `read_file` tool."
    )
    print("\n".join(summary_lines))
    return "\n".join(summary_lines + [""] + extracted_text)


def _save_extracted_content(original_file_path: Path, content: str, output_folder: Path | None = None) -> str:
    if output_folder:
        output_dir = output_folder
    else:
        output_dir = Path(REPORTS_OUTPUT_FOLDER)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = _get_extracted_path(original_file_path, output_dir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return _normalize_path_for_filesystem_tools(str(file_path))


def save_research_report(report_title: str, content: str) -> str:
    """Save a research report to the output folder."""
    output_subfolder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
    output_subfolder.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^a-zA-Z0-9_\- ]", "", report_title).strip()[:100]
    safe_title = safe_title.replace(" ", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_title}.md"
    file_path = output_subfolder / filename
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return _normalize_path_for_filesystem_tools(str(file_path))


_FRONTEND_SLIDES_SKILL_DIR = Path(__file__).resolve().parent / "skills" / "frontend-slides"
_FRONTEND_SLIDES_STYLE_PRESETS: dict[str, dict[str, str]] = {
    "Bold Signal": {
        "font_href": "https://fonts.googleapis.com/css2?family=Archivo+Black&family=Space+Grotesk:wght@400;500;700&display=swap",
        "font_display": '"Archivo Black", sans-serif',
        "font_body": '"Space Grotesk", sans-serif',
        "bg_primary": "#161616",
        "bg_secondary": "#242424",
        "surface": "rgba(255, 87, 34, 0.92)",
        "surface_alt": "rgba(255, 255, 255, 0.1)",
        "text_primary": "#ffffff",
        "text_secondary": "#ffe0d4",
        "accent": "#ff7a45",
        "accent_soft": "rgba(255, 122, 69, 0.22)",
    },
    "Electric Studio": {
        "font_href": "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;700;800&display=swap",
        "font_display": '"Manrope", sans-serif',
        "font_body": '"Manrope", sans-serif',
        "bg_primary": "#07111f",
        "bg_secondary": "#16355f",
        "surface": "rgba(255, 255, 255, 0.94)",
        "surface_alt": "rgba(67, 97, 238, 0.16)",
        "text_primary": "#f8fbff",
        "text_secondary": "#dce7ff",
        "accent": "#4361ee",
        "accent_soft": "rgba(67, 97, 238, 0.2)",
    },
    "Creative Voltage": {
        "font_href": "https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Space+Mono:wght@400;700&display=swap",
        "font_display": '"Syne", sans-serif',
        "font_body": '"Space Mono", monospace',
        "bg_primary": "#0b1020",
        "bg_secondary": "#005df5",
        "surface": "rgba(13, 23, 52, 0.84)",
        "surface_alt": "rgba(212, 255, 0, 0.14)",
        "text_primary": "#ffffff",
        "text_secondary": "#d6ddff",
        "accent": "#d4ff00",
        "accent_soft": "rgba(212, 255, 0, 0.2)",
    },
    "Dark Botanical": {
        "font_href": "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=IBM+Plex+Sans:wght@300;400;500&display=swap",
        "font_display": '"Cormorant Garamond", serif',
        "font_body": '"IBM Plex Sans", sans-serif',
        "bg_primary": "#0f0f0f",
        "bg_secondary": "#2a1f1b",
        "surface": "rgba(34, 28, 24, 0.78)",
        "surface_alt": "rgba(212, 165, 116, 0.14)",
        "text_primary": "#f4eee8",
        "text_secondary": "#d6c8bc",
        "accent": "#d4a574",
        "accent_soft": "rgba(212, 165, 116, 0.2)",
    },
}


def _load_frontend_slides_viewport_css() -> str:
    viewport_path = _FRONTEND_SLIDES_SKILL_DIR / "viewport-base.css"
    return viewport_path.read_text(encoding="utf-8")


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "presentation"


def _clean_frontend_slides_text(value: str) -> str:
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("***", " ").replace("**", "").replace("__", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _parse_frontend_slides_bullets(value: str) -> list[str]:
    bullets: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        bullet_match = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        if bullet_match:
            bullets.append(_clean_frontend_slides_text(bullet_match.group(1)))
    return bullets


def _parse_frontend_slides_sections(presentation_markdown: str) -> list[dict[str, object]]:
    pattern = re.compile(r"^#\s*\[Slide\s+\d+\]\s*Title:\s*(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(presentation_markdown))
    if not matches:
        return []

    slides: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        title = _clean_frontend_slides_text(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(presentation_markdown)
        section_text = presentation_markdown[start:end].strip()

        fields: dict[str, list[str]] = {}
        current_label: str | None = None
        unlabeled_lines: list[str] = []
        for raw_line in section_text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                if current_label:
                    fields.setdefault(current_label, []).append("")
                continue
            label_match = re.match(r"^\*\*([^:*]+):\*\*\s*(.*)$", stripped)
            if label_match:
                current_label = label_match.group(1).strip().lower()
                fields.setdefault(current_label, [])
                trailing = label_match.group(2).strip()
                if trailing:
                    fields[current_label].append(trailing)
                continue
            if current_label:
                fields.setdefault(current_label, []).append(stripped)
            else:
                unlabeled_lines.append(stripped)

        headline = _clean_frontend_slides_text("\n".join(fields.get("headline", [])))
        subtitle = _clean_frontend_slides_text("\n".join(fields.get("subtitle", [])))
        contact = _clean_frontend_slides_text("\n".join(fields.get("contact", [])))
        callout = _clean_frontend_slides_text("\n".join(fields.get("callout", [])))

        bullets = _parse_frontend_slides_bullets("\n".join(unlabeled_lines))
        bullets.extend(_parse_frontend_slides_bullets("\n".join(fields.get("body", []))))

        paragraph_sources = [
            _clean_frontend_slides_text("\n".join(fields.get("body", []))),
            _clean_frontend_slides_text("\n".join(unlabeled_lines)),
        ]
        paragraphs: list[str] = []
        for candidate in paragraph_sources:
            if not candidate:
                continue
            if candidate not in paragraphs and candidate not in bullets:
                paragraphs.append(candidate)

        slides.append(
            {
                "title": title,
                "headline": headline,
                "subtitle": subtitle,
                "contact": contact,
                "callout": callout,
                "bullets": bullets[:6],
                "paragraphs": paragraphs[:2],
            }
        )

    return slides


def _build_frontend_slides_html(
    deck_title: str,
    slides: list[dict[str, object]],
    style_preset: str,
) -> str:
    viewport_css = _load_frontend_slides_viewport_css()
    preset = _FRONTEND_SLIDES_STYLE_PRESETS.get(
        style_preset, _FRONTEND_SLIDES_STYLE_PRESETS["Creative Voltage"]
    )

    slide_markup: list[str] = []
    for index, slide in enumerate(slides, start=1):
        title = html.escape(str(slide["title"]))
        headline = html.escape(str(slide["headline"]))
        subtitle = html.escape(str(slide["subtitle"]))
        contact = html.escape(str(slide["contact"]))
        callout = html.escape(str(slide["callout"]))
        bullets = [html.escape(str(item)) for item in slide.get("bullets", [])]  # type: ignore[arg-type]
        paragraphs = [html.escape(str(item)) for item in slide.get("paragraphs", [])]  # type: ignore[arg-type]

        is_title_slide = index == 1
        body_parts: list[str] = []
        if headline:
            body_parts.append(f'<p class="eyebrow reveal">{headline}</p>')
        if subtitle:
            body_parts.append(f'<p class="subtitle reveal">{subtitle}</p>')
        if bullets:
            body_parts.append(
                '<ul class="bullet-list reveal">'
                + "".join(f"<li>{bullet}</li>" for bullet in bullets)
                + "</ul>"
            )
        elif paragraphs:
            body_parts.append(
                '<div class="paragraph-stack reveal">'
                + "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
                + "</div>"
            )
        if callout:
            body_parts.append(f'<aside class="callout reveal">{callout}</aside>')
        if contact:
            body_parts.append(f'<p class="contact reveal">{contact}</p>')

        slide_markup.append(
            f"""
    <section class="slide{' title-slide' if is_title_slide else ''}" data-slide="{index}">
      <div class="slide-shell">
        <div class="slide-number reveal">{index:02d}</div>
        <div class="slide-content">
          <div class="title-wrap">
            <p class="kicker reveal">Frontend Slides</p>
            <h1 class="slide-title reveal">{title}</h1>
          </div>
          <div class="slide-body">
            {''.join(body_parts)}
          </div>
        </div>
      </div>
    </section>""".rstrip()
        )

    return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{html.escape(deck_title)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link rel="stylesheet" href="{preset['font_href']}" />
    <style>
      :root {{
        --bg-primary: {preset['bg_primary']};
        --bg-secondary: {preset['bg_secondary']};
        --surface: {preset['surface']};
        --surface-alt: {preset['surface_alt']};
        --text-primary: {preset['text_primary']};
        --text-secondary: {preset['text_secondary']};
        --accent: {preset['accent']};
        --accent-soft: {preset['accent_soft']};
        --font-display: {preset['font_display']};
        --font-body: {preset['font_body']};
      }}

{viewport_css}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        color: var(--text-primary);
        background:
          radial-gradient(circle at top left, rgba(255, 255, 255, 0.08), transparent 28%),
          radial-gradient(circle at bottom right, var(--accent-soft), transparent 32%),
          linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
        font-family: var(--font-body);
      }}

      .slide {{
        align-items: center;
        justify-content: center;
        padding: clamp(0.75rem, 2vw, 2rem);
      }}

      .slide-shell {{
        width: min(92vw, 1240px);
        height: min(88vh, 900px);
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: linear-gradient(160deg, var(--surface) 0%, rgba(4, 7, 17, 0.84) 100%);
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
        border-radius: clamp(1rem, 2vw, 2rem);
        display: grid;
        grid-template-columns: minmax(4rem, 8rem) 1fr;
        overflow: hidden;
        position: relative;
      }}

      .slide-shell::before {{
        content: "";
        position: absolute;
        inset: 0;
        background:
          linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px),
          linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px);
        background-size: clamp(24px, 3vw, 36px) clamp(24px, 3vw, 36px);
        opacity: 0.3;
        pointer-events: none;
      }}

      .slide-number {{
        display: flex;
        align-items: flex-start;
        justify-content: center;
        padding-top: clamp(1.5rem, 3vw, 3rem);
        font-family: var(--font-display);
        font-size: clamp(2rem, 8vw, 6rem);
        color: var(--accent);
        letter-spacing: 0.08em;
        z-index: 1;
      }}

      .slide-content {{
        position: relative;
        z-index: 1;
        gap: clamp(1rem, 2vh, 2rem);
      }}

      .title-wrap {{
        display: grid;
        gap: clamp(0.5rem, 1.5vh, 1rem);
      }}

      .kicker,
      .eyebrow,
      .contact {{
        margin: 0;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.16em;
        font-size: clamp(0.68rem, 1vw, 0.92rem);
      }}

      .slide-title {{
        margin: 0;
        max-width: 14ch;
        font-family: var(--font-display);
        font-size: clamp(2rem, 5.8vw, 5.4rem);
        line-height: 0.92;
        text-wrap: balance;
      }}

      .slide-body {{
        display: grid;
        gap: clamp(0.8rem, 1.7vh, 1.35rem);
        max-width: min(58rem, 100%);
      }}

      .subtitle,
      .paragraph-stack p {{
        margin: 0;
        font-size: clamp(0.9rem, 1.5vw, 1.2rem);
        line-height: 1.55;
        color: var(--text-primary);
        max-width: 65ch;
      }}

      .bullet-list {{
        margin: 0;
        padding-left: clamp(1rem, 2vw, 1.6rem);
        display: grid;
        gap: clamp(0.45rem, 0.8vh, 0.75rem);
        font-size: clamp(0.84rem, 1.35vw, 1.08rem);
        line-height: 1.45;
      }}

      .callout {{
        margin: 0;
        max-width: 72ch;
        padding: clamp(0.9rem, 1.8vw, 1.25rem);
        border-left: 4px solid var(--accent);
        background: var(--surface-alt);
        font-size: clamp(0.88rem, 1.35vw, 1.05rem);
        line-height: 1.5;
      }}

      .progress-bar {{
        position: fixed;
        inset: 0 0 auto 0;
        height: 4px;
        transform-origin: left center;
        background: linear-gradient(90deg, var(--accent) 0%, #ffffff 100%);
        transform: scaleX(0);
        z-index: 100;
      }}

      .nav-dots {{
        position: fixed;
        right: clamp(0.75rem, 2vw, 1.5rem);
        top: 50%;
        transform: translateY(-50%);
        display: grid;
        gap: 0.55rem;
        z-index: 100;
      }}

      .nav-dots button {{
        width: 0.8rem;
        height: 0.8rem;
        border-radius: 999px;
        border: 0;
        background: rgba(255, 255, 255, 0.22);
        cursor: pointer;
        transition: transform 0.2s ease, background 0.2s ease;
      }}

      .nav-dots button.active {{
        background: var(--accent);
        transform: scale(1.15);
      }}

      .reveal {{
        opacity: 0;
        transform: translateY(24px);
        transition: opacity 0.55s ease, transform 0.55s ease;
      }}

      .slide.visible .reveal {{
        opacity: 1;
        transform: translateY(0);
      }}

      .reveal:nth-child(1) {{ transition-delay: 0.08s; }}
      .reveal:nth-child(2) {{ transition-delay: 0.16s; }}
      .reveal:nth-child(3) {{ transition-delay: 0.24s; }}
      .reveal:nth-child(4) {{ transition-delay: 0.32s; }}
      .reveal:nth-child(5) {{ transition-delay: 0.4s; }}

      @media (max-width: 820px) {{
        .slide-shell {{
          grid-template-columns: 1fr;
          grid-template-rows: auto 1fr;
        }}

        .slide-number {{
          justify-content: flex-start;
          padding: clamp(1rem, 2vw, 1.5rem) 0 0 clamp(1.1rem, 3vw, 1.8rem);
        }}
      }}
    </style>
  </head>
  <body>
    <div class="progress-bar" aria-hidden="true"></div>
    <nav class="nav-dots" aria-label="Slide navigation"></nav>
{''.join(slide_markup)}
    <script>
      class SlidePresentation {{
        constructor() {{
          this.slides = [...document.querySelectorAll(".slide")];
          this.progressBar = document.querySelector(".progress-bar");
          this.navDotsContainer = document.querySelector(".nav-dots");
          this.currentSlide = 0;
          this.buildNavDots();
          this.setupObserver();
          this.setupKeyboardNav();
          this.updateUI(0);
        }}

        buildNavDots() {{
          this.navDotsContainer.innerHTML = "";
          this.slides.forEach((_, index) => {{
            const dot = document.createElement("button");
            dot.type = "button";
            dot.setAttribute("aria-label", `Go to slide ${{index + 1}}`);
            dot.addEventListener("click", () => this.goToSlide(index));
            this.navDotsContainer.appendChild(dot);
          }});
        }}

        setupObserver() {{
          const observer = new IntersectionObserver((entries) => {{
            entries.forEach((entry) => {{
              if (entry.isIntersecting) {{
                const index = this.slides.indexOf(entry.target);
                this.updateUI(index);
                entry.target.classList.add("visible");
              }}
            }});
          }}, {{ threshold: 0.55 }});
          this.slides.forEach((slide) => observer.observe(slide));
        }}

        setupKeyboardNav() {{
          window.addEventListener("keydown", (event) => {{
            if (["ArrowDown", "PageDown", " "].includes(event.key)) {{
              event.preventDefault();
              this.goToSlide(Math.min(this.currentSlide + 1, this.slides.length - 1));
            }}
            if (["ArrowUp", "PageUp"].includes(event.key)) {{
              event.preventDefault();
              this.goToSlide(Math.max(this.currentSlide - 1, 0));
            }}
          }});
        }}

        goToSlide(index) {{
          this.slides[index]?.scrollIntoView({{ behavior: "smooth", block: "start" }});
          this.updateUI(index);
        }}

        updateUI(index) {{
          this.currentSlide = index;
          const progress = this.slides.length <= 1 ? 1 : index / (this.slides.length - 1);
          this.progressBar.style.transform = `scaleX(${{progress}})`;
          [...this.navDotsContainer.children].forEach((dot, dotIndex) => {{
            dot.classList.toggle("active", dotIndex === index);
          }});
        }}
      }}

      new SlidePresentation();
    </script>
  </body>
</html>
"""


@tool("frontend-slides", parse_docstring=True)
def frontend_slides(
    presentation_markdown: str,
    output_filename: str | None = None,
    deck_title: str | None = None,
    style_preset: str = "Creative Voltage",
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Generate a self-contained HTML slide deck from markdown-style slide content.

    Use this tool when the user wants an actual browser-ready presentation rather than
    plain markdown. It accepts content in the frontend-slides format, such as:
    ``# [Slide 1] Title: ...`` followed by ``**Headline:**``, ``**Subtitle:**``,
    ``**Body:**``, bullet lists, and optional ``**Callout:**`` blocks.

    Args:
        presentation_markdown: Markdown-style slide content to convert into HTML slides.
        output_filename: Optional filename for the generated HTML. Saved under OUTPUT_FOLDER.
        deck_title: Optional browser title for the presentation. Defaults to the first slide title.
        style_preset: Visual preset name. Supported: Bold Signal, Electric Studio, Creative Voltage, Dark Botanical.
        state: LangGraph state (injected automatically, do not supply).

    Returns:
        Confirmation containing the generated file path and slide count, or an error message.
    """
    slides = _parse_frontend_slides_sections(presentation_markdown)
    if not slides:
        return (
            "Error: No slides were detected. Use headings like "
            "`# [Slide 1] Title: My Slide` in the presentation_markdown input."
        )

    resolved_title = deck_title or str(slides[0]["title"])
    html_content = _build_frontend_slides_html(resolved_title, slides, style_preset)

    output_dir = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_filename:
        safe_name = Path(output_filename).name
        if not safe_name.endswith(".html"):
            safe_name = f"{safe_name}.html"
    else:
        safe_name = f"{_slugify_filename(resolved_title)}.html"

    output_path = output_dir / safe_name
    output_path.write_text(html_content, encoding="utf-8")

    if state is not None:
        files = state.get("files", {})
        files[f"/{safe_name}"] = create_file_data(html_content)
        state["files"] = files

    normalized_path = _normalize_path_for_filesystem_tools(str(output_path))
    return (
        f"Generated `{style_preset}` HTML presentation with {len(slides)} slide(s) at "
        f"`{normalized_path}`."
    )


@tool(parse_docstring=True)
def finalize_golden_dataset_output(
        payload_json: str,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Export a validated golden-dataset JSON payload to CSV and run quality metrics.

    For the ``golden-dataset`` target, call this after ``render_target_output`` with the
    same JSON. This writes the CSV under the output folder and runs metrics in one step.
    It also generates:
    - `/golden_dataset_metrics.md`: Markdown table of all items with quality metrics
    - `/final_report.md`: Comprehensive report of the entire golden dataset generation process

    Args:
        payload_json: JSON object matching the golden-dataset schema (same payload as ``render_target_output``).
        state: LangGraph state

    Returns:
        Paths to the exported CSV and metrics output, or a validation or runtime error message.
    """
    import time
    from research_agent.skills.golden_dataset.pipeline import (
        GOLDEN_DATASET_TARGET_ID,
        evaluate_and_report_golden_dataset,
        export_golden_dataset_csv,
    )

    if state is not None:
        requested_target = state.get("target")
        if requested_target != GOLDEN_DATASET_TARGET_ID:
            return (
                "ERROR: `finalize_golden_dataset_output` is only available when the active "
                "target is `golden-dataset`. Use the standard research flow when no target is selected."
            )

    _, payload, err = _prepare_validated_payload(GOLDEN_DATASET_TARGET_ID, payload_json)
    if err: return err
    if payload is None:
        return "Error: Failed to prepare validated payload"

    try:
        start_time = state.get("agent_start_time") if state else None
        if isinstance(start_time, float):
            elapsed_seconds = time.time() - start_time
        else:
            elapsed_seconds = 0.0
        output_subfolder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
        csv_path = export_golden_dataset_csv(payload, output_subfolder)
        metrics_csv_path, markdown_content, final_report_content = evaluate_and_report_golden_dataset(
            csv_path=csv_path, payload=payload, output_folder=output_subfolder, elapsed_seconds=elapsed_seconds
        )
        metrics_md_path = output_subfolder / "golden_dataset_metrics.md"
        with open(metrics_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        final_report_path = output_subfolder / "final_report.md"
        with open(final_report_path, "w", encoding="utf-8") as f:
            f.write(final_report_content)
        if state is not None:
            files = state.get("files", {})
            files["/golden_dataset_metrics.md"] = create_file_data(markdown_content)
            files["/final_report.md"] = create_file_data(final_report_content)
            state["files"] = files
        return (
            f"**CSV exported to:** `{csv_path}`\n\n**Metrics CSV:** `{metrics_csv_path}`\n\n"
            f"**Metrics Markdown:** `{metrics_md_path}`\n\n**Final Report:** `{final_report_path}`\n\n"
            f"All files have been generated successfully!"
        )
    except Exception as e:
        return f"**Error exporting or evaluating golden dataset:** {e}"


@tool(parse_docstring=True)
def trigger_dataset_evaluation(
    file_path: str,
    state: Annotated[dict, InjectedState] = None,
) -> str:
    """Evaluate a generated golden dataset CSV to compute quality metrics.

    Run this tool only after you have successfully generated a golden dataset
    and received the CSV file path locally in your output folder. This runs a heavy
    evaluation script to compute Similarity, Relevance, Coherence, and Groundedness.

    For new datasets, prefer ``finalize_golden_dataset_output``, which exports the CSV
    and runs this evaluation in order. Use this tool to re-run metrics on an existing CSV.

    Args:
        file_path: The path to the CSV file to evaluate (e.g., "./output/golden_dataset.csv").
        state: LangGraph state

    Returns:
        The result of the quality metric evaluation, including the path to the scored dataset.
    """
    from research_agent.skills.golden_dataset.pipeline import (
        GOLDEN_DATASET_TARGET_ID,
        evaluate_golden_dataset_csv_file,
    )

    if state is not None:
        requested_target = state.get("target")
        if requested_target != GOLDEN_DATASET_TARGET_ID:
            return (
                "ERROR: `trigger_dataset_evaluation` is only available when the active target is `golden-dataset`."
                "Use the standard research flow when no target is selected."
            )

    return evaluate_golden_dataset_csv_file(file_path)
