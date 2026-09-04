from datetime import UTC, datetime

from packages.importers import DocEvent, Document, TextChunk


def _doc_a() -> Document:
    return Document(
        events=[
            DocEvent(
                title="Gym",
                start_at=datetime(2026, 9, 8, 19, tzinfo=UTC),
                end_at=datetime(2026, 9, 8, 20, tzinfo=UTC),
            )
        ],
        text_chunks=[TextChunk(text="first", order=0), TextChunk(text="second", order=1)],
    )


def _doc_b() -> Document:
    return Document(
        events=[
            DocEvent(
                title="Run",
                start_at=datetime(2026, 9, 9, 7, tzinfo=UTC),
                end_at=datetime(2026, 9, 9, 8, tzinfo=UTC),
            )
        ],
        text_chunks=[TextChunk(text="third", order=0)],
    )


def test_merge_combines_events_and_chunks():
    merged = _doc_a().merge(_doc_b())
    assert [e.title for e in merged.events] == ["Gym", "Run"]
    assert [c.text for c in merged.text_chunks] == ["first", "second", "third"]


def test_merge_reorders_second_documents_chunks():
    merged = _doc_a().merge(_doc_b())
    assert [c.order for c in merged.text_chunks] == [0, 1, 2]


def test_merge_does_not_mutate_either_side():
    a, b = _doc_a(), _doc_b()
    merged = a.merge(b)
    assert merged is not a and merged is not b
    assert len(a.events) == 1
    assert [c.order for c in a.text_chunks] == [0, 1]
    assert len(b.events) == 1
    assert [c.order for c in b.text_chunks] == [0]


def test_merge_with_empty_document_keeps_orders():
    a = _doc_a()
    merged = a.merge(Document())
    assert [c.order for c in merged.text_chunks] == [0, 1]
    assert len(merged.events) == 1


def test_empty_document_defaults_are_independent():
    d1, d2 = Document(), Document()
    d1.text_chunks.append(TextChunk(text="x"))
    assert d2.text_chunks == []
