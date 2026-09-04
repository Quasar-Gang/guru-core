"""匯入 package：統一的 Document 型別、來源／解析器 port 與 parser registry。"""

from packages.importers.document import DocEvent, Document, TextChunk
from packages.importers.parsers import (
    CsvParser,
    DocxParser,
    HtmlParser,
    IcsParser,
    MarkdownParser,
    PdfParser,
    XlsxParser,
)
from packages.importers.ports import ParserPort, RawBlob, SourcePort, UnsupportedFormat
from packages.importers.registry import ParserRegistry, default_registry, detect_format
from packages.importers.sources.memory import InMemorySource

__all__ = [
    "CsvParser",
    "DocEvent",
    "Document",
    "DocxParser",
    "HtmlParser",
    "IcsParser",
    "InMemorySource",
    "MarkdownParser",
    "ParserPort",
    "ParserRegistry",
    "PdfParser",
    "RawBlob",
    "SourcePort",
    "TextChunk",
    "UnsupportedFormat",
    "XlsxParser",
    "default_registry",
    "detect_format",
]
