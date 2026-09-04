"""建立或更新一筆 role model（團隊寫入端點，PRD 12.7）。

寫入前先驗證 tag 命名空間（12.3）與 content schema（12.4），任一失敗即拒絕；
成功後把新出現的 tag 值追加回 `config/tag_vocab.yaml`，供前端篩選與寫入提示。
"""

import fcntl
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml

from packages.config import CONFIG_DIR
from packages.repo import RoleModelRepo
from services.role_model.application.errors import InvalidInput
from services.role_model.application.get_role_model import RoleModelView
from services.role_model.domain import (
    InvalidContent,
    InvalidTag,
    TagVocab,
    learn_values,
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
        self._learn(tags, vocab)
        return RoleModelView.of(role_model)

    def _learn(self, tags: list[str], vocab: TagVocab) -> None:
        """把新值寫回 vocab 檔：flock 序列化 + 暫存檔 + os.replace 原子替換。"""
        if learn_values(tags, vocab).known_values == vocab.known_values:
            return
        path = self._tag_vocab_path
        lock_path = path.with_name(path.name + ".lock")
        with open(lock_path, "w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                # 取得鎖後重讀，避免覆蓋其他 process 在等待期間學到的值。
                fresh = learn_values(tags, load_tag_vocab(path))
                _atomic_write_yaml(path, fresh.model_dump(mode="json"))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            yaml.safe_dump(data, tmp, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
