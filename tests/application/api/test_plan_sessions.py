"""Plan session HTTP endpoints (plan Task 24, PRD 3.2 / 3.3 / 5)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from packages.queue import InMemoryQueue, JobPayload
from services.api.container import ApiContainer


def _enqueued(container: ApiContainer) -> list[JobPayload]:
    """The fake queue's log; the test container always wires an `InMemoryQueue`."""
    queue = container.queue
    assert isinstance(queue, InMemoryQueue)
    return queue.enqueued


def _question(question_id: str = "q1") -> dict[str, Any]:
    return {
        "id": question_id,
        "metric_id": "capacity",
        "text": "how many sessions a week can you commit to?",
        "options": ["two evenings", "three evenings", "weekends only"],
        "allow_custom": True,
        "allow_skip": True,
    }


async def _questioning_session(container: ApiContainer, user_id: UUID) -> UUID:
    session = await container.plan_sessions.create(
        user_id=user_id,
        goal="run 5k under 30 minutes",
        intake={},
        import_ids=[],
        use_calendar=False,
        trait_role_model_id=None,
        persona_role_model_id=None,
    )
    await container.followup_rounds.create(session.id, 0, [_question()])
    await container.plan_sessions.bump_round(session.id)
    await container.plan_sessions.set_status(session.id, "questioning")
    return session.id


async def test_create_session_requires_goal(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post("/v1/plan-sessions", json={"goal": "   "}, headers=auth_headers)
    assert r.status_code == 422


async def test_create_session_returns_202_and_enqueues(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    r = await client.post("/v1/plan-sessions", json={"goal": "跑進 30 分"}, headers=auth_headers)

    assert r.status_code == 202
    assert r.json()["job_id"]
    assert _enqueued(container)[0].queue_name() == "plan.generate"


async def test_create_session_requires_authentication(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/plan-sessions", json={"goal": "anything"})
    assert r.status_code == 401


async def test_create_session_rejects_other_users_import(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    record = await container.imports.create(other.id, "upload", "csv", "key", "f.csv")
    await container.imports.set_status(record.id, "parsed")

    r = await client.post(
        "/v1/plan-sessions",
        json={"goal": "g", "import_ids": [str(record.id)]},
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_create_session_rejects_unparsed_import(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    record = await container.imports.create(auth_user_id, "upload", "csv", "key", "f.csv")

    r = await client.post(
        "/v1/plan-sessions",
        json={"goal": "g", "import_ids": [str(record.id)]},
        headers=auth_headers,
    )

    assert r.status_code == 422


async def test_create_session_marks_calendar_use_when_google_is_connected(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    await container.oauth_connections.upsert(auth_user_id, "google", b"token", "scope", None)

    r = await client.post("/v1/plan-sessions", json={"goal": "g"}, headers=auth_headers)

    session = await container.plan_sessions.get(auth_user_id, UUID(r.json()["session_id"]))
    assert session is not None
    assert session.use_calendar is True


async def test_revoked_google_connection_does_not_enable_calendar(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    await container.oauth_connections.upsert(auth_user_id, "google", b"token", "scope", None)
    await container.oauth_connections.mark_revoked(auth_user_id, "google", datetime.now(UTC))

    r = await client.post("/v1/plan-sessions", json={"goal": "g"}, headers=auth_headers)

    session = await container.plan_sessions.get(auth_user_id, UUID(r.json()["session_id"]))
    assert session is not None
    assert session.use_calendar is False


async def test_get_session_returns_questions_while_questioning(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    session_id = await _questioning_session(container, auth_user_id)

    body = (await client.get(f"/v1/plan-sessions/{session_id}", headers=auth_headers)).json()

    assert body["status"] == "questioning"
    assert body["round"] == 1
    assert [q["id"] for q in body["questions"]] == ["q1"]
    assert body["plans"] == []


async def test_get_session_of_other_user_is_404(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    other = await container.users.create("other@example.com", "other-sub")
    session_id = await _questioning_session(container, other.id)

    r = await client.get(f"/v1/plan-sessions/{session_id}", headers=auth_headers)

    assert r.status_code == 404


async def test_answers_accepted_and_enqueue_continue(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    session_id = await _questioning_session(container, auth_user_id)

    r = await client.post(
        f"/v1/plan-sessions/{session_id}/answers",
        json={"answers": [{"question_id": "q1", "choice": "two evenings"}]},
        headers=auth_headers,
    )

    assert r.status_code == 202
    assert _enqueued(container)[-1].queue_name() == "plan.continue"
    round_ = await container.followup_rounds.latest(session_id)
    assert round_ is not None
    assert round_.answers == [
        {"question_id": "q1", "choice": "two evenings", "custom": None, "skipped": False}
    ]
    assert round_.answered_at is not None


async def test_answers_on_non_questioning_session_conflicts(
    client: httpx.AsyncClient,
    container: ApiContainer,
    auth_headers: dict[str, str],
    auth_user_id: UUID,
) -> None:
    session_id = await _questioning_session(container, auth_user_id)
    await container.plan_sessions.set_status(session_id, "generating")

    r = await client.post(
        f"/v1/plan-sessions/{session_id}/answers",
        json={"answers": [{"question_id": "q1", "skipped": True}]},
        headers=auth_headers,
    )

    assert r.status_code == 409


async def test_answers_on_unknown_session_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    r = await client.post(
        f"/v1/plan-sessions/{uuid4()}/answers",
        json={"answers": []},
        headers=auth_headers,
    )
    assert r.status_code == 404


async def test_job_status_is_reported(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post("/v1/plan-sessions", json={"goal": "g"}, headers=auth_headers)
    job_id = created.json()["job_id"]

    body = (await client.get(f"/v1/jobs/{job_id}", headers=auth_headers)).json()

    assert body == {"job_id": job_id, "status": "queued"}


async def test_unknown_job_reports_unknown(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = (await client.get("/v1/jobs/does-not-exist", headers=auth_headers)).json()
    assert body["status"] == "unknown"
