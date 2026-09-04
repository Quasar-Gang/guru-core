"""Markdown parser: split on headings, one TextChunk per section."""

from __future__ import annotations

from markdown_it import MarkdownIt

from packages.importers.document import Document, TextChunk
from packages.importers.ports import RawBlob


class MarkdownParser:
    """Parse Markdown text; the heading text becomes the chunk's section."""

    def supports(self, fmt: str) -> bool:
        return fmt == "md"

    def parse(self, blob: RawBlob) -> Document:
        text = blob.data.decode("utf-8-sig", errors="replace")
        if not text.strip():
            return Document()

        tokens = MarkdownIt().parse(text)
        chunks: list[TextChunk] = []
        section: str | None = None
        body: list[str] = []

        def flush() -> None:
            joined = "\n\n".join(part for part in body if part)
            if section is not None or joined:
                chunks.append(TextChunk(text=joined, section=section, order=len(chunks)))
            body.clear()

        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == "heading_open":
                flush()
                inline = tokens[index + 1]
                section = inline.content.strip()
                index += 3
                continue
            if token.type == "inline":
                content = token.content.strip()
                if content:
                    body.append(content)
            index += 1
        flush()
        return Document(text_chunks=chunks)
