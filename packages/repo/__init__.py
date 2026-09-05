"""Repo package: the ORM schema, the repo protocols and their two implementations.

ORM objects never leave `packages.repo`; everything crossing the boundary is a frozen
Pydantic model from `entities.py`. The implementations are grouped by bounded context —
identity, intake, direction, catalog, planning, reconciliation — so a context's tables are
read and written in one place rather than scattered across a file per table.
"""

from packages.repo.engine import build_engine, build_session_factory
from packages.repo.entities import (
    Checkin,
    DirectionHypothesis,
    DirectionRun,
    Document,
    FitVerdict,
    Import,
    LlmCallLog,
    Milestone,
    NewFitVerdict,
    NewMilestone,
    NewReport,
    NewRoleModel,
    NewTask,
    OAuthConnection,
    Plan,
    PlanExport,
    Profile,
    QuestionAnswer,
    Quota,
    Reconciliation,
    Report,
    RoleModel,
    ScheduledTaskRow,
    ScheduleSlot,
    Task,
    TaskStatusUpdate,
    User,
)
from packages.repo.memory.catalog import InMemoryRoleModelRepo
from packages.repo.memory.direction import (
    InMemoryDirectionHypothesisRepo,
    InMemoryDirectionRunRepo,
    InMemoryFitVerdictRepo,
    InMemoryQuestionAnswerRepo,
    InMemoryQuotaRepo,
    InMemoryReportRepo,
)
from packages.repo.memory.identity import InMemoryOAuthConnectionRepo, InMemoryUserRepo
from packages.repo.memory.intake import (
    InMemoryDocumentRepo,
    InMemoryImportRepo,
    InMemoryProfileRepo,
)
from packages.repo.memory.llm_call import InMemoryLlmCallRepo
from packages.repo.memory.planning import (
    InMemoryCheckinRepo,
    InMemoryPlanExportRepo,
    InMemoryPlanRepo,
    InMemoryPlanTreeRepo,
)
from packages.repo.memory.reconciliation import InMemoryReconciliationRepo
from packages.repo.models import Base
from packages.repo.pg.catalog import PgRoleModelRepo
from packages.repo.pg.direction import (
    PgDirectionHypothesisRepo,
    PgDirectionRunRepo,
    PgFitVerdictRepo,
    PgQuestionAnswerRepo,
    PgQuotaRepo,
    PgReportRepo,
)
from packages.repo.pg.identity import PgOAuthConnectionRepo, PgUserRepo
from packages.repo.pg.intake import PgDocumentRepo, PgImportRepo, PgProfileRepo
from packages.repo.pg.llm_call import PgLlmCallRepo
from packages.repo.pg.planning import (
    PgCheckinRepo,
    PgPlanExportRepo,
    PgPlanRepo,
    PgPlanTreeRepo,
)
from packages.repo.pg.reconciliation import PgReconciliationRepo
from packages.repo.ports import (
    CheckinRepo,
    DirectionHypothesisRepo,
    DirectionRunRepo,
    DocumentRepo,
    FitVerdictRepo,
    ImportRepo,
    LlmCallRepo,
    OAuthConnectionRepo,
    PlanExportRepo,
    PlanRepo,
    PlanTreeRepo,
    ProfileRepo,
    QuestionAnswerRepo,
    QuotaRepo,
    ReconciliationRepo,
    ReportRepo,
    RoleModelRepo,
    UserRepo,
)

__all__ = [
    # entities
    "Base",
    "Checkin",
    "DirectionHypothesis",
    "DirectionRun",
    "Document",
    "FitVerdict",
    "Import",
    "LlmCallLog",
    "Milestone",
    "NewFitVerdict",
    "NewMilestone",
    "NewReport",
    "NewRoleModel",
    "NewTask",
    "OAuthConnection",
    "Plan",
    "PlanExport",
    "Profile",
    "QuestionAnswer",
    "Quota",
    "Reconciliation",
    "Report",
    "RoleModel",
    "ScheduleSlot",
    "ScheduledTaskRow",
    "Task",
    "TaskStatusUpdate",
    "User",
    # protocols
    "CheckinRepo",
    "DirectionHypothesisRepo",
    "DirectionRunRepo",
    "DocumentRepo",
    "FitVerdictRepo",
    "ImportRepo",
    "LlmCallRepo",
    "OAuthConnectionRepo",
    "PlanExportRepo",
    "PlanRepo",
    "PlanTreeRepo",
    "ProfileRepo",
    "QuestionAnswerRepo",
    "QuotaRepo",
    "ReconciliationRepo",
    "ReportRepo",
    "RoleModelRepo",
    "UserRepo",
    # postgres
    "PgCheckinRepo",
    "PgDirectionHypothesisRepo",
    "PgDirectionRunRepo",
    "PgDocumentRepo",
    "PgFitVerdictRepo",
    "PgImportRepo",
    "PgLlmCallRepo",
    "PgOAuthConnectionRepo",
    "PgPlanExportRepo",
    "PgPlanRepo",
    "PgPlanTreeRepo",
    "PgProfileRepo",
    "PgQuestionAnswerRepo",
    "PgQuotaRepo",
    "PgReconciliationRepo",
    "PgReportRepo",
    "PgRoleModelRepo",
    "PgUserRepo",
    # in-memory
    "InMemoryCheckinRepo",
    "InMemoryDirectionHypothesisRepo",
    "InMemoryDirectionRunRepo",
    "InMemoryDocumentRepo",
    "InMemoryFitVerdictRepo",
    "InMemoryImportRepo",
    "InMemoryLlmCallRepo",
    "InMemoryOAuthConnectionRepo",
    "InMemoryPlanExportRepo",
    "InMemoryPlanRepo",
    "InMemoryPlanTreeRepo",
    "InMemoryProfileRepo",
    "InMemoryQuestionAnswerRepo",
    "InMemoryQuotaRepo",
    "InMemoryReconciliationRepo",
    "InMemoryReportRepo",
    "InMemoryRoleModelRepo",
    "InMemoryUserRepo",
    # engine
    "build_engine",
    "build_session_factory",
]
