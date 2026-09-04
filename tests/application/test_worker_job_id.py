"""Worker handlers bind the job id, so every log line emitted inside a job carries it."""

import io
import json
import logging
from typing import Any, cast
from uuid import uuid4

import pytest

from packages.logging import JsonFormatter
from packages.queue import ExportJobV1, ImportParseJobV1, PlanGenerateJobV1, PlanReviseJobV1
from services.api.adapters.queue.export_consumer import ExportPushConsumer
from services.api.adapters.queue.import_consumer import ImportParseConsumer
from services.plan_engine.adapters.queue.consumers import (
    EvaluateSessionConsumer,
    PlanReviseConsumer,
)


@pytest.fixture
def captured_logs() -> Any:
    """Attach a JSON handler to the root logger and hand back its buffer."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    previous, previous_level = root.handlers[:], root.level
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    yield stream
    root.handlers, root.level = previous, previous_level


async def _log_something(payload: Any) -> None:
    logging.getLogger("test.worker").info("handling")


def _job_ids(stream: io.StringIO) -> list[str | None]:
    return [json.loads(line).get("job_id") for line in stream.getvalue().splitlines()]


async def test_import_parse_consumer_binds_the_import_id(captured_logs: io.StringIO) -> None:
    import_id = uuid4()
    consumer = ImportParseConsumer(cast(Any, _log_something))
    await consumer(ImportParseJobV1(import_id=import_id))
    assert _job_ids(captured_logs) == [str(import_id)]


async def test_export_push_consumer_binds_the_plan_id(captured_logs: io.StringIO) -> None:
    plan_id = uuid4()
    consumer = ExportPushConsumer(cast(Any, _log_something))
    await consumer(ExportJobV1(plan_id=plan_id, target="google_calendar", mode="full"))
    assert _job_ids(captured_logs) == [str(plan_id)]


async def test_evaluate_session_consumer_binds_the_session_id(captured_logs: io.StringIO) -> None:
    session_id = uuid4()
    consumer = EvaluateSessionConsumer(cast(Any, _log_something))
    await consumer(PlanGenerateJobV1(session_id=session_id))
    assert _job_ids(captured_logs) == [str(session_id)]


async def test_plan_revise_consumer_binds_the_plan_id(captured_logs: io.StringIO) -> None:
    plan_id = uuid4()
    consumer = PlanReviseConsumer(cast(Any, _log_something))
    await consumer(PlanReviseJobV1(plan_id=plan_id, revision_id=uuid4(), strategy="postpone"))
    assert _job_ids(captured_logs) == [str(plan_id)]


async def test_job_id_is_unbound_after_the_handler_returns(captured_logs: io.StringIO) -> None:
    consumer = ImportParseConsumer(cast(Any, _log_something))
    await consumer(ImportParseJobV1(import_id=uuid4()))
    logging.getLogger("test.worker").info("outside")
    assert _job_ids(captured_logs)[-1] is None
