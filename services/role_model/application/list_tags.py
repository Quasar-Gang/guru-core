"""List the tags in use, grouped by namespace, for the front-end filters."""

from packages.repo import RoleModelRepo
from services.role_model.domain import parse_tag


class ListTags:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for tag in await self._role_models.list_tags():
            namespace, value = parse_tag(tag)
            bucket = grouped.setdefault(namespace, [])
            if value not in bucket:
                bucket.append(value)
        return {namespace: sorted(values) for namespace, values in sorted(grouped.items())}
