import pytest

from packages.queue import API_WORKER_QUEUE, PLAN_ENGINE_WORKER_QUEUE
from packages.queue.worker import _worker_queue


async def _noop(_payload):
    return None


def test_api_handlers_resolve_to_the_api_queue():
    handlers = {"import.parse": _noop, "export.push": _noop}
    assert _worker_queue(handlers) == API_WORKER_QUEUE


def test_engine_handlers_resolve_to_the_engine_queue():
    handlers = {"plan.generate": _noop, "plan.continue": _noop, "plan.revise": _noop}
    assert _worker_queue(handlers) == PLAN_ENGINE_WORKER_QUEUE


def test_mixing_deployables_in_one_worker_is_rejected():
    """Serving both sets from one process would silently re-create the stolen-job bug."""
    with pytest.raises(ValueError, match="more than one worker queue"):
        _worker_queue({"import.parse": _noop, "plan.generate": _noop})
