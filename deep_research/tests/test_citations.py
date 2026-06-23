"""Tests for content extraction page markers and citation parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_agent.utils.content_extractors import _render_page_chunk
from thread_wiki.models import SourceCitation, WikiQueryResult
from thread_wiki.service import _extract_citations


# ── _render_page_chunk ─────────────────────────────────────────────────────


class TestRenderPageChunk:
    """Tests for the page chunk renderer helper."""

    def test_emits_page_comment_and_heading(self) -> None:
        result = _render_page_chunk(3, "Some content here.")
        assert "<!-- page: 3 -->" in result
        assert "## Page 3" in result
        assert "Some content here." in result

    def test_strips_whitespace_from_body(self) -> None:
        result = _render_page_chunk(1, "   padded content   ")
        assert "<!-- page: 1 -->" in result
        assert "padded content" in result


# ── _extract_pdf_text ───────────────────────────────────────────────────


@pytest.fixture()
def mock_extractors_modules(monkeypatch):
    """Mock pymupdf4llm and pypdf so _extract_pdf_text can be tested without
    the actual libraries installed.  Returns (mock_pymupdf, mock_pypdf)."""
    import sys

    mock_pymupdf = MagicMock()
    mock_pypdf = MagicMock()

    # Stash originals so we can restore them.
    orig_pymupdf = sys.modules.get("pymupdf4llm")
    orig_pypdf = sys.modules.get("pypdf")

    sys.modules["pymupdf4llm"] = mock_pymupdf
    sys.modules["pypdf"] = mock_pypdf

    # Reload the module under test so the lazy `import pymupdf4llm` inside
    # _extract_pdf_text picks up our mock.
    import importlib
    import research_agent.utils.content_extractors as mod
    importlib.reload(mod)

    yield mock_pymupdf, mock_pypdf, mod

    # Restore originals.
    if orig_pymupdf is None:
        sys.modules.pop("pymupdf4llm", None)
    else:
        sys.modules["pymupdf4llm"] = orig_pymupdf
    if orig_pypdf is None:
        sys.modules.pop("pypdf", None)
    else:
        sys.modules["pypdf"] = orig_pypdf
    importlib.reload(mod)


class TestExtractPdfTextPageChunks:
    """Tests for PDF extraction with page_chunks=True."""

    def test_page_chunks_list_with_metadata_page(self, mock_extractors_modules) -> None:
        """When pymupdf4llm returns page-chunk dicts with metadata.page,
        each chunk should get a <!-- page: N --> marker."""
        mock_pymupdf, _, mod = mock_extractors_modules
        chunks = [
            {"metadata": {"page": 5, "total_page": 10}, "content": "Page five text."},
            {"metadata": {"page": 6, "total_page": 10}, "content": "Page six text."},
        ]
        mock_pymupdf.to_markdown.return_value = chunks
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))

        assert "<!-- page: 5 -->" in result
        assert "<!-- page: 6 -->" in result
        assert "Page five text." in result
        assert "Page six text." in result
        assert "## Page 5" in result
        assert "## Page 6" in result

    def test_page_chunks_list_without_metadata(self, mock_extractors_modules) -> None:
        """When chunks are dicts but lack metadata.page, fall back to 1-based index."""
        mock_pymupdf, _, mod = mock_extractors_modules
        chunks = [
            {"content": "First chunk"},
            {"content": "Second chunk"},
        ]
        mock_pymupdf.to_markdown.return_value = chunks
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))

        assert "<!-- page: 1 -->" in result
        assert "<!-- page: 2 -->" in result

    def test_page_chunks_string_items(self, mock_extractors_modules) -> None:
        """When chunks are plain strings (not dicts), enumerate with index."""
        mock_pymupdf, _, mod = mock_extractors_modules
        chunks = ["First page text.", "Second page text."]
        mock_pymupdf.to_markdown.return_value = chunks
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))

        assert "<!-- page: 1 -->" in result
        assert "<!-- page: 2 -->" in result

    def test_flat_string_return(self, mock_extractors_modules) -> None:
        """When pymupdf4llm returns a flat string (older version),
        the content passes through without page markers."""
        mock_pymupdf, _, mod = mock_extractors_modules
        mock_pymupdf.to_markdown.return_value = "Flat markdown content\nwith no page markers."
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))

        assert "Flat markdown content" in result
        assert "<!-- page:" not in result  # no page markers from flat string

    def test_empty_result_returns_empty_string(self, mock_extractors_modules) -> None:
        """When pymupdf4llm returns empty string, the result is empty
        (pypdf fallback is only triggered on exception)."""
        mock_pymupdf, _, mod = mock_extractors_modules
        mock_pymupdf.to_markdown.return_value = ""
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))
        assert result == ""

    def test_exception_falls_through_to_pypdf(self, mock_extractors_modules) -> None:
        """When pymupdf4llm raises, fall through to pypdf fallback."""
        mock_pymupdf, mock_pypdf, mod = mock_extractors_modules
        mock_pymupdf.to_markdown.side_effect = RuntimeError("boom")
        mock_reader = MagicMock()
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Fallback text"
        mock_reader.pages = [mock_page1]
        mock_pypdf.PdfReader.return_value = mock_reader
        result = mod._extract_pdf_text(Path("/tmp/test.pdf"))

        assert "<!-- page: 1 -->" in result
        assert "Fallback text" in result


# ── _extract_citations ───────────────────────────────────────────────────


class TestExtractCitationsRaw:
    """Tests for raw document citation parsing."""

    def test_raw_path_with_page(self) -> None:
        answer = "Revenue was $42B (Source: /raw/report.pdf.md, p. 12)."
        citations = _extract_citations(answer)
        assert len(citations) >= 1
        raw_cits = [c for c in citations if c.kind == "raw"]
        assert len(raw_cits) >= 1
        cit = raw_cits[0]
        assert "/raw/report.pdf.md" in cit.raw_path
        assert cit.page == 12

    def test_raw_path_without_page(self) -> None:
        answer = "Based on (Source: /raw/summary.md)."
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw"]
        assert len(raw_cits) >= 1
        cit = raw_cits[0]
        assert "/raw/summary.md" in cit.raw_path
        assert cit.page is None

    def test_raw_path_page_variant_formats(self) -> None:
        """Various page annotation formats should all parse."""
        for fmt in [
            "/raw/x.pdf.md, p. 3",
            "/raw/x.pdf.md page 4",
            "/raw/x.pdf.md p5",
        ]:
            answer = f"Claim ({fmt})."
            citations = _extract_citations(answer)
            raw_cits = [c for c in citations if c.kind == "raw"]
            assert any(c.page is not None for c in raw_cits), f"Failed for format: {fmt}"

    def test_dedup_same_raw_path(self) -> None:
        answer = "Claim A (Source: /raw/doc.pdf.md, p. 5). Claim B (Source: /raw/doc.pdf.md, p. 5)."
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw" and c.raw_path == "/raw/doc.pdf.md" and c.page == 5]
        assert len(raw_cits) == 1

    def test_multiple_different_raw_paths(self) -> None:
        answer = "From /raw/a.pdf.md, p. 1 and /raw/b.docx.md, p. 3."
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw"]
        paths = {c.raw_path for c in raw_cits}
        assert len(paths) >= 2

    def test_old_style_citation_still_captured(self) -> None:
        """Old-style bare raw path without page should still work."""
        answer = "(Source: /raw/legacy.pdf.md)"
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw"]
        assert len(raw_cits) >= 1
        assert raw_cits[0].page is None

    def test_pptx_slide_citation(self) -> None:
        answer = "Slide info (Source: /raw/deck.pptx.md, Slide 4)."
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw" and c.raw_path == "/raw/deck.pptx.md"]
        assert len(raw_cits) == 1
        assert raw_cits[0].locator == "Slide 4"
        assert raw_cits[0].page is None

    def test_xlsx_sheet_row_citation(self) -> None:
        answer = "Row info (Source: /raw/data.xlsx.txt, Sheet: Cash, row 42)."
        citations = _extract_citations(answer)
        raw_cits = [c for c in citations if c.kind == "raw" and c.raw_path == "/raw/data.xlsx.txt"]
        assert len(raw_cits) == 1
        assert raw_cits[0].locator == "Sheet: Cash, row 42"
        assert raw_cits[0].page is None


class TestExtractCitationsWeb:
    """Tests for web URL citation parsing."""

    def test_sources_block_with_numbered_urls(self) -> None:
        answer = (
            "Some finding [1]. Another [2].\n\n"
            "### Sources\n"
            "[1] AI Research: https://example.com/ai\n"
            "[2] Industry Report: https://example.com/industry\n"
        )
        citations = _extract_citations(answer)
        web_cits = [c for c in citations if c.kind == "web"]
        assert len(web_cits) >= 2
        urls = {c.url for c in web_cits}
        assert "https://example.com/ai" in urls
        assert "https://example.com/industry" in urls

    def test_sources_block_title_captured_as_locator(self) -> None:
        answer = (
            "Finding [1].\n\n"
            "### Sources\n"
            "[1] Annual Report 2025: https://example.com/ar2025\n"
        )
        citations = _extract_citations(answer)
        web_cits = [c for c in citations if c.kind == "web"]
        assert any(c.locator == "Annual Report 2025" for c in web_cits)

    def test_bare_url_without_sources_block(self) -> None:
        """Bare URLs in text should be captured as web citations."""
        answer = "See https://example.com/data for more details."
        citations = _extract_citations(answer)
        web_cits = [c for c in citations if c.kind == "web"]
        assert len(web_cits) >= 1
        assert any(c.url == "https://example.com/data" for c in web_cits)

    def test_bare_url_not_deduped_with_sources_block(self) -> None:
        """URL in Sources block should not be duplicated as bare URL."""
        answer = (
            "See https://example.com/data.\n\n"
            "### Sources\n"
            "[1] Data Page: https://example.com/data\n"
        )
        citations = _extract_citations(answer)
        web_cits = [c for c in citations if c.kind == "web" and c.url == "https://example.com/data"]
        assert len(web_cits) == 1


class TestExtractCitationsSection:
    """Tests for file.md#Heading section reference parsing."""

    def test_section_ref(self) -> None:
        answer = "See policies.md#Risk-Factors for details."
        citations = _extract_citations(answer)
        section_cits = [c for c in citations if c.kind == "section"]
        assert len(section_cits) >= 1
        assert section_cits[0].raw_path == "policies.md"
        assert section_cits[0].locator == "Risk-Factors"

    def test_raw_section_ref_not_captured_as_section(self) -> None:
        """Section refs to /raw/ files should be skipped (they're raw citations)."""
        answer = "See /raw/report.pdf.md#Page 3 for the data."
        citations = _extract_citations(answer)
        section_cits = [c for c in citations if c.kind == "section"]
        assert len(section_cits) == 0


class TestExtractCitationsMixed:
    """Tests with mixed citation styles."""

    def test_mixed_raw_and_web(self) -> None:
        answer = (
            "BMO earned $42B (Source: /raw/bmo_ar2025.pdf.md, p. 15) [1].\n\n"
            "### Sources\n"
            "[1] BMO Financial Group: https://example.com/bmo\n"
        )
        citations = _extract_citations(answer)
        kinds = {c.kind for c in citations}
        assert "raw" in kinds
        assert "web" in kinds

    def test_empty_answer(self) -> None:
        citations = _extract_citations("")
        assert citations == []

    def test_answer_with_no_citations(self) -> None:
        citations = _extract_citations("This answer has no citations at all.")
        assert citations == []


# ── SourceCitation dataclass ───────────────────────────────────────────────


class TestSourceCitationModel:
    """Tests for the SourceCitation dataclass."""

    def test_raw_citation(self) -> None:
        cit = SourceCitation(kind="raw", raw_path="/raw/doc.pdf.md", page=5)
        assert cit.kind == "raw"
        assert cit.page == 5
        assert cit.url is None
        assert cit.locator is None

    def test_web_citation(self) -> None:
        cit = SourceCitation(kind="web", url="https://example.com", locator="Example Site")
        assert cit.kind == "web"
        assert cit.url == "https://example.com"

    def test_frozen(self) -> None:
        cit = SourceCitation(kind="raw", raw_path="/raw/x.md")
        with pytest.raises(AttributeError):
            cit.kind = "web"  # type: ignore[misc]


# ── WikiQueryResult compatibility ─────────────────────────────────────────


class TestWikiQueryResult:
    """Tests for updated WikiQueryResult model."""

    def test_default_empty_citations(self) -> None:
        result = WikiQueryResult(answer="test")
        assert result.sources_cited == []

    def test_with_citations(self) -> None:
        cit = SourceCitation(kind="raw", raw_path="/raw/doc.pdf.md", page=10)
        result = WikiQueryResult(answer="test", sources_cited=[cit])
        assert len(result.sources_cited) == 1
        assert result.sources_cited[0].page == 10
