"""HTML parser: split on headings and strip the markup, keeping only text."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from packages.importers.document import Document, TextChunk
from packages.importers.ports import RawBlob

_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


class HtmlParser:
    """Parse HTML; the text of an <h1>-<h6> element becomes the chunk's section."""

    def supports(self, fmt: str) -> bool:
        return fmt == "html"

    def parse(self, blob: RawBlob) -> Document:
        text = blob.data.decode("utf-8-sig", errors="replace")
        if not text.strip():
            return Document()

        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()

        chunks: list[TextChunk] = []
        section: str | None = None
        body: list[str] = []

        def flush() -> None:
            joined = "\n\n".join(part for part in body if part)
            if section is not None or joined:
                chunks.append(TextChunk(text=joined, section=section, order=len(chunks)))
            body.clear()

        root = soup.body or soup
        for element in root.find_all(True):
            if not isinstance(element, Tag):
                continue
            if element.name in _HEADINGS:
                flush()
                section = element.get_text(" ", strip=True)
                continue
            if element.find(True) is not None:
                continue
            content = element.get_text(" ", strip=True)
            if content:
                body.append(content)
        flush()
        return Document(text_chunks=chunks)
