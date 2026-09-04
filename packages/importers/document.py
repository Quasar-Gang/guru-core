"""Document — Plan Engine 唯一認識的匯入格式。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DocEvent(BaseModel):
    """一筆有明確時間的事件。"""

    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    location: str | None = None
    source_ref: str | None = None


class TextChunk(BaseModel):
    """一段沒有時間資訊的文字。"""

    text: str
    section: str | None = None
    order: int = 0


class Document(BaseModel):
    """一份或多份匯入來源解析後的統一結果。"""

    events: list[DocEvent] = Field(default_factory=list)
    text_chunks: list[TextChunk] = Field(default_factory=list)

    def merge(self, other: Document) -> Document:
        """回傳合併後的新 Document，不修改 self 與 other。

        `other` 的 text_chunks 會重新編號，接續 self 的最大 order + 1。
        """
        offset = max((c.order for c in self.text_chunks), default=-1) + 1
        return Document(
            events=[*self.events, *other.events],
            text_chunks=[
                *self.text_chunks,
                *(c.model_copy(update={"order": c.order + offset}) for c in other.text_chunks),
            ],
        )
