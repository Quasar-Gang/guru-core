"""Create or update a role model (the team-facing write endpoint, PRD 12.7).

Tag namespaces (12.3) and the content schema (12.4) are validated before the write, and
any failure rejects it.

PRD 12.3 says newly seen tag values should be recorded "so they show up in front-end
filters and authoring hints". We satisfy that from the database rather than by rewriting
`config/tag_vocab.yaml`: `GET /role-models/tags` aggregates the live `role_models.tags`
column, which is always current, needs no lock, and cannot strip the config file's
comments. The file therefore stays hand-maintained and owns only the namespace
allow-list, the value rules, and the enum-only namespaces — the parts that gate writes.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from packages.config import CONFIG_DIR
from packages.repo import RoleModelRepo
from services.role_model.application.errors import InvalidInput
from services.role_model.application.get_role_model import RoleModelView
from services.role_model.domain import (
    InvalidContent,
    InvalidTag,
    load_tag_vocab,
    parse_content,
    validate_tags,
)


class UpsertRoleModel:
    def __init__(self, role_models: RoleModelRepo, tag_vocab_path: Path | None = None) -> None:
        self._role_models = role_models
        self._tag_vocab_path = tag_vocab_path or CONFIG_DIR / "tag_vocab.yaml"

    async def __call__(
        self,
        role_model_id: UUID | None,
        kind: str,
        name: str,
        tags: list[str],
        content: dict[str, Any],
    ) -> RoleModelView:
        vocab = load_tag_vocab(self._tag_vocab_path)
        try:
            validate_tags(tags, kind, vocab)
            parsed = parse_content(kind, content)
        except (InvalidTag, InvalidContent) as exc:
            raise InvalidInput(str(exc)) from exc

        role_model = await self._role_models.upsert(
            role_model_id=role_model_id,
            kind=kind,
            name=name,
            tags=list(tags),
            content=parsed.model_dump(mode="json"),
        )
        return RoleModelView.of(role_model)
