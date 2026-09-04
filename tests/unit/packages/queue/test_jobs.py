from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.queue import (
    API_WORKER_QUEUE,
    JOB_REGISTRY,
    PLAN_ENGINE_WORKER_QUEUE,
    WORKER_QUEUE_BY_JOB,
    ExportJobV1,
    ImportParseJobV1,
    PlanContinueJobV1,
    PlanGenerateJobV1,
    PlanReviseJobV1,
)


def test_queue_name_mapping():
    assert PlanGenerateJobV1.queue_name() == "plan.generate"
    assert JOB_REGISTRY["export.push"] is ExportJobV1


def test_registry_contains_every_queue_name():
    expected = {
        "import.parse": ImportParseJobV1,
        "plan.generate": PlanGenerateJobV1,
        "plan.continue": PlanContinueJobV1,
        "plan.revise": PlanReviseJobV1,
        "export.push": ExportJobV1,
    }
    assert expected == JOB_REGISTRY


def test_payload_is_frozen_and_strict():
    p = PlanGenerateJobV1(session_id=uuid4())
    with pytest.raises(ValidationError):
        PlanGenerateJobV1(session_id=uuid4(), extra_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        p.session_id = uuid4()  # type: ignore[misc]


def test_base_payload_has_no_queue_name():
    from packages.queue.jobs import JobPayload

    with pytest.raises(NotImplementedError):
        JobPayload.queue_name()


def test_literal_fields_are_validated():
    with pytest.raises(ValidationError):
        PlanReviseJobV1(plan_id=uuid4(), revision_id=uuid4(), strategy="nope")
    with pytest.raises(ValidationError):
        ExportJobV1(plan_id=uuid4(), target="dropbox", mode="full")


def test_every_job_declares_a_worker_queue():
    assert set(WORKER_QUEUE_BY_JOB) == set(JOB_REGISTRY)


def test_the_two_deployables_use_different_queues():
    """A shared list lets one worker pop a job it has no handler for and discard it."""
    assert API_WORKER_QUEUE != PLAN_ENGINE_WORKER_QUEUE


def test_api_jobs_and_engine_jobs_are_separated():
    assert WORKER_QUEUE_BY_JOB["import.parse"] == API_WORKER_QUEUE
    assert WORKER_QUEUE_BY_JOB["export.push"] == API_WORKER_QUEUE
    assert WORKER_QUEUE_BY_JOB["plan.generate"] == PLAN_ENGINE_WORKER_QUEUE
    assert WORKER_QUEUE_BY_JOB["plan.continue"] == PLAN_ENGINE_WORKER_QUEUE
    assert WORKER_QUEUE_BY_JOB["plan.revise"] == PLAN_ENGINE_WORKER_QUEUE
