"""Research Tools.

This module provides search and content processing utilities for the research agent,
using Tavily for URL discovery and fetching full webpage content.
"""

import os
from json import dumps as json_dumps

import httpx
import requests
from dotenv import load_dotenv
from langchain_core.tools import InjectedToolArg, tool
from markdownify import markdownify
from marker.convert import convert_single_pdf
from marker.models import load_all_models
from marker.output import save_markdown
from tavily import TavilyClient
from typing_extensions import Annotated, Literal

from utils import get_ssl_verify_config

# Load environment variables
load_dotenv()

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()
tavily_session = requests.Session()
tavily_session.verify = verify_ssl
tavily_client = TavilyClient(session=tavily_session)


def _run_tavily_search(query: str, max_results: int, topic: str, timeout: float = 60.0) -> dict:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not set")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "topic": topic,
        # Keep output compact; we fetch full page content ourselves.
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
    """Fetch and convert webpage content to markdown.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Webpage content as markdown
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = httpx.get(url=url,
                             headers=headers,
                             timeout=timeout,
                             verify=verify_ssl)
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as e:
        return f"Error fetching content from {url}: {str(e)}"


@tool(parse_docstring=True)
def tavily_search(
        query: str,
        max_results: Annotated[int, InjectedToolArg] = 1,
        topic: Annotated[
            Literal["general", "news", "finance"], InjectedToolArg
        ] = "general",
) -> str:
    """Search the web for information on a given query.

    Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 1)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Formatted search results with full webpage content
    """
    # Use Tavily to discover URLs
    try:
        search_results = _run_tavily_search(
            query=query,
            max_results=max_results,
            topic=topic,
        )
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 401:
            return (
                "Tavily authentication failed (401 Unauthorized)."
                "Set a valid TAVILY_API_KEY environment variable and retry"
            )
        return f"Tavily request failed with HTTP {status_code}: {e}"
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Tavily search failed: {e}"

    # Fetch full content for each URL
    result_texts = []
    for result in search_results.get("results", []):
        url = result["url"]
        title = result["title"]

        # Fetch webpage content
        content = fetch_webpage_content(url)

        result_text = f"""## {title}
**URL:** {url}

{content}

---
"""
        result_texts.append(result_text)

    # Format final response
    response = f"""🔍 Found {len(result_texts)} result(s) for '{query}':

{chr(10).join(result_texts)}"""

    return response


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


@tool(parse_docstring=True)
def read_pdf_folder(folder_path: str) -> str:
    """Read and extract text from all PDF documents in a given folder using Marker.

    Use this tool when you need to research from local PDF documents instead of or in addition to web search.

    Args:
        folder_path: The absolute or relative path to the folder containing PDF files.

    Returns:
        Extracted text from all PDFs or an error message.
    """
    if not os.path.exists(folder_path):
        return f"Error: Folder {folder_path} does not exist."

    extracted_text = []
    # Marker's convert_single_pdf expects loaded models rather than a config object
    model_lst = load_all_models()
    try:
        for file_name in os.listdir(folder_path):
            if file_name.lower().endswith('.pdf'):
                file_path = os.path.join(folder_path, file_name)
                try:
                    result = convert_single_pdf(file_path, model_lst)
                    if isinstance(result, tuple) and len(result) >= 2:
                        full_text, images = result[0], result[1]
                        out_meta = result[2] if len(result) > 2 else {}
                    else:
                        full_text = result
                        images = {}
                        out_meta = {}

                    # Save images to temporary location
                    temp_dir = os.path.join(folder_path, "__marker_temp__")
                    os.makedirs(temp_dir, exist_ok=True)
                    save_markdown(temp_dir, file_name, full_text, images, out_meta)
                    # Include image paths in output
                    extracted_text.append(f"--- Content of {file_name} ---\n{full_text}\n")
                except Exception as e:
                    extracted_text.append(f"--- Error reading {file_name}: {str(e)} ---\n")
    except Exception as e:
        return f"Error accessing folder {folder_path}: {str(e)}"

    if not extracted_text:
        return f"No PDF files found in {folder_path}."

    return "\n".join(extracted_text)


@tool(parse_docstring=True)
def generate_slide_markup(topic: str, slide_contents: list[str]) -> str:
    """Generate Markdown presentation slide markup for a given research topic, optimized for quick learning.

    Args:
        topic: The overall presentation topic.
        slide_contents: A list of content strings for each slide (e.g., 3 slides).

    Returns:
        Structured markdown for presentation slides, demarcated by `---`.
    """
    markup = f"# Presentation: {topic}\\n\\n---\\n\\n"
    for i, content in enumerate(slide_contents):
        markup += f"## Slide {i + 1}\\n\\n{content}\\n\\n---\\n\\n"
    return markup
