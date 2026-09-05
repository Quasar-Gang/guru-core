"""Keep docs/api/README.md honest against the OpenAPI document.

An API guide that names an endpoint the service does not serve is worse than no
guide: the reader trusts it and loses an afternoon. These checks are cheap and
catch the two ways it goes wrong — a route added without documenting it, and a
documented route that was renamed or removed.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "api" / "README.md"
SPEC = ROOT / "docs" / "api" / "openapi.json"

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: path segments that are enum-valued parameters rather than ids
_ENUMS = r"/(google|google_calendar|q1|q2|q3|latest)(?=/|$)"
#: job ids are opaque strings, not uuids
_JOB_ID = r"(?<=/v1/jobs/)[\w\-]+"
#: shell variables stand in for ids in the runnable examples
_SHELL_VAR = r"\$[A-Z_]+"


def _normalise(path: str) -> str:
    """Collapse a concrete example path onto its template form."""
    path = path.rstrip("/")
    path = re.sub(r"\{[^}]+\}", "{}", path)
    path = re.sub(_UUID, "{}", path)
    path = re.sub(_ENUMS, "/{}", path)
    path = re.sub(_JOB_ID, "{}", path)
    path = re.sub(_SHELL_VAR, "{}", path)
    return path.split("?", 1)[0]


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _mentioned(guide: str) -> set[str]:
    found = re.findall(r"(/(?:v1/[\w{}$\-./?=:]*|health))", guide)
    return {m for m in found if not m.endswith(".md")}


def test_every_endpoint_appears_in_the_guide(guide: str, spec: dict) -> None:
    mentioned = {_normalise(m) for m in _mentioned(guide)}
    missing = sorted(p for p in spec["paths"] if _normalise(p) not in mentioned)
    assert not missing, f"endpoints the guide never mentions: {missing}"


def test_the_guide_names_no_endpoint_that_does_not_exist(guide: str, spec: dict) -> None:
    real = {_normalise(p) for p in spec["paths"]}
    # /v1/files/* paths appear as presigned URLs with a storage key, not as routes
    unknown = sorted(
        m for m in _mentioned(guide) if _normalise(m) not in real and "/v1/files/" not in m
    )
    assert not unknown, f"guide names endpoints that are not served: {unknown}"


def test_examples_are_copy_pasteable(guide: str) -> None:
    """An id abbreviated with an ellipsis makes the surrounding curl useless."""
    truncated = re.findall(r"[0-9a-f]{6,}-\.\.\.", guide)
    assert not truncated, f"truncated ids in examples: {sorted(set(truncated))}"


def test_error_codes_are_ones_the_app_emits(guide: str) -> None:
    from services.api.adapters.http.app import STATUS_BY_ERROR, error_code
    from services.api.domain.errors import DomainError

    # error_code takes an instance, not a class, so instantiate each one — that is also
    # the path a real response goes through. DomainError itself is only the 500 fallback
    # and never reaches a client as a code.
    classes = set(STATUS_BY_ERROR) - {DomainError}
    emitted = {error_code(klass("x")) for klass in classes} | {"rate_limited"}
    table = guide.split("| code | HTTP |", 1)
    assert len(table) == 2, "the error-code table moved or was renamed"
    body = table[1].split("\n\n", 1)[0]
    claimed = set(re.findall(r"^\| `(\w+)` \|", body, re.MULTILINE))
    assert claimed, "no error codes parsed out of the table"

    unknown = sorted(claimed - emitted)
    assert not unknown, f"guide documents error codes the app never returns: {unknown}"

    missing = sorted(emitted - claimed)
    assert not missing, f"error codes the app returns but the guide never explains: {missing}"


def test_spec_export_is_current(spec: dict) -> None:
    """The checked-in export must match what the app would produce right now."""
    from services.api.adapters.http.app import create_app
    from services.api.container import build_test_container

    live = create_app(build_test_container()).openapi()
    assert set(live["paths"]) == set(spec["paths"]), (
        "docs/api/openapi.json is stale — run: uv run python scripts/export_openapi.py"
    )


async def test_declared_422_matches_the_body_actually_returned() -> None:
    """FastAPI advertises its own validation shape; our handler returns a different one.

    A generated client trusts the spec, so a mismatch here costs someone an
    afternoon unpacking a `detail` array that never arrives.
    """
    import httpx

    from services.api.adapters.http.app import create_app
    from services.api.container import build_test_container

    app = create_app(build_test_container())
    spec = app.openapi()

    declared = spec["paths"]["/v1/auth/google"]["post"]["responses"]["422"]
    ref = declared["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorResponse"), f"422 still declares {ref}"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # missing required body fields -> RequestValidationError -> our handler
        response = await client.post("/v1/auth/google", json={})

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}, f"actual body does not match ErrorResponse: {body}"
    assert set(body["error"]) >= {"code", "message"}
    assert body["error"]["code"] == "invalid_input"
