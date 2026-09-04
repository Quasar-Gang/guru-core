"""PDF parser：每頁一個 TextChunk。"""

from __future__ import annotations

import io

from pypdf import PdfReader

from packages.importers.document import Document, TextChunk
from packages.importers.ports import RawBlob


class PdfParser:
    """抽取每一頁的純文字，section 為 "page N"。"""

    def supports(self, fmt: str) -> bool:
        return fmt == "pdf"

    def parse(self, blob: RawBlob) -> Document:
        if not blob.data:
            return Document()
        reader = PdfReader(io.BytesIO(blob.data))
        chunks = [
            TextChunk(text=page.extract_text().strip(), section=f"page {number}", order=index)
            for index, (number, page) in enumerate(enumerate(reader.pages, start=1))
        ]
        return Document(text_chunks=chunks)
