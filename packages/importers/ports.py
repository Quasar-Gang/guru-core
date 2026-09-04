"""匯入相關的 port 介面與共用型別。"""

from typing import Protocol

from pydantic import BaseModel

from packages.importers.document import Document


class RawBlob(BaseModel):
    """尚未解析的原始位元組與其中繼資料。"""

    data: bytes
    content_type: str
    filename: str


class UnsupportedFormat(ValueError):
    """無法判斷格式，或沒有 parser 支援該格式時拋出。"""


class SourcePort(Protocol):
    """取得原始資料的來源 port。"""

    async def fetch(self) -> RawBlob: ...


class ParserPort(Protocol):
    """把 RawBlob 解析成 Document 的 parser port。"""

    def supports(self, fmt: str) -> bool: ...

    def parse(self, blob: RawBlob) -> Document: ...
