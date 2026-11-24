"""Request models for the HTTP API.

Response payloads are assembled by the routers from deterministic analytics results and documented in
``docs/API.md``; only inputs are validated here, so an unexpected response field never blocks a request.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class SaveCreate(BaseModel):
    """Body for creating a save."""

    name: str = Field(min_length=1, max_length=128)
    game_version: str | None = None
    game_build: str | None = None


class WatchItemCreate(BaseModel):
    """Add one player to the watchlist."""

    instance_id: int
    tag: str | None = None
    note: str | None = None


class WatchItemUpdate(BaseModel):
    """Change the tag or note of a watchlist entry."""

    tag: str | None = None
    note: str | None = None


class EvaluateRequest(BaseModel):
    """Score one player against one role template."""

    instance_id: int
    role_key: str


class ScoutingSearchRequest(BaseModel):
    """Role-aware scouting search."""

    save_id: int | None = None
    role_key: str | None = None
    query: str | None = None
    position: str | None = None
    position_group: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_ca: int | None = None
    min_pa: int | None = None
    max_value: int | None = None
    max_wage: int | None = None
    club_id: int | None = None
    limit: int = Field(default=25, ge=1, le=200)


class ConversationCreate(BaseModel):
    """Create a decision conversation."""

    save_id: int | None = None
    title: str | None = Field(default=None, max_length=128)


class AskRequest(BaseModel):
    """Ask one question inside a conversation."""

    question: str = Field(min_length=2, max_length=2000)
    save_id: int | None = None
    instance_id: int | None = None
    club_id: int | None = None


class SquadWeights(BaseModel):
    """Per-request override of the six squad-score weights; unset components keep the profile value."""

    coverage: float | None = Field(default=None, ge=0, le=1)
    depth: float | None = Field(default=None, ge=0, le=1)
    age: float | None = Field(default=None, ge=0, le=1)
    fit: float | None = Field(default=None, ge=0, le=1)
    wage: float | None = Field(default=None, ge=0, le=1)
    potential: float | None = Field(default=None, ge=0, le=1)

    def overrides(self) -> dict[str, float]:
        """Only the components the caller actually sent."""
        return {key: value for key, value in self.model_dump().items() if value is not None}


class TacticalProfileUpdate(BaseModel):
    """Create or replace one weight profile of a save."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    weights: SquadWeights = Field(default_factory=SquadWeights)
    is_default: bool = False


class RecruitmentSearchRequest(BaseModel):
    """Filters for the recruitment engine."""

    save_id: int | None = None
    slot: str | None = None
    min_age: int | None = Field(default=None, ge=10, le=60)
    max_age: int | None = Field(default=None, ge=10, le=60)
    max_value: int | None = Field(default=None, ge=0)
    max_wage: int | None = Field(default=None, ge=0)
    min_score: float | None = Field(default=None, ge=0, le=100)
    exclude_own_club: bool = True
    limit: int = Field(default=25, ge=1, le=200)


class ShortlistRequest(BaseModel):
    """Generate and store a shortlist."""

    save_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    slot: str | None = None
    role_key: str | None = None
    budget: int | None = Field(default=None, ge=0)
    min_age: int | None = Field(default=None, ge=10, le=60)
    max_age: int | None = Field(default=None, ge=10, le=60)
    limit: int = Field(default=10, ge=1, le=50)
    persist: bool = True


class CompareRequest(BaseModel):
    """Compare several players with the same scoring weights."""

    save_id: int | None = None
    instance_ids: list[int] = Field(min_length=2, max_length=5)


class DealRequest(BaseModel):
    """Deal model inputs for one prospective signing."""

    save_id: int | None = None
    instance_id: int
    fee: float | None = Field(default=None, ge=0)
    budget: int | None = Field(default=None, ge=0)
    wage_period: str = Field(default="week", pattern="^(week|month|year)$")
    contract_years: float | None = Field(default=None, gt=0, le=20)


class IdentityConflictResolve(BaseModel):
    """人工处理一条身份冲突。"""

    decision: str = Field(pattern="^(same|different|defer)$")
    keep: str = Field(default="existing", pattern="^(existing|incoming)$")
    note: str | None = Field(default=None, max_length=512)


class FieldEvidenceCaptureIn(BaseModel):
    """One field sample captured by the reader or game UI."""

    player_instance_id: int | None = Field(default=None, ge=1)
    player_instance_uid: str | None = Field(default=None, min_length=1, max_length=64)
    field_id: str = Field(min_length=1, max_length=64)
    object_type: str = Field(min_length=1, max_length=32)
    raw_value: str | None = Field(default=None, max_length=4096)
    expected_value: str | None = Field(default=None, max_length=4096)
    game_build: str | None = Field(default=None, max_length=64)
    plugin_version: str | None = Field(default=None, max_length=32)
    layout_version: str | None = Field(default=None, max_length=32)
    game_date: date | None = None
    observed_at: datetime
    evidence_source: str = Field(default="reader_capture", max_length=32)
    validation_status: str = Field(default="Pending", pattern="^(Pending|Candidate|Verified|Rejected)$")
    simulated: bool = False


class FieldEvidenceCaptureBatch(BaseModel):
    """Batch upload of captured field samples."""

    items: list[FieldEvidenceCaptureIn] = Field(min_length=1, max_length=500)


class CanonicalDecisionIn(BaseModel):
    """Manual review decision for one canonical group."""

    action: str = Field(pattern="^(select_snapshot|exclude_game_date|keep_pending)$")
    selected_snapshot_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=512)
    evidence: dict | None = None


class CaptureRunIn(BaseModel):
    """Register/update one automatic capture attempt."""

    game_date: date | None = None
    reader_version: str | None = Field(default=None, max_length=32)
    game_build: str | None = Field(default=None, max_length=64)
    scan_scope: str = Field(default="players", min_length=1, max_length=32)
    status: str = Field(default="monitoring", max_length=24)
    scan_id: str | None = Field(default=None, max_length=64)
    import_job_id: int | None = None
    supplemental: bool = False
    revision: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = None
    metadata: dict | None = None
    date_source: str | None = Field(default=None, max_length=32)
    date_confidence: str | None = Field(default=None, max_length=16)
    date_read_status: str | None = Field(default=None, max_length=24)


class CaptureRunUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=24)
    attempt_count: int | None = Field(default=None, ge=0)
    next_retry_at: datetime | None = None
    scan_id: str | None = Field(default=None, max_length=64)
    import_job_id: int | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = None


class UnresolvedResolveIn(BaseModel):
    """人工把一条待确认候选关联到一个既有身份。

    必须显式 ``confirm=true``：接口不会把"看起来像"当成事实。目标只能是同一存档里的球员实例或球员。
    """

    player_instance_id: int | None = Field(default=None, ge=1)
    player_id: int | None = Field(default=None, ge=1)
    confirm: bool = False
    note: str | None = Field(default=None, max_length=512)


class UnresolvedDismissIn(BaseModel):
    """人工忽略一条候选；观察记录保留，不物理删除。"""

    reason: str = Field(min_length=1, max_length=256)
    note: str | None = Field(default=None, max_length=512)

class SaveEvidenceIn(BaseModel):
    """一条由 Reader 产生、Agent 转发的身份证据（只含规范化哈希，不含原始内容）。"""

    type: str = Field(min_length=1, max_length=64)
    source: str = Field(default="file", max_length=32)
    hash: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=64)
    confidence: str = Field(default="none", max_length=16)
    observed_at: datetime | None = None
    detail: str | None = Field(default=None, max_length=512)


class SaveIdentityRegisterIn(BaseModel):
    """身份注册/重复上报。``identity_status`` 只是客户端声明，后端会按证据封顶。"""

    save_id: int | None = None
    fingerprint: str = Field(min_length=8, max_length=128)
    fingerprint_version: int = Field(default=1, ge=1, le=99)
    identity_status: str = Field(default="unknown", max_length=24)
    confidence: str = Field(default="none", max_length=16)
    kind: str = Field(default="save_file", max_length=32)
    game_build: str | None = Field(default=None, max_length=64)
    plugin_version: str | None = Field(default=None, max_length=32)
    ambiguous: bool = False
    evidence: list[SaveEvidenceIn] = Field(default_factory=list)
    agent_id: str | None = Field(default=None, max_length=64)
    session_key: str | None = Field(default=None, max_length=128)


class SaveIdentityVerifyIn(BaseModel):
    """人工确认把身份升级为 verified；必须说明确认主体与依据。"""

    confirmed_fingerprint: str = Field(min_length=8, max_length=128)
    basis: str = Field(min_length=1, max_length=512)
    actor: str = Field(default="local", max_length=64)


class SaveSessionStartIn(BaseModel):
    """一次游戏进程内的会话登记；``session_key`` 幂等。"""

    save_id: int | None = None
    identity_id: int = Field(ge=1)
    session_key: str = Field(min_length=1, max_length=128)
    process_id: int | None = Field(default=None, ge=1)
    process_start_time: datetime | None = None
    game_build: str | None = Field(default=None, max_length=64)
    plugin_version: str | None = Field(default=None, max_length=32)
    agent_id: str | None = Field(default=None, max_length=64)


class SaveSessionHeartbeatIn(BaseModel):
    """会话心跳；身份、指纹或 build 不一致时后端会失效该会话。"""

    identity_id: int = Field(ge=1)
    fingerprint: str | None = Field(default=None, max_length=128)
    game_build: str | None = Field(default=None, max_length=64)
    agent_version: str | None = Field(default=None, max_length=32)


class SaveSessionInvalidateIn(BaseModel):
    """显式失效会话（存档切换 / 游戏关闭 / Agent 重启）。"""

    reason: str = Field(min_length=1, max_length=64)
