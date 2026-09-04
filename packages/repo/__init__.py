"""Repo package: the ORM schema, the repo protocols and their implementations.

ORM objects never leave `packages.repo`; everything crossing the boundary is a frozen
Pydantic model from `entities.py`.
"""

from packages.repo.engine import build_engine, build_session_factory
from packages.repo.entities import (
    Checkin,
    Document,
    FollowupRound,
    Import,
    LlmCallLog,
    NewPlan,
    NewPlanTask,
    OAuthConnection,
    Plan,
    PlanExport,
    PlanRevision,
    PlanSession,
    PlanTask,
    Profile,
    RoleModel,
    TaskStatusUpdate,
    User,
)
from packages.repo.memory.checkin import InMemoryCheckinRepo
from packages.repo.memory.document import InMemoryDocumentRepo
from packages.repo.memory.export import InMemoryPlanExportRepo
from packages.repo.memory.followup import InMemoryFollowupRoundRepo
from packages.repo.memory.imports import InMemoryImportRepo
from packages.repo.memory.llm_call import InMemoryLlmCallRepo
from packages.repo.memory.oauth import InMemoryOAuthConnectionRepo
from packages.repo.memory.plan import InMemoryPlanRepo
from packages.repo.memory.plan_session import InMemoryPlanSessionRepo
from packages.repo.memory.plan_task import InMemoryPlanTaskRepo
from packages.repo.memory.profile import InMemoryProfileRepo
from packages.repo.memory.revision import InMemoryPlanRevisionRepo
from packages.repo.memory.role_model import InMemoryRoleModelRepo
from packages.repo.memory.user import InMemoryUserRepo
from packages.repo.models import Base
from packages.repo.pg.checkin import PgCheckinRepo
from packages.repo.pg.document import PgDocumentRepo
from packages.repo.pg.export import PgPlanExportRepo
from packages.repo.pg.followup import PgFollowupRoundRepo
from packages.repo.pg.imports import PgImportRepo
from packages.repo.pg.llm_call import PgLlmCallRepo
from packages.repo.pg.oauth import PgOAuthConnectionRepo
from packages.repo.pg.plan import PgPlanRepo
from packages.repo.pg.plan_session import PgPlanSessionRepo
from packages.repo.pg.plan_task import PgPlanTaskRepo
from packages.repo.pg.profile import PgProfileRepo
from packages.repo.pg.revision import PgPlanRevisionRepo
from packages.repo.pg.role_model import PgRoleModelRepo
from packages.repo.pg.user import PgUserRepo
from packages.repo.ports import (
    CheckinRepo,
    DocumentRepo,
    FollowupRoundRepo,
    ImportRepo,
    LlmCallRepo,
    OAuthConnectionRepo,
    PlanExportRepo,
    PlanRepo,
    PlanRevisionRepo,
    PlanSessionRepo,
    PlanTaskRepo,
    ProfileRepo,
    RoleModelRepo,
    UserRepo,
)

__all__ = [
    # engine / schema
    "Base",
    "build_engine",
    "build_session_factory",
    # entities
    "Checkin",
    "Document",
    "FollowupRound",
    "Import",
    "OAuthConnection",
    "Plan",
    "PlanExport",
    "PlanRevision",
    "PlanSession",
    "PlanTask",
    "Profile",
    "RoleModel",
    "User",
    # input models
    "LlmCallLog",
    "NewPlan",
    "NewPlanTask",
    "TaskStatusUpdate",
    # ports
    "CheckinRepo",
    "DocumentRepo",
    "FollowupRoundRepo",
    "ImportRepo",
    "LlmCallRepo",
    "OAuthConnectionRepo",
    "PlanExportRepo",
    "PlanRepo",
    "PlanRevisionRepo",
    "PlanSessionRepo",
    "PlanTaskRepo",
    "ProfileRepo",
    "RoleModelRepo",
    "UserRepo",
    # in-memory implementations
    "InMemoryCheckinRepo",
    "InMemoryDocumentRepo",
    "InMemoryFollowupRoundRepo",
    "InMemoryImportRepo",
    "InMemoryLlmCallRepo",
    "InMemoryOAuthConnectionRepo",
    "InMemoryPlanExportRepo",
    "InMemoryPlanRepo",
    "InMemoryPlanRevisionRepo",
    "InMemoryPlanSessionRepo",
    "InMemoryPlanTaskRepo",
    "InMemoryProfileRepo",
    "InMemoryRoleModelRepo",
    "InMemoryUserRepo",
    # postgres implementations
    "PgCheckinRepo",
    "PgDocumentRepo",
    "PgFollowupRoundRepo",
    "PgImportRepo",
    "PgLlmCallRepo",
    "PgOAuthConnectionRepo",
    "PgPlanExportRepo",
    "PgPlanRepo",
    "PgPlanRevisionRepo",
    "PgPlanSessionRepo",
    "PgPlanTaskRepo",
    "PgProfileRepo",
    "PgRoleModelRepo",
    "PgUserRepo",
]
