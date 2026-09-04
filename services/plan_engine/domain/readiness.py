"""Readiness 指標設定（PRD 13.1–13.3）、evaluate_readiness 輸出 schema 與業務規則。"""

from collections.abc import Callable, Set
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config

__all__ = [
    "DomainProbeSpec",
    "FollowupOption",
    "FollowupQuestion",
    "MetricSpec",
    "ReadinessConfig",
    "ReadinessOutput",
    "load_readiness_config",
    "readiness_rules",
]

READINESS_CONFIG_FILENAME = "readiness_metrics.yaml"


class MetricSpec(BaseModel):
    """一項 readiness 指標（PRD 13.2 的 required / helpful 項目）。"""

    id: str
    name: str
    fills: str | None = None
    check: str
    bad_example: str | None = None
    good_example: str | None = None
    default: str | None = None
    note: str | None = None


class DomainProbeSpec(BaseModel):
    """領域關鍵前提：不預先列舉領域，由 LLM 依目標自行判斷。"""

    id: str
    name: str
    max_items: int
    instruction: str
    examples_for_llm: list[str]
    note: str


class ReadinessConfig(BaseModel):
    """`config/readiness_metrics.yaml` 的型別化檢視。"""

    version: int
    max_followup_rounds: int
    max_questions_per_round: int
    options_per_question: int
    ask_order: list[str]
    required: list[MetricSpec]
    domain_probe: DomainProbeSpec
    helpful: list[MetricSpec]
    ready_rule: str
    force_generate_rule: str

    def required_ids(self) -> list[str]:
        return [metric.id for metric in self.required]

    def known_metric_ids(self) -> set[str]:
        """required + domain_probe + helpful 的完整 id 集合。"""
        return {
            *(metric.id for metric in self.required),
            self.domain_probe.id,
            *(metric.id for metric in self.helpful),
        }


def load_readiness_config(path: Path | None = None) -> ReadinessConfig:
    return load_yaml_config(path or CONFIG_DIR / READINESS_CONFIG_FILENAME, ReadinessConfig)


class FollowupOption(BaseModel):
    """單一選項；LLM 目前只回文字，保留型別供前端擴充。"""

    text: str


class FollowupQuestion(BaseModel):
    """一題追問：一題只補一個指標，恰好三個依 context 客製的選項。"""

    id: str
    metric_id: str
    text: str
    options: list[str] = Field(min_length=3, max_length=3)
    allow_custom: bool = True
    allow_skip: bool = True


class ReadinessOutput(BaseModel):
    """`evaluate_readiness` 的 LLM output_schema。"""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    missing: list[str] = []
    questions: list[FollowupQuestion] = Field(default=[], max_length=5)


def readiness_rules(
    cfg: ReadinessConfig,
    asked_metric_ids: Set[str],
) -> list[Callable[[BaseModel], list[str]]]:
    """回傳 `complete_validated` 用的業務規則：格式對不代表內容合理。"""
    known = cfg.known_metric_ids()
    asked = set(asked_metric_ids)

    def check_questions_present(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        if not output.ready and not output.questions:
            return ["ready=false 時 questions 不得為空"]
        return []

    def check_missing_empty_when_ready(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        if output.ready and output.missing:
            return [f"ready=true 時 missing 必須為空，收到 {output.missing}"]
        return []

    def check_metric_ids(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        return [
            f"question {q.id} 的 metric_id {q.metric_id!r} 不在指標清單中"
            for q in output.questions
            if q.metric_id not in known
        ]

    def check_no_duplicate_metric(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        violations: list[str] = []
        seen: set[str] = set()
        for question in output.questions:
            if question.metric_id in seen:
                violations.append(f"同一輪不得對 metric_id {question.metric_id!r} 出兩題")
            seen.add(question.metric_id)
        return violations

    def check_not_asked_before(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        return [
            f"metric_id {q.metric_id!r} 上一輪已問過，不得重問"
            for q in output.questions
            if q.metric_id in asked
        ]

    def check_options(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        violations: list[str] = []
        for question in output.questions:
            options = question.options
            if len(options) != cfg.options_per_question:
                violations.append(
                    f"question {question.id} 的 options 必須恰好 "
                    f"{cfg.options_per_question} 個，收到 {len(options)} 個"
                )
            if any(not option.strip() for option in options):
                violations.append(f"question {question.id} 的 options 不得有空字串")
            if len({option.strip() for option in options}) != len(options):
                violations.append(f"question {question.id} 的 options 必須互不相同")
        return violations

    return [
        check_questions_present,
        check_missing_empty_when_ready,
        check_metric_ids,
        check_no_duplicate_metric,
        check_not_asked_before,
        check_options,
    ]
