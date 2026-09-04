# Role Model Service

## What it owns

The source of truth for role cards and trait cards (`role_models`). It exposes the
`/role-models*` HTTP API (port 8001): listing and tag lookup, single-record detail, team
writes (`POST` / `PUT`), and deactivation (`DELETE`, a soft delete). Writes are validated
against the tag namespace rules (PRD 12.3) and the `content` schema (PRD 12.4), and any tag
value seen for the first time is learned back into `config/tag_vocab.yaml`.

## Ports it exposes

- HTTP (driving): `GET /role-models`, `GET /role-models/tags`, `GET /role-models/{id}` are
  unauthenticated; `POST /role-models`, `PUT /role-models/{id}` and `DELETE /role-models/{id}`
  require `X-API-Key`.
- `packages.repo.RoleModelRepo` (driven): `PgRoleModelRepo` in production,
  `InMemoryRoleModelRepo` in tests.
- `config/tag_vocab.yaml` (driven): reads and writes of the tag vocabulary, at the path given
  by `RoleModelSettings.tag_vocab_path`.

## What it does not do

No user authentication (JWTs are the API Service's job; this service only checks an API key),
no access to user data, no calls to other services, no scheduling and no plan generation.
Choosing a role model and rendering it into a prompt belongs to the Plan Engine.
