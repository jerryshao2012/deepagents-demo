from __future__ import annotations

import tempfile
from pathlib import Path

from langchain_core.embeddings import FakeEmbeddings

from research_agent.utils.retrieval import (
    chunk_markdown_by_boundaries,
    get_document_chunks,
    build_index,
    load_or_build_index,
)


def test_chunk_markdown_by_boundaries() -> None:
    content = (
        "Some general info.\n"
        "<!-- page: 1 -->\n"
        "## Page 1\n"
        "This is text on page 1.\n"
        "<!-- heading: 2 -->\n"
        "Heading text.\n"
        "<!-- slide: 3 -->\n"
        "Slide content."
    )
    chunks = chunk_markdown_by_boundaries(content)
    assert len(chunks) == 4
    assert chunks[0]["page"] is None
    assert chunks[1]["page"] == 1
    assert chunks[2]["page"] == 1
    assert chunks[2]["heading"] == "Heading level 2"
    assert chunks[3]["page"] == 3
    assert chunks[3]["locator"] == "Slide 3"


def test_get_document_chunks_splits_large_text() -> None:
    large_text = "word " * 1000
    chunks = get_document_chunks(large_text)
    assert len(chunks) > 1


def test_build_and_load_index() -> None:
    embeddings = FakeEmbeddings(size=1536)

    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_dir = Path(tmp_dir) / "raw"
        raw_dir.mkdir()

        doc_file = raw_dir / "report.pdf.md"
        doc_file.write_text("<!-- page: 1 -->\n## Page 1\nRevenue is $100M.", encoding="utf-8")

        index_dir = Path(tmp_dir) / "index"

        # Build index
        vectorstore = build_index(raw_dir, index_dir, embeddings)
        assert vectorstore is not None
        assert (index_dir / "index.faiss").exists()

        # Load index
        loaded = load_or_build_index(raw_dir, index_dir, embeddings)
        assert loaded is not None

        # Test similarity search
        results = loaded.similarity_search("Revenue", k=1)
        assert len(results) == 1
        assert "Revenue is $100M" in results[0].page_content
        assert results[0].metadata["source_path"] == "/raw/report.pdf.md"
        assert results[0].metadata["page"] == 1
