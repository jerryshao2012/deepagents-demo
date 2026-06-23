from __future__ import annotations

import re
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_markdown_by_boundaries(content: str) -> list[dict]:
    """Split markdown content into chunks based on page, slide, sheet, or heading sentinels."""
    chunks = []
    current_page = None
    current_heading = None
    current_locator = None
    current_lines = []

    page_re = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
    slide_re = re.compile(r"<!--\s*slide:\s*(\d+)\s*-->")
    sheet_re = re.compile(r"<!--\s*sheet:\s*([^;]+?)(?:\s*;\s*row:\s*(\d+))?\s*-->")
    heading_re = re.compile(r"<!--\s*heading:\s*(\d+)\s*-->")

    lines = content.splitlines()
    for line in lines:
        page_match = page_re.search(line)
        slide_match = slide_re.search(line)
        sheet_match = sheet_re.search(line)
        heading_match = heading_re.search(line)

        if page_match or slide_match or sheet_match or heading_match:
            if current_lines:
                chunk_text = "\n".join(current_lines).strip()
                if chunk_text:
                    chunks.append({
                        "text": chunk_text,
                        "page": current_page,
                        "locator": current_locator,
                        "heading": current_heading
                    })
                current_lines = []

            if page_match:
                current_page = int(page_match.group(1))
                current_locator = f"Page {current_page}"
                current_heading = None
            elif slide_match:
                current_page = int(slide_match.group(1))
                current_locator = f"Slide {current_page}"
                current_heading = None
            elif sheet_match:
                sheet_name = sheet_match.group(1).strip()
                row = sheet_match.group(2)
                if row:
                    current_locator = f"Sheet: {sheet_name}, row {row}"
                else:
                    current_locator = f"Sheet: {sheet_name}"
                current_page = None
                current_heading = None
            elif heading_match:
                current_heading = f"Heading level {heading_match.group(1)}"

        current_lines.append(line)

    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if chunk_text:
            chunks.append({
                "text": chunk_text,
                "page": current_page,
                "locator": current_locator,
                "heading": current_heading
            })

    return chunks


def get_document_chunks(content: str) -> list[dict]:
    """Split markdown content structurally, then sub-split using text splitter if chunks exceed limits."""
    raw_chunks = chunk_markdown_by_boundaries(content)

    splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)
    final_chunks = []

    for chunk in raw_chunks:
        text = chunk["text"]
        if len(text) <= 2000:
            final_chunks.append(chunk)
        else:
            sub_texts = splitter.split_text(text)
            for sub_text in sub_texts:
                final_chunks.append({
                    "text": sub_text,
                    "page": chunk["page"],
                    "locator": chunk["locator"],
                    "heading": chunk["heading"]
                })

    return final_chunks


def build_index(raw_dir: Path, output_index_dir: Path, embedding_model) -> FAISS | None:
    """Build and save a local FAISS vector store index from raw documents."""
    if not raw_dir.exists():
        return None

    md_files = list(raw_dir.rglob("*.md"))
    if not md_files:
        return None

    documents = []
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        rel_path = md_file.name

        chunks = get_document_chunks(content)
        for chunk in chunks:
            raw_path = f"/raw/{rel_path}"

            metadata = {
                "source_path": raw_path,
                "page": chunk["page"],
                "locator": chunk["locator"],
                "heading": chunk["heading"]
            }
            # Clean None values
            metadata = {k: v for k, v in metadata.items() if v is not None}

            doc = Document(page_content=chunk["text"], metadata=metadata)
            documents.append(doc)

    if not documents:
        return None

    vectorstore = FAISS.from_documents(documents, embedding_model)
    output_index_dir.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(output_index_dir))
    return vectorstore


def load_or_build_index(raw_dir: Path, output_index_dir: Path, embedding_model) -> FAISS | None:
    """Load an existing local FAISS vector store or build a new one if it does not exist."""
    index_file = output_index_dir / "index.faiss"
    if index_file.exists():
        try:
            return FAISS.load_local(str(output_index_dir), embedding_model, allow_dangerous_deserialization=True)
        except Exception:
            pass

    return build_index(raw_dir, output_index_dir, embedding_model)
