import pytest

from packages.importers import (
    Document,
    InMemorySource,
    ParserRegistry,
    RawBlob,
    TextChunk,
    UnsupportedFormat,
    default_registry,
    detect_format,
)


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("a.csv", "text/csv", "csv"),
        ("a.CSV", "application/octet-stream", "csv"),
        (
            "a.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        ),
        ("a.md", "text/markdown", "md"),
        ("a.markdown", "application/octet-stream", "md"),
        ("a.html", "text/html", "html"),
        ("a.HTM", "application/octet-stream", "html"),
        ("a.pdf", "application/pdf", "pdf"),
        (
            "a.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
        ("a.ics", "text/calendar", "ics"),
    ],
)
def test_detect_format_by_extension(filename, content_type, expected):
    assert detect_format(filename, content_type) == expected


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/csv", "csv"),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        ("text/markdown", "md"),
        ("text/html", "html"),
        ("application/pdf", "pdf"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
        ("text/calendar", "ics"),
    ],
)
def test_detect_format_falls_back_to_content_type(content_type, expected):
    assert detect_format("upload", content_type) == expected


def test_detect_format_content_type_is_case_insensitive_and_ignores_params():
    assert detect_format("upload", "TEXT/CSV; charset=utf-8") == "csv"


def test_detect_format_prefers_extension_over_content_type():
    assert detect_format("a.csv", "application/pdf") == "csv"


def test_detect_format_unknown_raises():
    with pytest.raises(UnsupportedFormat):
        detect_format("a.exe", "application/x-msdownload")


def test_unsupported_format_is_value_error():
    assert issubclass(UnsupportedFormat, ValueError)


class _StubParser:
    def __init__(self, fmt: str, text: str) -> None:
        self._fmt = fmt
        self._text = text

    def supports(self, fmt: str) -> bool:
        return fmt == self._fmt

    def parse(self, blob: RawBlob) -> Document:
        return Document(text_chunks=[TextChunk(text=self._text)])


def _blob(filename: str, content_type: str) -> RawBlob:
    return RawBlob(data=b"x", content_type=content_type, filename=filename)


def test_registry_picks_matching_parser():
    registry = ParserRegistry([_StubParser("csv", "from-csv"), _StubParser("md", "from-md")])
    doc = registry.parse(_blob("a.md", "text/markdown"))
    assert doc.text_chunks[0].text == "from-md"


def test_registry_without_matching_parser_raises():
    registry = ParserRegistry([_StubParser("csv", "from-csv")])
    with pytest.raises(UnsupportedFormat):
        registry.parse(_blob("a.md", "text/markdown"))


def test_registry_propagates_unknown_format():
    registry = ParserRegistry([_StubParser("csv", "from-csv")])
    with pytest.raises(UnsupportedFormat):
        registry.parse(_blob("a.exe", "application/x-msdownload"))


def test_default_registry_is_a_registry():
    assert isinstance(default_registry(), ParserRegistry)


async def test_in_memory_source_returns_blob():
    blob = _blob("a.csv", "text/csv")
    assert await InMemorySource(blob).fetch() is blob
