"""Format detection and parser selection."""

from collections.abc import Sequence

from packages.importers.document import Document
from packages.importers.parsers import (
    CsvParser,
    DocxParser,
    HtmlParser,
    IcsParser,
    MarkdownParser,
    PdfParser,
    XlsxParser,
)
from packages.importers.ports import ParserPort, RawBlob, UnsupportedFormat

_EXTENSIONS: dict[str, str] = {
    "csv": "csv",
    "xlsx": "xlsx",
    "md": "md",
    "markdown": "md",
    "html": "html",
    "htm": "html",
    "pdf": "pdf",
    "docx": "docx",
    "ics": "ics",
}

_CONTENT_TYPES: dict[str, str] = {
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/markdown": "md",
    "text/html": "html",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/calendar": "ics",
}


def detect_format(filename: str, content_type: str) -> str:
    """Return "csv" | "xlsx" | "md" | "html" | "pdf" | "docx" | "ics".

    The file extension wins (case-insensitively); the content type is only consulted when
    the extension is unknown. Raises UnsupportedFormat when neither identifies a format.
    """
    _, _, extension = filename.rpartition(".")
    fmt = _EXTENSIONS.get(extension.lower())
    if fmt is not None:
        return fmt

    media_type = content_type.split(";", 1)[0].strip().lower()
    fmt = _CONTENT_TYPES.get(media_type)
    if fmt is not None:
        return fmt

    raise UnsupportedFormat(
        f"unsupported format: filename={filename!r} content_type={content_type!r}"
    )


class ParserRegistry:
    """Pick a parser based on the result of detect_format."""

    def __init__(self, parsers: Sequence[ParserPort]) -> None:
        self._parsers = tuple(parsers)

    def parse(self, blob: RawBlob) -> Document:
        fmt = detect_format(blob.filename, blob.content_type)
        for parser in self._parsers:
            if parser.supports(fmt):
                return parser.parse(blob)
        raise UnsupportedFormat(f"no parser registered for format: {fmt}")


def default_registry() -> ParserRegistry:
    """Production registry with all seven parsers: csv, xlsx, md, html, pdf, docx, ics."""
    return ParserRegistry(
        (
            CsvParser(),
            XlsxParser(),
            MarkdownParser(),
            HtmlParser(),
            PdfParser(),
            DocxParser(),
            IcsParser(),
        )
    )
