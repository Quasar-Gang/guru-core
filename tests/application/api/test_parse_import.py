from uuid import UUID, uuid4

from packages.queue import ImportParseJobV1, InMemoryQueue
from services.api.adapters.queue.import_consumer import ImportParseConsumer
from services.api.container import ApiContainer

CSV_BODY = b"title,start\nMorning run,2026-01-05 07:00\n"


async def _drain(container: ApiContainer) -> None:
    assert isinstance(container.queue, InMemoryQueue)
    await container.queue.drain({"import.parse": ImportParseConsumer(container.parse_import)})


async def _upload(
    container: ApiContainer, user_id: UUID, filename: str, content_type: str, body: bytes
) -> UUID:
    result = await container.presign_import(user_id, filename, content_type, len(body))
    await container.storage.put(result.storage_key, body, content_type)
    await container.complete_import(user_id, result.import_id)
    return result.import_id


async def test_parse_import_writes_document(container: ApiContainer, auth_user_id: UUID) -> None:
    import_id = await _upload(container, auth_user_id, "a.csv", "text/csv", CSV_BODY)
    await _drain(container)

    document = await container.documents.get_by_import(import_id)
    assert document is not None
    assert len(document.events) == 1
    assert document.events[0]["title"] == "Morning run"

    record = await container.imports.get(auth_user_id, import_id)
    assert record is not None
    assert record.status == "parsed"
    assert record.error is None


async def test_parse_import_counts_show_up_in_list(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    await _upload(container, auth_user_id, "a.csv", "text/csv", CSV_BODY)
    await _drain(container)

    [view] = await container.list_imports(auth_user_id)
    assert view.status == "parsed"
    assert view.event_count == 1


async def test_parse_import_marks_failed_on_bad_content(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    import_id = await _upload(
        container,
        auth_user_id,
        "a.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        b"\x00 not really a spreadsheet",
    )
    await _drain(container)

    record = await container.imports.get(auth_user_id, import_id)
    assert record is not None
    assert record.status == "failed"
    assert record.error


async def test_parse_import_marks_failed_when_object_is_missing(
    container: ApiContainer, auth_user_id: UUID
) -> None:
    result = await container.presign_import(auth_user_id, "a.csv", "text/csv", 10)
    await container.parse_import(ImportParseJobV1(import_id=result.import_id))

    record = await container.imports.get(auth_user_id, result.import_id)
    assert record is not None
    assert record.status == "failed"
    assert record.error


async def test_parse_import_never_raises_on_unknown_import(container: ApiContainer) -> None:
    await container.parse_import(ImportParseJobV1(import_id=uuid4()))
