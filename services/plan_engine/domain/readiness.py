"""Readiness metric config (PRD 13.1-13.3), the evaluate_readiness schema and its rules."""

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
    """One readiness metric (a required or helpful entry of PRD 13.2)."""

    id: str
    name: str
    fills: str | None = None
    check: str
    bad_example: str | None = None
    good_example: str | None = None
    default: str | None = None
    note: str | None = None


class DomainProbeSpec(BaseModel):
    """Domain-critical prerequisites; the LLM infers the domain from the goal."""

    id: str
    name: str
    max_items: int
    instruction: str
    examples_for_llm: list[str]
    note: str


class ReadinessConfig(BaseModel):
    """Typed view of `config/readiness_metrics.yaml`."""

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
        """Every known metric id: required + domain_probe + helpful."""
        return {
            *(metric.id for metric in self.required),
            self.domain_probe.id,
            *(metric.id for metric in self.helpful),
        }


def load_readiness_config(path: Path | None = None) -> ReadinessConfig:
    return load_yaml_config(path or CONFIG_DIR / READINESS_CONFIG_FILENAME, ReadinessConfig)


class FollowupOption(BaseModel):
    """A single option. The LLM returns only text today; the type is kept for the UI."""

    text: str


class FollowupQuestion(BaseModel):
    """One follow-up question: one metric, exactly three context-specific options."""

    id: str
    metric_id: str
    text: str
    options: list[str] = Field(min_length=3, max_length=3)
    allow_custom: bool = True
    allow_skip: bool = True


class ReadinessOutput(BaseModel):
    """LLM ``output_schema`` for `evaluate_readiness`."""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    missing: list[str] = []
    questions: list[FollowupQuestion] = Field(default=[], max_length=5)


def readiness_rules(
    cfg: ReadinessConfig,
    asked_metric_ids: Set[str],
) -> list[Callable[[BaseModel], list[str]]]:
    """Business rules for `complete_validated`: a well-formed output can still be wrong."""
    known = cfg.known_metric_ids()
    asked = set(asked_metric_ids)

    def check_questions_present(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        if not output.ready and not output.questions:
            return ["questions must not be empty when ready=false"]
        return []

    def check_missing_empty_when_ready(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        if output.ready and output.missing:
            return [f"missing must be empty when ready=true, got {output.missing}"]
        return []

    def check_metric_ids(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        return [
            f"question {q.id} has metric_id {q.metric_id!r}, which is not a known metric"
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
                violations.append(
                    f"metric_id {question.metric_id!r} must not be asked twice in one round"
                )
            seen.add(question.metric_id)
        return violations

    def check_not_asked_before(output: BaseModel) -> list[str]:
        if not isinstance(output, ReadinessOutput):
            return []
        return [
            f"metric_id {q.metric_id!r} was already asked in an earlier round"
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
                    f"question {question.id} must have exactly "
                    f"{cfg.options_per_question} options, got {len(options)}"
                )
            if any(not option.strip() for option in options):
                violations.append(f"question {question.id} must not have blank options")
            if len({option.strip() for option in options}) != len(options):
                violations.append(f"question {question.id} must have distinct options")
        return violations

    return [
        check_questions_present,
        check_missing_empty_when_ready,
        check_metric_ids,
        check_no_duplicate_metric,
        check_not_asked_before,
        check_options,
    ]
