"""Frontend Slides Skill - HTML Presentation Generator.

This module provides tools for generating self-contained HTML slide decks
from markdown-style content with dynamic styling and animations.
"""

import html
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import InjectedState, tool

from research_agent.tools import _get_skill_registry

# Constants
REPORTS_OUTPUT_FOLDER = "reports"


def _normalize_path_for_filesystem_tools(file_path: str) -> str:
    """Normalize file paths for filesystem tools compatibility."""
    return file_path.replace("\\", "/")


_SKILL_DIR = Path(__file__).resolve().parent


def _load_style_presets() -> dict[str, dict[str, str]]:
    """Load style presets from STYLE_PRESETS.md in the frontend_slides skill directory.
    
    This dynamically reads and parses the STYLE_PRESETS.md file to extract
    font and color configurations, allowing easy customization without code changes.
    """
    registry = _get_skill_registry()
    presets_md = registry.read_supporting_file("frontend_slides", "STYLE_PRESETS.md")

    if not presets_md:
        # Fallback to hardcoded presets if file not found
        print("Warning: STYLE_PRESETS.md not found, using fallback presets")
        return _get_fallback_style_presets()

    # Parse the markdown to extract style presets
    return _parse_style_presets_from_markdown(presets_md)


def _get_fallback_style_presets() -> dict[str, dict[str, str]]:
    """Fallback hardcoded presets if STYLE_PRESETS.md cannot be loaded."""
    return {
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


def _parse_style_presets_from_markdown(markdown_content: str) -> dict[str, dict[str, str]]:
    """Parse STYLE_PRESETS.md markdown to extract style preset configurations.
    
    Extracts font information and color variables from each preset section.
    Maps the markdown structure to the format expected by the HTML generator.
    
    Args:
        markdown_content: Raw content of STYLE_PRESETS.md
        
    Returns:
        Dictionary mapping preset names to their configuration dictionaries
    """
    presets = {}

    # Split into sections by preset headers (### Number. Name)
    section_pattern = re.compile(r'^###\s+\d+\.\s+(.+?)$', re.MULTILINE)
    sections = list(section_pattern.finditer(markdown_content))

    for i, section_match in enumerate(sections):
        preset_name = section_match.group(1).strip()

        # Get content until next section or end of file
        start_pos = section_match.end()
        end_pos = sections[i + 1].start() if i + 1 < len(sections) else len(markdown_content)
        section_content = markdown_content[start_pos:end_pos]

        # Extract typography info
        fonts = _extract_fonts_from_section(section_content)

        # Extract colors from CSS code block
        colors = _extract_colors_from_css(section_content)

        # Combine into preset config
        if fonts or colors:
            presets[preset_name] = {**fonts, **colors}

    # If no presets were parsed, return fallback
    if not presets:
        print("Warning: Could not parse any presets from STYLE_PRESETS.md, using fallback")
        return _get_fallback_style_presets()

    return presets


def _extract_fonts_from_section(section_content: str) -> dict[str, str]:
    """Extract font information from a preset section.
    
    Looks for Typography section and extracts display/body fonts,
    then constructs Google Fonts URL.
    """
    result = {}

    # Find Typography section
    typography_match = re.search(r'\*\*Typography:\*\*(.*?)(?=\n\*\*|$)', section_content, re.DOTALL)
    if not typography_match:
        return result

    typography_text = typography_match.group(1)

    # Extract display font
    display_match = re.search(r'Display:\s*[`\']([^`\']+)[`\']', typography_text)
    body_match = re.search(r'Body:\s*[`\']([^`\']+)[`\']', typography_text)

    if display_match and body_match:
        display_font = display_match.group(1).split(' ')[0]  # Get first word (font family)
        body_font = body_match.group(1).split(' ')[0]

        # Construct Google Fonts URL
        # Handle special cases where fonts might not be on Google Fonts
        if display_font == body_font:
            font_href = f"https://fonts.googleapis.com/css2?family={display_font.replace(' ', '+')}:wght@400;500;700;800&display=swap"
        else:
            font_href = f"https://fonts.googleapis.com/css2?family={display_font.replace(' ', '+')}:wght@700;800&family={body_font.replace(' ', '+')}:wght@400;500&display=swap"

        result['font_href'] = font_href
        result['font_display'] = f'"{display_font}", sans-serif'
        result['font_body'] = f'"{body_font}", sans-serif'

    return result


def _extract_colors_from_css(section_content: str) -> dict[str, str]:
    """Extract color variables from CSS code block in a preset section.
    
    Parses the :root CSS block and maps variables to the format needed
    by the HTML template generator.
    """
    result = {}

    # Find CSS code block
    css_match = re.search(r'```css\s*:root\s*\{(.*?)}\s*```', section_content, re.DOTALL)
    if not css_match:
        return result

    css_content = css_match.group(1)

    # Parse CSS variables
    css_vars = {}
    for var_match in re.finditer(r'--([\w-]+):\s*([^;]+);', css_content):
        var_name = var_match.group(1)
        var_value = var_match.group(2).strip()
        css_vars[var_name] = var_value

    # Map CSS variables to template variables based on common patterns
    # Different presets use different naming conventions, so we need flexible mapping

    # Background colors
    if 'bg-primary' in css_vars:
        result['bg_primary'] = css_vars['bg-primary']
    elif 'bg-dark' in css_vars:
        result['bg_primary'] = css_vars['bg-dark']

    if 'bg-secondary' in css_vars:
        result['bg_secondary'] = css_vars['bg-secondary']
    elif 'bg-gradient' in css_vars:
        # Use first color from gradient as secondary
        gradient_match = re.search(r'linear-gradient\([^,]+,\s*(\S+)', css_vars.get('bg-gradient', ''))
        if gradient_match:
            result['bg_secondary'] = gradient_match.group(1)

    # Text colors
    if 'text-primary' in css_vars:
        result['text_primary'] = css_vars['text-primary']

    if 'text-secondary' in css_vars:
        result['text_secondary'] = css_vars['text-secondary']
    elif 'text-on-card' in css_vars:
        result['text_secondary'] = css_vars['text-on-card']

    # Accent colors - use the most prominent accent
    accent_candidates = ['accent', 'accent-blue', 'accent-neon', 'accent-warm', 'card-bg']
    for candidate in accent_candidates:
        if candidate in css_vars:
            result['accent'] = css_vars[candidate]
            break

    # Surface colors (for cards/containers)
    if 'card-bg' in css_vars:
        result['surface'] = css_vars['card-bg']
        result['surface_alt'] = f"rgba({css_vars.get('text-primary', '#ffffff').lstrip('#')}, 0.1)"
    elif 'bg-white' in css_vars:
        result['surface'] = css_vars['bg-white']
        result['surface_alt'] = 'rgba(255, 255, 255, 0.1)'

    # Generate soft accent version if accent is defined
    if 'accent' in result:
        accent_color = result['accent']
        # Convert hex to rgba with transparency
        if accent_color.startswith('#'):
            hex_color = accent_color.lstrip('#')
            if len(hex_color) == 6:
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                result['accent_soft'] = f"rgba({r}, {g}, {b}, 0.2)"

    return result


# Initialize style presets (loaded at module import)
_STYLE_PRESETS = _load_style_presets()


def _load_viewport_css() -> str:
    """Load viewport CSS using the skill registry for dynamic access."""
    registry = _get_skill_registry()
    content = registry.read_supporting_file("frontend_slides", "viewport-base.css")
    if content:
        return content

    # Fallback to direct file read if registry fails
    viewport_path = _SKILL_DIR / "viewport-base.css"
    return viewport_path.read_text(encoding="utf-8")


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "presentation"


def _clean_text(value: str) -> str:
    # Avoid stripping images by checking for '!' before link syntax
    def replace_link(match: Any) -> str:
        if match.group(0).startswith('!'):
            return str(match.group(0))
        return str(match.group(1))

    value = re.sub(r"!?\[(.*?)]\((.*?)\)", replace_link, value)
    value = value.replace("***", " ").replace("**", "").replace("__", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _parse_bullets(value: str) -> list[str]:
    bullets: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        bullet_match = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        if bullet_match:
            bullets.append(_clean_text(bullet_match.group(1)))
    return bullets


def _parse_sections(presentation_markdown: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"^#\s*\[Slide\s+\d+]\s*Title:\s*(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(presentation_markdown))
    if not matches:
        return []

    slides: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        title = _clean_text(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(presentation_markdown)
        section_text = presentation_markdown[start:end].strip()

        images = []
        for img_match in re.finditer(r"!\[(.*?)]\((.*?)\)", section_text):
            images.append({"alt": img_match.group(1), "src": img_match.group(2)})

        # Remove images from text so they don't appear as empty bullets/paragraphs
        section_text = re.sub(r"!\[(.*?)]\((.*?)\)", "", section_text)

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
                if current_label:
                    fields.setdefault(current_label, [])
                    trailing = label_match.group(2).strip()
                    if trailing:
                        fields[current_label].append(trailing)
                continue
            if current_label:
                fields.setdefault(current_label, []).append(stripped)
            else:
                unlabeled_lines.append(stripped)

        headline = _clean_text("\n".join(fields.get("headline", [])))
        subtitle = _clean_text("\n".join(fields.get("subtitle", [])))
        contact = _clean_text("\n".join(fields.get("contact", [])))
        callout = _clean_text("\n".join(fields.get("callout", [])))

        bullets = _parse_bullets("\n".join(unlabeled_lines))
        bullets.extend(_parse_bullets("\n".join(fields.get("body", []))))

        paragraph_sources = [
            _clean_text("\n".join(fields.get("body", []))),
            _clean_text("\n".join(unlabeled_lines)),
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
                "images": images[:2],
            }
        )

    return slides


def _get_animation_css(animation_feeling: str) -> str:
    if animation_feeling == "dramatic":
        return """
      .reveal {
        opacity: 0;
        transform: scale(0.9);
        transition: opacity 1.2s ease-out, transform 1.2s cubic-bezier(0.16, 1, 0.3, 1);
      }
      .slide.visible .reveal {
        opacity: 1;
        transform: scale(1);
      }
      .reveal:nth-child(1) { transition-delay: 0.1s; }
      .reveal:nth-child(2) { transition-delay: 0.2s; }
      .reveal:nth-child(3) { transition-delay: 0.3s; }
      .reveal:nth-child(4) { transition-delay: 0.4s; }
      .reveal:nth-child(5) { transition-delay: 0.5s; }
"""
    elif animation_feeling == "techy":
        return """
      .reveal {
        opacity: 0;
        transform: translateX(-50px);
        transition: opacity 0.6s, transform 0.6s cubic-bezier(0.16, 1, 0.3, 1);
      }
      .slide.visible .reveal {
        opacity: 1;
        transform: translateX(0);
      }
      .slide-shell::after {
        content: ""; position: absolute; inset: 0;
        background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
        background-size: 50px 50px; pointer-events: none;
      }
      .reveal:nth-child(1) { transition-delay: 0.08s; }
      .reveal:nth-child(2) { transition-delay: 0.16s; }
      .reveal:nth-child(3) { transition-delay: 0.24s; }
      .reveal:nth-child(4) { transition-delay: 0.32s; }
      .reveal:nth-child(5) { transition-delay: 0.4s; }
"""
    elif animation_feeling == "playful":
        return """
      .reveal {
        opacity: 0;
        transform: translateY(40px);
        transition: opacity 0.6s, transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
      }
      .slide.visible .reveal {
        opacity: 1;
        transform: translateY(0);
      }
      .reveal:nth-child(1) { transition-delay: 0.1s; }
      .reveal:nth-child(2) { transition-delay: 0.2s; }
      .reveal:nth-child(3) { transition-delay: 0.3s; }
      .reveal:nth-child(4) { transition-delay: 0.4s; }
      .reveal:nth-child(5) { transition-delay: 0.5s; }
"""
    elif animation_feeling == "calm":
        return """
      .reveal {
        opacity: 0;
        filter: blur(10px);
        transition: opacity 1s, filter 1s ease-out;
      }
      .slide.visible .reveal {
        opacity: 1;
        filter: blur(0);
      }
      .reveal:nth-child(1) { transition-delay: 0.1s; }
      .reveal:nth-child(2) { transition-delay: 0.2s; }
      .reveal:nth-child(3) { transition-delay: 0.3s; }
      .reveal:nth-child(4) { transition-delay: 0.4s; }
      .reveal:nth-child(5) { transition-delay: 0.5s; }
"""
    elif animation_feeling == "editorial":
        return """
      .reveal {
        opacity: 0;
        transform: translateY(20px);
        transition: opacity 0.8s ease, transform 0.8s ease;
      }
      .slide.visible .reveal {
        opacity: 1;
        transform: translateY(0);
      }
      .reveal:nth-child(1) { transition-delay: 0.1s; }
      .reveal:nth-child(2) { transition-delay: 0.3s; }
      .reveal:nth-child(3) { transition-delay: 0.5s; }
      .reveal:nth-child(4) { transition-delay: 0.7s; }
      .reveal:nth-child(5) { transition-delay: 0.9s; }
"""
    else:  # professional
        return """
      .reveal {
        opacity: 0;
        transform: translateY(24px);
        transition: opacity 0.55s ease, transform 0.55s ease;
      }
      .slide.visible .reveal {
        opacity: 1;
        transform: translateY(0);
      }
      .reveal:nth-child(1) { transition-delay: 0.08s; }
      .reveal:nth-child(2) { transition-delay: 0.16s; }
      .reveal:nth-child(3) { transition-delay: 0.24s; }
      .reveal:nth-child(4) { transition-delay: 0.32s; }
      .reveal:nth-child(5) { transition-delay: 0.4s; }
"""


def _get_inline_editing_css() -> str:
    return """
      /* Inline Editing Styles */
      .edit-hotzone {
        position: fixed;
        top: 0;
        left: 0;
        width: 80px;
        height: 80px;
        z-index: 10000;
        cursor: pointer;
      }
      .edit-toggle {
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.3s ease;
        z-index: 10001;
        position: fixed;
        top: 20px;
        left: 20px;
        background: var(--surface);
        border: 1px solid var(--surface-alt);
        color: var(--text-primary);
        width: 40px;
        height: 40px;
        border-radius: 50%;
        font-size: 1.2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
      }
      .edit-toggle.show,
      .edit-toggle.active {
        opacity: 1;
        pointer-events: auto;
      }
      .edit-banner {
        position: fixed;
        bottom: 20px;
        left: 50%;
        transform: translateX(-50%) translateY(100px);
        background: var(--surface);
        color: var(--text-primary);
        padding: 12px 24px;
        border-radius: 50px;
        display: flex;
        gap: 16px;
        align-items: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        border: 1px solid var(--surface-alt);
        z-index: 10002;
        transition: transform 0.3s ease;
      }
      .edit-banner.show {
        transform: translateX(-50%) translateY(0);
      }
      .edit-banner button {
        background: var(--accent);
        color: var(--bg-primary);
        border: none;
        padding: 6px 16px;
        border-radius: 20px;
        cursor: pointer;
        font-weight: bold;
      }
      [contenteditable="true"] {
        outline: 1px dashed var(--accent-soft);
        min-width: 1em;
        display: inline-block;
      }
      [contenteditable="true"]:focus {
        outline: 2px solid var(--accent);
      }
"""


def _get_inline_editing_js() -> str:
    return """
      class InlineEditor {
        constructor() {
          this.isActive = false;
          this.editableSelectors = 'h1, h2, h3, p, li, .callout, .kicker, .eyebrow, .subtitle';
          this.setupAutoSave();
          this.setupInteractions();
        }

        setupInteractions() {
          const toggleBtn = document.getElementById("editToggle");
          if(toggleBtn) {
            toggleBtn.addEventListener("click", () => this.toggleEditMode());
          }

          const hotzone = document.querySelector(".edit-hotzone");
          const editToggle = document.getElementById("editToggle");
          let hideTimeout = null;

          if(hotzone && editToggle) {
            hotzone.addEventListener("mouseenter", () => {
              clearTimeout(hideTimeout);
              editToggle.classList.add("show");
            });
            hotzone.addEventListener("mouseleave", () => {
              hideTimeout = setTimeout(() => {
                if (!this.isActive) editToggle.classList.remove("show");
              }, 400);
            });
            editToggle.addEventListener("mouseenter", () => {
              clearTimeout(hideTimeout);
            });
            editToggle.addEventListener("mouseleave", () => {
              hideTimeout = setTimeout(() => {
                if (!this.isActive) editToggle.classList.remove("show");
              }, 400);
            });
            hotzone.addEventListener("click", () => {
              this.toggleEditMode();
            });
          }

          document.addEventListener("keydown", (e) => {
            if (
              (e.key === "e" || e.key === "E") &&
              !e.target.getAttribute("contenteditable")
            ) {
              this.toggleEditMode();
            }
          });
        }

        toggleEditMode() {
          this.isActive = !this.isActive;
          document.body.classList.toggle('edit-active', this.isActive);
          const toggleBtn = document.getElementById('editToggle');
          if (toggleBtn) {
              toggleBtn.classList.toggle('active', this.isActive);
          }

          const els = document.querySelectorAll(this.editableSelectors);
          els.forEach(el => {
              if (this.isActive) {
                  el.setAttribute('contenteditable', 'true');
              } else {
                  el.removeAttribute('contenteditable');
              }
          });

          let banner = document.querySelector('.edit-banner');
          if (this.isActive) {
              if (!banner) {
                  banner = document.createElement('div');
                  banner.className = 'edit-banner';
                  banner.innerHTML = `<span>✏️ Edit Mode Active</span> <button onclick="editor.exportFile()">Save HTML</button>`;
                  document.body.appendChild(banner);
              }
              setTimeout(() => banner.classList.add('show', 'active'), 10);
          } else if (banner) {
              banner.classList.remove('show', 'active');
          }
        }

        setupAutoSave() {
          let timeout;
          document.addEventListener('input', (e) => {
              if (e.target.getAttribute('contenteditable')) {
                  clearTimeout(timeout);
                  timeout = setTimeout(() => {
                      console.log('Auto-saved presentation draft');
                  }, 1000);
              }
          });
        }

        exportFile() {
          const editableEls = Array.from(document.querySelectorAll('[contenteditable]'));
          editableEls.forEach(el => el.removeAttribute('contenteditable'));
          document.body.classList.remove('edit-active');

          const editToggle = document.getElementById('editToggle');
          const editBanner = document.querySelector('.edit-banner');
          editToggle?.classList.remove('active', 'show');
          editBanner?.classList.remove('active', 'show');

          const html = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;

          document.body.classList.add('edit-active');
          editableEls.forEach(el => el.setAttribute('contenteditable', 'true'));
          editToggle?.classList.add('active', 'show');
          editBanner?.classList.add('active', 'show');

          const blob = new Blob([html], { type: 'text/html' });
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'presentation.html';
          a.click();
          URL.revokeObjectURL(a.href);
        }
      }
      const editor = new InlineEditor();
"""


def _build_html(
        deck_title: str,
        slides: list[dict[str, Any]],
        style_preset: str,
        animation_feeling: str = "professional",
        enable_inline_editing: bool = False,
) -> str:
    """Build HTML presentation using dynamic viewport CSS and style presets.
    
    This function generates the actual HTML file. The agent should read the
    supporting markdown files (html-template.md, animation-patterns.md) to
    understand the architecture and make informed decisions about styling
    and animations before calling this tool.
    
    Args:
        deck_title: Title for the presentation
        slides: List of slide data dictionaries
        style_preset: Name of the style preset (e.g., "Bold Signal")
        animation_feeling: Desired animation feeling (dramatic/techy/playful/professional/calm/editorial)
        enable_inline_editing: Whether to include in-browser text editing functionality.
    """
    # Load viewport CSS dynamically from skill registry
    # (This is mandatory CSS that must be included in every presentation)
    viewport_css = _load_viewport_css()

    # Get style preset configuration (parsed from STYLE_PRESETS.md at init)
    preset = _STYLE_PRESETS.get(
        style_preset, _STYLE_PRESETS["Creative Voltage"]
    )

    slide_markup: list[str] = []
    for index, slide in enumerate(slides, start=1):
        title = html.escape(str(slide["title"]))
        headline = html.escape(str(slide["headline"]))
        subtitle = html.escape(str(slide["subtitle"]))
        contact = html.escape(str(slide["contact"]))
        callout = html.escape(str(slide["callout"]))
        bullets = [html.escape(str(item)) for item in slide.get("bullets", [])]
        paragraphs = [html.escape(str(item)) for item in slide.get("paragraphs", [])]
        images = slide.get("images", [])

        is_title_slide = index == 1
        body_parts: list[str] = []
        if headline:
            body_parts.append(f'<p class="eyebrow reveal">{headline}</p>')
        if subtitle:
            body_parts.append(f'<p class="subtitle reveal">{subtitle}</p>')

        if images and isinstance(images, list):
            for img in images:
                body_parts.append(
                    f'<img src="{html.escape(img["src"])}" alt="{html.escape(img["alt"])}" class="slide-image reveal" />')

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

    animation_css = _get_animation_css(animation_feeling)
    inline_editing_css = _get_inline_editing_css() if enable_inline_editing else ""
    inline_editing_html = '<div class="edit-hotzone"></div>\n    <button class="edit-toggle" id="editToggle" title="Edit mode (E)">✏️</button>' if enable_inline_editing else ""
    inline_editing_js = _get_inline_editing_js() if enable_inline_editing else ""

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

      .slide-image {{
        max-width: 100%;
        max-height: min(50vh, 400px);
        object-fit: contain;
        border-radius: 8px;
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

{animation_css}
{inline_editing_css}

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
    {inline_editing_html}
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
          this.setupTouchNav();
          this.setupWheelNav();
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
            if (event.target.getAttribute("contenteditable")) return;
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

        setupTouchNav() {{
          let touchStartY = 0;
          let touchStartX = 0;
          window.addEventListener('touchstart', e => {{
            touchStartY = e.changedTouches[0].screenY;
            touchStartX = e.changedTouches[0].screenX;
          }}, {{passive: true}});
          window.addEventListener('touchend', e => {{
            const touchEndY = e.changedTouches[0].screenY;
            const touchEndX = e.changedTouches[0].screenX;
            const diffY = touchStartY - touchEndY;
            const diffX = touchStartX - touchEndX;
            if (Math.abs(diffX) > Math.abs(diffY)) {{
                if (diffX > 50) this.goToSlide(Math.min(this.currentSlide + 1, this.slides.length - 1));
                if (diffX < -50) this.goToSlide(Math.max(this.currentSlide - 1, 0));
            }} else {{
                if (diffY > 50) this.goToSlide(Math.min(this.currentSlide + 1, this.slides.length - 1));
                if (diffY < -50) this.goToSlide(Math.max(this.currentSlide - 1, 0));
            }}
          }}, {{passive: true}});
        }}

        setupWheelNav() {{
          let wheelTimeout = false;
          window.addEventListener('wheel', (e) => {{
            if (wheelTimeout) return;
            if (Math.abs(e.deltaY) > 30) {{
              if (e.deltaY > 0) {{
                this.goToSlide(Math.min(this.currentSlide + 1, this.slides.length - 1));
              }} else {{
                this.goToSlide(Math.max(this.currentSlide - 1, 0));
              }}
              wheelTimeout = true;
              setTimeout(() => {{ wheelTimeout = false; }}, 800);
            }}
          }}, {{passive: true}});
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

{inline_editing_js}
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
        animation_feeling: str = "professional",
        enable_inline_editing: bool = False,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Generate a self-contained HTML slide deck from markdown-style slide content.

    Use this tool when the user wants an actual browser-ready presentation rather than
    plain markdown. It accepts content in the frontend-slides format, such as:
    ``# [Slide 1] Title: ...`` followed by ``**Headline:**``, ``**Subtitle:**``,
    ``**Body:**``, bullet lists, and optional ``**Callout:**`` blocks.

    **Before calling this tool, read these supporting files for guidance:**
    - Use `read_skill_supporting_file('frontend_slides', 'html-template.md')` to understand HTML architecture
    - Use `read_skill_supporting_file('frontend_slides', 'animation-patterns.md')` for animation reference
    - Use `read_skill_supporting_file('frontend_slides', 'viewport-base.css')` for mandatory CSS rules

    These files provide the architectural patterns and best practices you should follow when
    structuring your presentation content and choosing animation styles.

    Args:
        presentation_markdown: Markdown-style slide content to convert into HTML slides.
        output_filename: Optional filename for the generated HTML. Saved under OUTPUT_FOLDER.
        deck_title: Optional browser title for the presentation. Defaults to the first slide title.
        style_preset: Visual preset name. Supported: Bold Signal, Electric Studio, Creative Voltage, Dark Botanical, Notebook Tabs, Pastel Geometry, Split Pastel, Vintage Editorial, Neon Cyber, Terminal Green, Swiss Modern, Paper & Ink.
        animation_feeling: Animation style feeling. Options: dramatic (cinematic), techy (futuristic), playful (bouncy), professional (subtle), calm (gentle), editorial (staggered).
        enable_inline_editing: Whether to include in-browser text editing capabilities. Options: True / False.
        state: LangGraph state (injected automatically, do not supply).

    Returns:
        Confirmation containing the generated file path and slide count, or an error message.
    """
    # Parse the markdown content into structured slide data
    slides = _parse_sections(presentation_markdown)
    if not slides:
        return (
            "Error: No slides were detected. Use headings like "
            "`# [Slide 1] Title: My Slide` in the presentation_markdown input."
        )

    # Build HTML using the template engine with dynamic resources
    resolved_title = deck_title or str(slides[0]["title"])
    html_content = _build_html(resolved_title, slides, style_preset, animation_feeling, enable_inline_editing)

    # Save to output folder
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

    # Update state if available
    if state is not None:
        try:
            from deepagents.backends.utils import (
                create_file_data,
            )

            files = state.get("files", {})
            files[f"/{safe_name}"] = create_file_data(html_content)
            state["files"] = files
        except ImportError:
            # Fallback: manually create file data structure
            files = state.get("files", {})
            files[f"/{safe_name}"] = {
                "content": html_content,
                "type": "text/html",
            }
            state["files"] = files

    normalized_path = _normalize_path_for_filesystem_tools(str(output_path))
    return (
        f"Generated `{style_preset}` HTML presentation with {len(slides)} slide(s) at "
        f"`{normalized_path}`."
    )


@tool("frontend-slides-export-pdf", parse_docstring=True)
def frontend_slides_export_pdf(
        html_file_path: str,
        output_pdf_path: str | None = None,
        compact: bool = False,
) -> str:
    """Export an HTML presentation to PDF.

    Use this tool when the user wants to convert a generated HTML presentation into a PDF file.
    This calls the `scripts/export-pdf.sh` script, which uses Playwright to capture screenshots
    of each slide and compile them. Note that animations are not preserved in the PDF.

    Args:
        html_file_path: The absolute path to the generated HTML presentation file.
        output_pdf_path: Optional absolute path for the output PDF. If not provided, it saves next to the HTML file.
        compact: Whether to render the PDF in compact mode (1280x720 instead of 1920x1080) for smaller file sizes.
        
    Returns:
        The path to the generated PDF file or an error message.
    """
    script_path = _SKILL_DIR / "scripts" / "export-pdf.sh"

    cmd = ["bash", str(script_path), html_file_path]
    if output_pdf_path:
        cmd.append(output_pdf_path)
    if compact:
        cmd.append("--compact")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully exported PDF.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error exporting PDF: {e.stderr}\\n\\n{e.stdout}"


@tool("frontend-slides-deploy", parse_docstring=True)
def frontend_slides_deploy(
        html_file_path: str,
) -> str:
    """Deploy an HTML presentation to a live Vercel URL.

    Use this tool when the user wants to share the presentation online.
    This calls the `scripts/deploy.sh` script which deploys the presentation to Vercel.
    The user must have Vercel CLI installed and be logged in.

    Args:
        html_file_path: The absolute path to the generated HTML presentation file or directory.

    Returns:
        The deployment output including the live URL, or an error message.
    """
    script_path = _SKILL_DIR / "scripts" / "deploy.sh"

    cmd = ["bash", str(script_path), html_file_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully deployed presentation.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error deploying presentation: {e.stderr}\\n\\n{e.stdout}"


@tool("frontend-slides-extract-pptx", parse_docstring=True)
def frontend_slides_extract_pptx(
        pptx_file_path: str,
        output_dir: str | None = None,
) -> str:
    """Extract content and images from a PowerPoint (.pptx) file.

    Use this tool when the user provides a .pptx file and wants to convert it
    into an HTML presentation. This runs `scripts/extract-pptx.py` which returns
    a JSON structure containing slides, text, and images.

    Args:
        pptx_file_path: The absolute path to the input PowerPoint file.
        output_dir: Optional absolute path to the directory where extracted data and images should be saved.

    Returns:
        The output of the extraction process, including the path to the extracted JSON.
    """
    script_path = _SKILL_DIR / "scripts" / "extract-pptx.py"

    cmd = ["python3", str(script_path), pptx_file_path]
    if output_dir:
        cmd.append(output_dir)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully extracted PowerPoint content.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error extracting PowerPoint content: {e.stderr}\\n\\n{e.stdout}"
