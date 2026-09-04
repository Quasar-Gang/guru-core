import json
import logging

from packages.logging import bind_job_id, configure_logging, current_job_id, get_logger


def _emit(capsys, fn) -> dict:
    configure_logging("test-service")
    fn(get_logger("guru.test"))
    line = capsys.readouterr().out.strip().splitlines()[-1]
    return json.loads(line)


def test_record_is_one_json_line_with_service(capsys):
    payload = _emit(capsys, lambda log: log.info("something_happened"))
    assert payload["event"] == "something_happened"
    assert payload["service"] == "test-service"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "guru.test"


def test_extra_fields_are_merged_into_the_payload(capsys):
    payload = _emit(capsys, lambda log: log.info("plan_generated", extra={"plan_count": 3}))
    assert payload["plan_count"] == 3


def test_job_id_absent_outside_a_bound_block(capsys):
    payload = _emit(capsys, lambda log: log.info("no_job"))
    assert "job_id" not in payload


def test_job_id_is_attached_inside_the_block(capsys):
    def emit(log):
        with bind_job_id("job-42"):
            log.info("in_job")

    assert _emit(capsys, emit)["job_id"] == "job-42"


def test_job_id_is_restored_after_the_block():
    assert current_job_id() is None
    with bind_job_id("outer"):
        assert current_job_id() == "outer"
        with bind_job_id("inner"):
            assert current_job_id() == "inner"
        assert current_job_id() == "outer"
    assert current_job_id() is None


def test_exception_is_rendered(capsys):
    def emit(log):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("call_failed")

    payload = _emit(capsys, emit)
    assert "ValueError: boom" in payload["exception"]


def test_configure_logging_is_idempotent(capsys):
    configure_logging("svc")
    configure_logging("svc")
    get_logger("guru.test").info("once")
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_level_is_respected(capsys):
    configure_logging("svc", level=logging.WARNING)
    log = get_logger("guru.test")
    log.info("dropped")
    log.warning("kept")
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "kept"
