"""Parser 測試共用的 fixture 載入器。"""

from pathlib import Path

from packages.importers import RawBlob

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "importers"

CONTENT_TYPES = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".md": "text/markdown",
    ".html": "text/html",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ics": "text/calendar",
}


def load_blob(name: str) -> RawBlob:
    """從 tests/fixtures/importers/ 讀一個 fixture 成 RawBlob。"""
    path = FIXTURES / name
    return RawBlob(
        data=path.read_bytes(),
        content_type=CONTENT_TYPES[path.suffix.lower()],
        filename=name,
    )
