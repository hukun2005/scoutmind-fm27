"""SQLAlchemy models for the ScoutMind core schema.

Design rules that the ingestion and analytics code rely on:

* ``players`` is the relatively stable identity of a person; ``player_instances`` is that person inside one FM save.
* ``player_snapshots`` is append-only. Re-importing the same observation never rewrites history.
* Every save-scoped row carries ``fm_save_id`` so a future multi-user build can isolate data by user and save.
* Money columns keep the game currency unit; ``currency`` records which currency a transfer used.
* Missing facts stay ``NULL``. Nothing here has a server-side default that could be mistaken for observed data.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .utils import utcnow


class Base(DeclarativeBase):
    """Declarative base for every ScoutMind table."""


class TimestampMixin:
    """Adds the two import timestamps used across operational tables."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(TimestampMixin, Base):
    """Local operator account. The MVP ships one implicit user but the column exists for isolation."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))


class FmSave(TimestampMixin, Base):
    """One Football Manager career save; every domain row belongs to exactly one."""

    __tablename__ = "fm_saves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    game_version: Mapped[str | None] = mapped_column(String(64))
    game_build: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 用户指定的主执教俱乐部。单一事实来源：所有 is_user_club 标记都由它派生。
    # 故意不加外键：clubs.fm_save_id 指向本表，两个方向都建外键会形成环，SQLite 无法建表/删表。
    # 归属校验由 ClubResolver.set_user_club 负责（必须属于同一存档）。
    user_club_id: Mapped[int | None] = mapped_column(Integer)
    # 本队是怎么定下来的：manual（你自己选的）/ payload（报文声明）/ None（未指定）。
    user_club_source: Mapped[str | None] = mapped_column(String(16))


class DataSource(TimestampMixin, Base):
    """Aggregated provenance per save and source kind, so the UI can show where records came from."""

    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("fm_save_id", "source", name="uq_data_source_save_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))
    record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class ImportJob(TimestampMixin, Base):
    """One accepted scan payload. ``(fm_save_id, scan_id)`` is the idempotency key.

    ``scan_id`` alone is not unique: two different saves may legitimately receive a scan that happens
    to carry the same id (for example a reader restarted with a fixed id). Uniqueness is therefore
    scoped to the save, matching how the importer looks up duplicates.
    """

    __tablename__ = "import_jobs"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "scan_id", name="uq_import_jobs_save_scan"),
        # V3.2.7.3：同一存档内 operation_id 唯一。并发重放由数据库约束兜底，不能只靠先查后写。
        UniqueConstraint("fm_save_id", "operation_id", name="uq_import_jobs_save_operation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    scan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))
    # V3.2.7.4：queued / running / cancel_requested / succeeded / partial / failed / rejected / cancelled
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    player_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    raw_payload_path: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(64))
    # 存档身份/会话归属。故意不加外键：历史行为 NULL，且 SQLite 对新增外键需要重建整表，
    # 归属校验由导入服务负责（与 fm_saves.user_club_id 的无外键设计一致）。
    save_identity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    save_session_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # V3.2.7.3：一次导入操作的身份。operation_id 在存档内唯一，用于幂等与拒绝追溯。
    operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # 任务创建时绑定的写入代次；与当前 save_write_gates.generation 不一致即视为旧任务。
    save_generation: Mapped[int | None] = mapped_column(Integer)
    # 写入被 fence 拒绝时的稳定原因码（write_fence_stale 等）；正常任务为 NULL。
    rejected_reason: Mapped[str | None] = mapped_column(String(64))
    # V3.2.7.4：每次请求（含幂等重放）递增，用于审计重试与冲突次数。
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # 取消是状态转换：请求时间与终态时间分开记录，已提交的事务不可撤销。
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)

    rows: Mapped[list[ImportRow]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ImportRow(TimestampMixin, Base):
    """A rejected or skipped row inside an import, kept for diagnostics and re-processing."""

    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_job_id: Mapped[int] = mapped_column(ForeignKey("import_jobs.id"), nullable=False, index=True)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    entity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text)

    job: Mapped[ImportJob] = relationship(back_populates="rows")


class Club(TimestampMixin, Base):
    """A club inside one save, identified by the save-local UID when the scanner provides it."""

    __tablename__ = "clubs"
    __table_args__ = (UniqueConstraint("fm_save_id", "uid", name="uq_club_save_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    nation: Mapped[str | None] = mapped_column(String(64))
    league: Mapped[str | None] = mapped_column(String(128))
    reputation: Mapped[int | None] = mapped_column(Integer)
    is_user_club: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 解析器补充：归一化名称用于合并"只有名字"和"带 ID"的两条记录；来源与可信度用于界面展示。
    normalized_name: Mapped[str | None] = mapped_column(String(128), index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    external_ids_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class Player(TimestampMixin, Base):
    """Stable person identity across saves. Never carries save-specific IDs."""

    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(64))

    instances: Mapped[list[PlayerInstance]] = relationship(back_populates="player")


class PlayerInstance(TimestampMixin, Base):
    """A player as they exist inside one save. UIDs are save-local and may be reused by the game."""

    __tablename__ = "player_instances"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "save_local_uid", "uid_occurrence", name="uq_instance_save_uid"),
        Index("ix_instance_game_unique_id", "game_unique_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    save_local_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    uid_occurrence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    game_unique_id: Mapped[str | None] = mapped_column(String(64))
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    position: Mapped[str | None] = mapped_column(String(16))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    player: Mapped[Player] = relationship(back_populates="instances")


class IdentityMatch(TimestampMixin, Base):
    """Audit trail for how an incoming record was matched to a player identity."""

    __tablename__ = "identity_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class IdentityConflict(TimestampMixin, Base):
    """一次无法安全合并的身份冲突，保留证据供人工复核。

    典型场景：同一个 save_local_uid 出现过不同出生日期，或缺少出生日期且姓名不同——这时不能猜测
    "是不是同一个人"，只能把两条记录都保留下来并记录冲突，等下一轮扫描或人工确认。
    """

    __tablename__ = "identity_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    save_local_uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    existing_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    incoming_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    existing_name: Mapped[str | None] = mapped_column(String(128))
    incoming_name: Mapped[str | None] = mapped_column(String(128))
    existing_birth_date: Mapped[date | None] = mapped_column(Date)
    incoming_birth_date: Mapped[date | None] = mapped_column(Date)
    resolution: Mapped[str] = mapped_column(String(32), default="kept_both", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False, index=True)
    conflict_fields: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Float)
    source_scan_id: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    __table_args__ = (
        Index("ix_identity_conflicts_save_uid", "fm_save_id", "save_local_uid"),
    )


class IdentityConflictAction(TimestampMixin, Base):
    """人工复核身份冲突的操作审计（追加写，不更新、不删除）。"""

    __tablename__ = "identity_conflict_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conflict_id: Mapped[int] = mapped_column(ForeignKey("identity_conflicts.id"), nullable=False, index=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    __table_args__ = (Index("ix_conflict_actions_conflict", "conflict_id", "created_at"),)


class PlayerAttribute(TimestampMixin, Base):
    """Attribute dictionary. Values are the FM 1-20 scale unless the source says otherwise."""

    __tablename__ = "player_attributes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PlayerSnapshot(TimestampMixin, Base):
    """One observation of a player instance. Rows are appended, never updated in place."""

    __tablename__ = "player_snapshots"
    __table_args__ = (
        UniqueConstraint("player_instance_id", "observed_at", name="uq_snapshot_instance_time"),
        Index("ix_snapshot_instance_observed", "player_instance_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    game_date: Mapped[date | None] = mapped_column(Date)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer)
    ca: Mapped[int | None] = mapped_column(Integer)
    pa: Mapped[int | None] = mapped_column(Integer)
    market_value: Mapped[int | None] = mapped_column(Integer)
    wage: Mapped[int | None] = mapped_column(Integer)
    contract_end: Mapped[date | None] = mapped_column(Date)
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    position: Mapped[str | None] = mapped_column(String(16))
    minutes_played: Mapped[int | None] = mapped_column(Integer)
    appearances: Mapped[int | None] = mapped_column(Integer)
    goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    # Profile facts some sources report directly. All nullable: absent stays unknown.
    height_cm: Mapped[int | None] = mapped_column(Integer)
    foot: Mapped[str | None] = mapped_column(String(8))
    world_reputation: Mapped[int | None] = mapped_column(Integer)
    data_completeness: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))

    values: Mapped[list[PlayerAttributeValue]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class PlayerAttributeValue(TimestampMixin, Base):
    """A single attribute reading attached to one snapshot."""

    __tablename__ = "player_attribute_values"
    __table_args__ = (UniqueConstraint("player_snapshot_id", "attribute_id", name="uq_value_snapshot_attr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_snapshot_id: Mapped[int] = mapped_column(ForeignKey("player_snapshots.id"), nullable=False, index=True)
    attribute_id: Mapped[int] = mapped_column(ForeignKey("player_attributes.id"), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    snapshot: Mapped[PlayerSnapshot] = relationship(back_populates="values")
    attribute: Mapped[PlayerAttribute] = relationship()


class Transfer(TimestampMixin, Base):
    """A historical transfer record. Only ``status='completed'`` rows enter price statistics."""

    __tablename__ = "transfer_history"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "source_record_id", name="uq_transfer_save_record"),
        Index("ix_transfer_save_date", "fm_save_id", "transfer_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"), index=True)
    player_name: Mapped[str] = mapped_column(String(128), nullable=False)
    from_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    to_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    from_club_name: Mapped[str | None] = mapped_column(String(128))
    to_club_name: Mapped[str | None] = mapped_column(String(128))
    transfer_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    season: Mapped[str | None] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    base_fee: Mapped[float | None] = mapped_column(Float)
    fee_paid: Mapped[float | None] = mapped_column(Float)
    addons_potential: Mapped[float | None] = mapped_column(Float)
    effective_fee: Mapped[float | None] = mapped_column(Float)
    player_age_at_transfer: Mapped[int | None] = mapped_column(Integer)
    player_ca_at_transfer: Mapped[int | None] = mapped_column(Integer)
    player_pa_at_transfer: Mapped[int | None] = mapped_column(Integer)
    contract_remaining_months: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    # 历史转会管道（SM-013）：官宣/生效日期、二转分成、工资分摊、来源与原始行。
    announcement_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    sell_on_clause_pct: Mapped[float | None] = mapped_column(Float)
    wage_contribution: Mapped[float | None] = mapped_column(Float)
    loan_fee: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_sources.id"), index=True)
    raw_payload_json: Mapped[str | None] = mapped_column(Text)
    # 原始金额字符串（SM-022）：解析后的金额与本值同时保留，便于审计。
    fee_raw: Mapped[str | None] = mapped_column(Text)
    addons_raw: Mapped[str | None] = mapped_column(Text)
    loan_fee_raw: Mapped[str | None] = mapped_column(Text)
    currency_original: Mapped[str | None] = mapped_column(String(16))

    components: Mapped[list[TransferFeeComponent]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )


class TransferSource(TimestampMixin, Base):
    """转会数据来源登记：名称、获取方式、许可与是否支持历史交易。"""

    __tablename__ = "transfer_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    license: Mapped[str | None] = mapped_column(String(128))
    supports_history: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class TransferImportRun(TimestampMixin, Base):
    """一次历史转会导入的批次报告（行数、导入、重复、拒绝、原始哈希）。"""

    __tablename__ = "transfer_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("transfer_sources.id"), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="completed", nullable=False)


class TransferFeeComponent(TimestampMixin, Base):
    """A fee component such as an installment, add-on or sell-on clause."""

    __tablename__ = "transfer_fee_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("transfer_history.id"), nullable=False, index=True)
    component_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    condition: Mapped[str | None] = mapped_column(String(256))

    transfer: Mapped[Transfer] = relationship(back_populates="components")


class Watchlist(TimestampMixin, Base):
    """A named watchlist; the default one is created lazily per save."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "fm_save_id", "name", name="uq_watchlist_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), default="默认关注", nullable=False)


class WatchlistItem(TimestampMixin, Base):
    """A followed player instance, optionally tagged for a development workflow."""

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "player_instance_id", name="uq_watchlist_instance"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    tag: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(512))
    # 关注状态：watching / preparing / paused / done；只描述用户的工作流，不参与任何能力计算。
    status: Mapped[str] = mapped_column(String(16), default="watching", server_default="watching", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)


class WatchRule(TimestampMixin, Base):
    """Automatic watchlist rule, e.g. "under 21 with PA above 150"."""

    __tablename__ = "watch_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    conditions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Alert(TimestampMixin, Base):
    """A generated, user-facing notification tied to one save and player."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "player_instance_id", "alert_type", "title", name="uq_alert_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlayerValuation(TimestampMixin, Base):
    """A stored valuation result so a past answer can be reproduced and audited."""

    __tablename__ = "player_valuations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    method: Mapped[str] = mapped_column(String(48), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    low: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    insufficient_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ScoreTemplateVersion(TimestampMixin, Base):
    """A versioned role template. Scores are only comparable inside one template version."""

    __tablename__ = "score_template_versions"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_template_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    position_group: Mapped[str] = mapped_column(String(8), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weights_json: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), default="role-score-1", nullable=False)


class PlayerScore(TimestampMixin, Base):
    """A computed role score with its component breakdown, kept for explainability."""

    __tablename__ = "player_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    components_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class TacticalProfile(TimestampMixin, Base):
    """A named squad-score weight profile.

    The six components (coverage, depth, age, tactical fit, wage health, potential) are the same formula for every
    profile; only their weights differ, so two profiles never change what a dimension measures.
    """

    __tablename__ = "tactical_profiles"
    __table_args__ = (UniqueConstraint("fm_save_id", "key", name="uq_tactical_profile_save_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256))
    weight_coverage: Mapped[float] = mapped_column(Float, default=0.25, nullable=False)
    weight_depth: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    weight_age: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    weight_fit: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    weight_wage: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    weight_potential: Mapped[float] = mapped_column(Float, default=0.10, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PlayerAvailability(TimestampMixin, Base):
    """One observation of a player's availability: listing flags, injury and loan ownership.

    Three-valued on purpose. ``None`` means the source did not report the field, ``True``/``False`` are observations.
    Injury proneness is a player attribute and never implies the player is currently injured; a missing injury
    record never means "fit".
    """

    __tablename__ = "player_availability"
    __table_args__ = (
        UniqueConstraint("player_instance_id", "observed_at", name="uq_availability_instance_time"),
        Index("ix_availability_instance_time", "player_instance_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    game_date: Mapped[date | None] = mapped_column(Date)
    listed: Mapped[bool | None] = mapped_column(Boolean)
    loan_listed: Mapped[bool | None] = mapped_column(Boolean)
    not_for_sale: Mapped[bool | None] = mapped_column(Boolean)
    set_for_release: Mapped[bool | None] = mapped_column(Boolean)
    injury_proneness: Mapped[int | None] = mapped_column(Integer)
    injured: Mapped[bool | None] = mapped_column(Boolean)
    injury_start_date: Mapped[date | None] = mapped_column(Date)
    expected_return_date: Mapped[date | None] = mapped_column(Date)
    injury_note: Mapped[str | None] = mapped_column(String(256))
    parent_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    loan_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    team_type: Mapped[str | None] = mapped_column(String(16))
    agreed_to_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    agreed_transfer_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))


class LoanRecord(TimestampMixin, Base):
    """A loan relationship: who owns the player, who plays him, and whether a purchase clause exists.

    Purchase option and obligation are three-valued: a source that does not expose the clause leaves them NULL and
    callers must show "unknown", never "no clause".
    """

    __tablename__ = "loan_records"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "source_record_id", name="uq_loan_save_record"),
        Index("ix_loan_instance", "player_instance_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    source_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"), index=True)
    parent_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    loan_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    parent_club_name: Mapped[str | None] = mapped_column(String(128))
    loan_club_name: Mapped[str | None] = mapped_column(String(128))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    has_option: Mapped[bool | None] = mapped_column(Boolean)
    has_obligation: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))


class TransferCandidate(TimestampMixin, Base):
    """A club change found by diffing two snapshots.

    This is a candidate event, not a completed transfer. It must be confirmed (against a transfer channel) or
    dismissed before it may influence any statistic.
    """

    __tablename__ = "transfer_candidates"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "player_instance_id", "to_club_id", "detected_at", name="uq_candidate_change"
        ),
        Index("ix_candidate_save_status", "fm_save_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    from_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    to_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    kind: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    previous_observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="candidate", nullable=False)
    confirmed_transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_history.id"))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class SquadAssignment(TimestampMixin, Base):
    """CSV / 手动导入的阵容归属：谁在哪个俱乐部、属于哪个梯队、是否租借。

    与 ``player_availability`` 分开：那个表描述"数据源观测到的状态"，本表描述"用户/文件声明的阵容归属"。
    两者都不允许在没有依据时把球员算成自由球员。
    """

    __tablename__ = "squad_assignments"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "player_instance_id", "source", name="uq_assignment_player_source"),
        Index("ix_assignment_save_club", "fm_save_id", "club_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"), index=True)
    club_name_raw: Mapped[str | None] = mapped_column(String(128))
    squad_type: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    loan_status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class PlayerStatistic(TimestampMixin, Base):
    """Season or match aggregate performance of one player instance.

    Every column is nullable: a scanner that does not expose expected goals must leave ``xg`` NULL rather than 0,
    so performance screens can tell "zero" from "not read".
    """

    __tablename__ = "player_statistics"
    __table_args__ = (
        UniqueConstraint("player_instance_id", "scope", "period", name="uq_player_stat_period"),
        Index("ix_player_stat_instance_scope", "player_instance_id", "scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="season", nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    competition: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    appearances: Mapped[int | None] = mapped_column(Integer)
    starts: Mapped[int | None] = mapped_column(Integer)
    minutes_played: Mapped[int | None] = mapped_column(Integer)
    goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    xg: Mapped[float | None] = mapped_column(Float)
    key_passes: Mapped[int | None] = mapped_column(Integer)
    passes_attempted: Mapped[int | None] = mapped_column(Integer)
    passes_completed: Mapped[int | None] = mapped_column(Integer)
    dribbles: Mapped[int | None] = mapped_column(Integer)
    tackles: Mapped[int | None] = mapped_column(Integer)
    interceptions: Mapped[int | None] = mapped_column(Integer)
    clearances: Mapped[int | None] = mapped_column(Integer)
    aerials_won: Mapped[int | None] = mapped_column(Integer)
    saves: Mapped[int | None] = mapped_column(Integer)
    conceded: Mapped[int | None] = mapped_column(Integer)
    clean_sheets: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))


class ScoutingReport(TimestampMixin, Base):
    """A generated report. ``payload_json`` is the whole answer so it can be replayed without recomputation."""

    __tablename__ = "scouting_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    reliability_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class RecruitmentShortlist(TimestampMixin, Base):
    """One generated shortlist for a position or role, with the criteria that produced it."""

    __tablename__ = "recruitment_shortlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    position_code: Mapped[str | None] = mapped_column(String(16))
    role_key: Mapped[str | None] = mapped_column(String(64))
    budget: Mapped[int | None] = mapped_column(Integer)
    criteria_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    items: Mapped[list[RecruitmentShortlistItem]] = relationship(
        back_populates="shortlist", cascade="all, delete-orphan"
    )


class RecruitmentShortlistItem(TimestampMixin, Base):
    """A ranked candidate inside one shortlist with the score breakdown that produced the rank."""

    __tablename__ = "recruitment_shortlist_items"
    __table_args__ = (UniqueConstraint("shortlist_id", "player_instance_id", name="uq_shortlist_instance"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shortlist_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_shortlists.id"), nullable=False, index=True
    )
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    shortlist: Mapped[RecruitmentShortlist] = relationship(back_populates="items")


class AiReport(TimestampMixin, Base):
    """One persisted AI Sporting Director answer with its citations and reliability split."""

    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("agent_conversations.id"), index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    reliability_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    tool_calls_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)


class ReaderCompatibility(TimestampMixin, Base):
    """Known-good FM27 build / plugin combinations for the external reader."""

    __tablename__ = "reader_compatibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[str | None] = mapped_column(String(32))
    build_id: Mapped[str | None] = mapped_column(String(32))
    plugin_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)


class AlgorithmVersion(TimestampMixin, Base):
    """Registered algorithm identifiers so reports can name the exact computation used."""

    __tablename__ = "algorithm_versions"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_algorithm_key_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(48), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))


class AgentConversation(TimestampMixin, Base):
    """A decision-support conversation scoped to one save."""

    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), default="新的分析", nullable=False)

    messages: Mapped[list[AgentMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class AgentMessage(TimestampMixin, Base):
    """One user question or assistant answer, including the tool calls behind it."""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("agent_conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_json: Mapped[str | None] = mapped_column(Text)
    tool_calls_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    conversation: Mapped[AgentConversation] = relationship(back_populates="messages")

class FieldEvidenceSample(TimestampMixin, Base):
    """One captured field sample, scoped to a save and player instance.

    Repeated captures of the same (save, instance, field, observed_at) are idempotent.
    Simulated samples can never be stored as Verified.
    """

    __tablename__ = "field_evidence_samples"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "player_instance_id", "field_id", "observed_at",
            name="uq_field_evidence_save_instance_field_time",
        ),
        Index("ix_field_evidence_save_status", "fm_save_id", "validation_status"),
        Index("ix_field_evidence_save_field", "fm_save_id", "field_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    field_id: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    game_build: Mapped[str | None] = mapped_column(String(64))
    plugin_version: Mapped[str | None] = mapped_column(String(32))
    layout_version: Mapped[str | None] = mapped_column(String(32))
    game_date: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class PlayerObservationCanonical(TimestampMixin, Base):
    """Canonical choice for one (player instance, game date), without deleting raw snapshots.

    Identical duplicates resolve to the latest observation. Content differences stay
    ``needs_review`` and keep every raw snapshot; no canonical id is fabricated.
    """

    __tablename__ = "player_observation_canonicals"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "player_instance_id", "game_date",
            name="uq_canonical_save_instance_game_date",
        ),
        Index("ix_canonical_save_status", "fm_save_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    canonical_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("player_snapshots.id"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_content_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    conflict_types_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    changed_fields_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlayerObservationCanonicalAction(TimestampMixin, Base):
    """Append-only audit record for a manual canonical decision."""

    __tablename__ = "player_observation_canonical_actions"
    __table_args__ = (
        Index("ix_canonical_action_save_canonical", "fm_save_id", "canonical_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_id: Mapped[int] = mapped_column(ForeignKey("player_observation_canonicals.id"), nullable=False, index=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False)
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    reviewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("player_snapshots.id"))
    previous_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class CaptureRun(TimestampMixin, Base):
    """One automatic capture attempt for a save/game-date scope.

    The formal row for a game date is revision 0; supplemental scans use revision > 0 and never
    overwrite it. Failures/attempts remain as history, not as snapshots.
    """

    __tablename__ = "capture_runs"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "game_date", "reader_version", "scan_scope", "revision",
            name="uq_capture_save_date_reader_scope_revision",
        ),
        Index("ix_capture_save_status", "fm_save_id", "status"),
        Index("ix_capture_save_date", "fm_save_id", "game_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    game_date: Mapped[date | None] = mapped_column(Date)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))
    scan_scope: Mapped[str] = mapped_column(String(32), default="players", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="monitoring", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    scan_id: Mapped[str | None] = mapped_column(String(64))
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"))
    supplemental: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # 游戏日期的来源与可信度：没有经过真实内存读取验证的日期不能标成 verified。
    date_source: Mapped[str | None] = mapped_column(String(32))
    date_confidence: Mapped[str | None] = mapped_column(String(16))
    date_read_status: Mapped[str | None] = mapped_column(String(24))
    # 存档身份/会话归属；历史行为 NULL。无外键的理由与 ImportJob 相同。
    save_identity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    save_session_id: Mapped[int | None] = mapped_column(Integer, index=True)


class TransferEventCandidate(TimestampMixin, Base):
    """An observed club change; never promoted to a paid transfer without explicit evidence."""

    __tablename__ = "transfer_event_candidates"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "player_instance_id", "from_club_id", "to_club_id", "game_date",
            name="uq_transfer_event_save_player_clubs_date",
        ),
        Index("ix_transfer_event_save_status", "fm_save_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int] = mapped_column(ForeignKey("player_instances.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), default="unknown_pending_verification", nullable=False)
    from_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    to_club_id: Mapped[int | None] = mapped_column(ForeignKey("clubs.id"))
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(24), default="Unverified", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    linked_transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_history.id"))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class UnresolvedPlayerCandidate(TimestampMixin, Base):
    """A player an upstream source could not identify, kept as a candidate instead of a fake identity.

    The row never participates in canonical observations, valuations, squad analysis or scouting until a
    human resolves it. ``candidate_key`` scopes correlation to one save: it comes from a stable upstream
    identity when one exists, otherwise it is unique per observation, so two sentinel rows from the same
    scan stay two candidates. Name, birth date and the sentinel value are evidence, never keys.
    """

    __tablename__ = "unresolved_player_candidates"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "candidate_key", name="uq_unresolved_candidate_save_key"),
        Index("ix_unresolved_candidate_save_status", "fm_save_id", "status"),
        Index("ix_unresolved_candidate_save_name", "fm_save_id", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    candidate_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # stable_id: a verified stable upstream identity; observation: this candidate is one observation only.
    source_identity_kind: Mapped[str] = mapped_column(String(24), default="observation", nullable=False)
    source_identity_value: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[str | None] = mapped_column(String(16))
    # Upstream identity evidence, kept verbatim for review.
    raw_uid: Mapped[str | None] = mapped_column(String(64))
    uid_status: Mapped[str] = mapped_column(String(16), nullable=False)
    uid_reason: Mapped[str | None] = mapped_column(String(64))
    # Derived cache for list filters and sorting. ``unresolved_player_observations`` stays the source of truth;
    # only the importer writes these columns.
    observation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    latest_ca: Mapped[int | None] = mapped_column(Integer)
    latest_pa: Mapped[int | None] = mapped_column(Integer)
    resolution_method: Mapped[str | None] = mapped_column(String(32))
    resolved_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    resolved_player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)
    dismissed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    dismiss_reason: Mapped[str | None] = mapped_column(String(256))
    evidence_summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    observations: Mapped[list[UnresolvedPlayerObservation]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class UnresolvedPlayerObservation(TimestampMixin, Base):
    """One raw observation of an unidentified player inside one scan.

    ``(fm_save_id, scan_id, row_index)`` is the idempotency key: re-importing the same scan never duplicates
    an observation. Candidate correlation is not implied by the key; see
    :class:`UnresolvedPlayerCandidate`.
    """

    __tablename__ = "unresolved_player_observations"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "scan_id", "row_index", name="uq_unresolved_observation_scan_row"),
        Index("ix_unresolved_observation_candidate", "candidate_id", "observed_at"),
        Index("ix_unresolved_observation_save_scan", "fm_save_id", "scan_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("unresolved_player_candidates.id"), nullable=False, index=True
    )
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    game_date: Mapped[date | None] = mapped_column(Date)
    raw_uid: Mapped[str | None] = mapped_column(String(64))
    uid_status: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(64))
    position: Mapped[str | None] = mapped_column(String(16))
    ca: Mapped[int | None] = mapped_column(Integer)
    pa: Mapped[int | None] = mapped_column(Integer)
    club_name: Mapped[str | None] = mapped_column(String(128))
    contract_end: Mapped[date | None] = mapped_column(Date)
    raw_evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    candidate: Mapped[UnresolvedPlayerCandidate] = relationship(back_populates="observations")


class UnresolvedPlayerAction(Base):
    """Append-only audit record for one manual decision on an unresolved candidate.

    The table deliberately has no ``updated_at``; the model refuses updates and deletes, so a decision
    can be superseded by a later row but never rewritten.
    """

    __tablename__ = "unresolved_player_actions"
    __table_args__ = (Index("ix_unresolved_action_candidate", "candidate_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("unresolved_player_candidates.id"), nullable=False, index=True
    )
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    target_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    note: Mapped[str | None] = mapped_column(String(512))
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


@event.listens_for(UnresolvedPlayerAction, "before_update")
@event.listens_for(UnresolvedPlayerAction, "before_delete")
def _reject_unresolved_action_rewrite(*_args: object) -> None:
    """Audit rows are immutable: a wrong decision is corrected by appending, never by editing."""
    raise ValueError("unresolved_player_actions 是不可覆盖的审计表：禁止更新或删除")


class SaveIdentity(TimestampMixin, Base):
    """一个存档的长期身份。

    ``identity_fingerprint`` 只由强证据（游戏内 Save ID / 世界 ID / 存档文件稳定元数据）生成；
    经理、俱乐部、日期、进程等第三优先级证据不进入指纹。历史存档以
    ``identity_status='unknown'`` + ``LEGACY_UNVERIFIED`` 证据标记，绝不冒充已验证。
    """

    __tablename__ = "save_identities"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "identity_version", "identity_fingerprint",
            name="uq_save_identity_save_version_fingerprint",
        ),
        Index("ix_save_identity_status", "identity_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 发现阶段可能还没有对应存档；故意不加外键（理由与 fm_saves.user_club_id 相同）。
    fm_save_id: Mapped[int | None] = mapped_column(Integer, index=True)
    identity_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    identity_status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    identity_confidence: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    identity_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    identity_kind: Mapped[str] = mapped_column(String(32), default="unresolved", nullable=False)
    game_build: Mapped[str | None] = mapped_column(String(64))
    plugin_version: Mapped[str | None] = mapped_column(String(32))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    # 只为“已验证”身份写入；升级主体与时间必须可追溯（V3.2.7.2）。
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(64))


class SaveEvidence(TimestampMixin, Base):
    """一条存档身份证据（只存规范化哈希与公开诊断字段，不存原始内存/文件内容）。"""

    __tablename__ = "save_evidences"
    __table_args__ = (
        Index("ix_save_evidence_identity_observed", "save_identity_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    save_identity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fm_save_id: Mapped[int | None] = mapped_column(Integer, index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_source: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    session_id: Mapped[int | None] = mapped_column(Integer, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class SaveSession(TimestampMixin, Base):
    """一次游戏进程内的存档会话。

    ``session_key`` 只用于区分进程会话，绝不作为存档身份；同一进程可先后加载多个存档。
    """

    __tablename__ = "save_sessions"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_save_sessions_session_key"),
        Index("ix_save_session_identity", "save_identity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int | None] = mapped_column(Integer, index=True)
    save_identity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    process_id: Mapped[int | None] = mapped_column(Integer)
    process_start_time: Mapped[datetime | None] = mapped_column(DateTime)
    session_key: Mapped[str] = mapped_column(String(128), nullable=False)
    session_started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    session_ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    game_build: Mapped[str | None] = mapped_column(String(64))
    plugin_version: Mapped[str | None] = mapped_column(String(32))
    agent_id: Mapped[str | None] = mapped_column(String(64))
    session_status: Mapped[str] = mapped_column(String(16), default="created", nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    invalidated_reason: Mapped[str | None] = mapped_column(String(64))
    # 会话创建时所属存档的写入代次；存档切换后该值落后于 gate.generation，旧会话不得再写。
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SaveWriteGate(TimestampMixin, Base):
    """每个存档唯一的写入代次门（V3.2.7.3）。

    ``generation`` 只增不减：存档切换、会话轮换或显式失效都会推进它，使所有绑定旧代次的
    Worker 在最终提交时被数据库条件更新拒绝。``current_session_id`` 是唯一获得写入资格的会话。
    """

    __tablename__ = "save_write_gates"
    __table_args__ = (
        UniqueConstraint("fm_save_id", name="uq_save_write_gate_save"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_session_id: Mapped[int | None] = mapped_column(Integer)
    current_identity_id: Mapped[int | None] = mapped_column(Integer)
    last_switch_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_switch_reason: Mapped[str | None] = mapped_column(String(64))


class SaveIdentityConflict(TimestampMixin, Base):
    """一次无法自动裁决的存档身份冲突，保留证据供人工处理。"""

    __tablename__ = "save_identity_conflicts"
    __table_args__ = (Index("ix_save_conflict_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int | None] = mapped_column(Integer, index=True)
    current_identity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conflicting_identity_id: Mapped[int | None] = mapped_column(Integer)
    conflict_reason: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    conflict_evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)


class SaveIdentityAuditEvent(TimestampMixin, Base):
    """存档身份/会话/采集的不可变审计事件（V3.2.7.2 Phase 6）。

    只追加，不覆盖：错误的结论通过新的修正事件表达。``evidence_summary`` 只存规范化摘要，
    不存原始内存或存档内容。
    """

    __tablename__ = "save_identity_audit_events"
    __table_args__ = (
        Index("ix_save_identity_audit_identity", "identity_id", "occurred_at"),
        Index("ix_save_identity_audit_session", "session_id", "occurred_at"),
        Index("ix_save_identity_audit_capture", "capture_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int | None] = mapped_column(Integer, index=True)
    identity_id: Mapped[int | None] = mapped_column(Integer)
    session_id: Mapped[int | None] = mapped_column(Integer)
    capture_id: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str | None] = mapped_column(String(24))
    old_fingerprint: Mapped[str | None] = mapped_column(String(128))
    new_fingerprint: Mapped[str | None] = mapped_column(String(128))
    evidence_summary: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="backend", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


@event.listens_for(SaveIdentityAuditEvent, "before_update")
@event.listens_for(SaveIdentityAuditEvent, "before_delete")
def _reject_save_identity_audit_rewrite(*_args: object) -> None:
    """审计事件不可覆盖：修正必须追加新事件。"""
    raise ValueError("save_identity_audit_events 是不可覆盖的审计表：禁止更新或删除")


# ---------------------------------------------------------------------------
# V3.2.9 全库球员身份治理
#
# 设计原则（与任务书 §1/§3/§5 一致）：
# * UID 只是「存档内关联键」，不是全球永久身份；所有观测都带存档身份作用域。
# * 无法确定的球员保留为候选或冲突，绝不自动合并。
# * 人工审核只产生「人类已确认」这类状态，Verified 仍由 V3.2.8.1 的门控决定，
#   API 不接受客户端直接把状态写成 Verified。
# ---------------------------------------------------------------------------

#: ``player_uid_observations.status`` 的取值。
UID_OBSERVATION_STATUSES = ("Valid", "Missing", "Duplicate", "Conflicted", "Stale", "Unsupported")
#: ``player_identity_links.verification_status`` 的取值。
#: 注意：这里没有 Verified —— Verified 属于 V3.2.8.1 的作用域模型，本层不生产它。
IDENTITY_LINK_STATUSES = (
    "Unverified",
    "Candidate",
    "ConfirmedByHuman",
    "Stale",
    "Conflicted",
    "Rejected",
)
#: 人工审核队列状态。
IDENTITY_REVIEW_STATUSES = (
    "PendingHumanReview",
    "Confirmed",
    "Rejected",
    "KeptIndependent",
    "Deferred",
    "Stale",
)
#: 批处理任务状态。
SCAN_RUN_STATUSES = ("Queued", "Running", "Paused", "Completed", "Failed", "Cancelled")


class PlayerUidObservation(TimestampMixin, Base):
    """一次带作用域的 UID 观测（只追加）。

    ``observation_key`` 是幂等键：同一次扫描重放不会产生第二行。作用域包含存档、存档身份指纹、
    会话、来源、采集时间与实例，任何一项变化都是新的观测，不会覆盖历史。
    ``uid`` 保留原始文本（含前导零），``uid_status`` 是统一分类结果（valid/sentinel/missing/invalid）。
    """

    __tablename__ = "player_uid_observations"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "observation_key", name="uq_uid_observation_save_key"),
        Index("ix_uid_observation_save_uid", "fm_save_id", "uid"),
        Index("ix_uid_observation_save_status", "fm_save_id", "status"),
        Index("ix_uid_observation_instance", "player_instance_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    observation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    save_identity_fingerprint: Mapped[str | None] = mapped_column(String(128))
    session_key: Mapped[str | None] = mapped_column(String(128))
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"))
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), index=True)
    uid: Mapped[str | None] = mapped_column(String(64))
    uid_status: Mapped[str] = mapped_column(String(16), nullable=False)
    uid_reason: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    game_build: Mapped[str | None] = mapped_column(String(64))
    layout_version: Mapped[str | None] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    attribute_record_digest: Mapped[str | None] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 重复/冲突时指向「另一条记录所属的球员」，不合并、只留证据。
    conflicting_player_id: Mapped[int | None] = mapped_column(Integer)


class PlayerIdentityLink(TimestampMixin, Base):
    """Canonical 球员与某个存档内实例之间的关联（只追加 + 显式失效）。

    历史不覆盖：关联失效写 ``valid_to`` 并追加新行，``superseded_by_id`` 指向新行。
    ``verification_status`` 永远不含 Verified；Verified 由 V3.2.8.1 的 C# 门控给出。
    """

    __tablename__ = "player_identity_links"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "link_key", name="uq_identity_link_save_key"),
        Index("ix_identity_link_save_player", "fm_save_id", "canonical_player_id"),
        Index("ix_identity_link_save_uid", "fm_save_id", "save_local_uid"),
        Index("ix_identity_link_save_instance", "fm_save_id", "player_instance_id"),
        Index("ix_identity_link_status", "fm_save_id", "verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    player_instance_id: Mapped[int | None] = mapped_column(ForeignKey("player_instances.id"))
    save_local_uid: Mapped[str | None] = mapped_column(String(64))
    uid_occurrence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(24), default="Candidate", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    link_key: Mapped[str] = mapped_column(String(64), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    superseded_by_id: Mapped[int | None] = mapped_column(Integer)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class PlayerIdentityReviewItem(TimestampMixin, Base):
    """人工审核队列的一条待处理身份问题（同名/UID 重复/跨存档/UID 冲突）。

    ``item_key`` 保证重复扫描幂等；同一问题不会因为多跑一次扫描而出现两行。
    已由人工处理的条目不会被后续扫描覆盖（扫描只在不存在时创建）。
    """

    __tablename__ = "player_identity_review_items"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "item_key", name="uq_identity_review_save_key"),
        Index("ix_identity_review_save_status", "fm_save_id", "status"),
        Index("ix_identity_review_save_type", "fm_save_id", "item_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PendingHumanReview", nullable=False)
    # 乐观锁版本（V3.2.9.2）：每次状态变更 +1；客户端提交决定时必须携带读取到的版本。
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    subject_uid: Mapped[str | None] = mapped_column(String(64))
    primary_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    candidate_player_ids_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    conflict_reason: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class PlayerIdentityReviewAction(Base):
    """审核操作的不可变审计行（追加写，禁止更新/删除）。"""

    __tablename__ = "player_identity_review_actions"
    __table_args__ = (
        Index("ix_identity_review_action_item", "review_id", "created_at"),
        UniqueConstraint("review_id", "request_key", name="uq_identity_review_action_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("player_identity_review_items.id"), nullable=False, index=True
    )
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    # 乐观锁版本快照（V3.2.9.2）：历史必须能追溯"从哪个版本改到哪个版本"。
    previous_version: Mapped[int | None] = mapped_column(Integer)
    new_version: Mapped[int | None] = mapped_column(Integer)
    # 幂等键（V3.2.9.2）：同一 review 上重复提交同一 key 不重复追加历史。
    request_key: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(512))
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


@event.listens_for(PlayerIdentityReviewAction, "before_update")
@event.listens_for(PlayerIdentityReviewAction, "before_delete")
def _reject_identity_review_action_rewrite(*_args: object) -> None:
    raise ValueError("player_identity_review_actions 是不可覆盖的审计表：禁止更新或删除")


class IdentityScanRun(TimestampMixin, Base):
    """一次全库身份扫描的批次状态，用于有界批处理、幂等重放与断点恢复。

    ``payload_checksum`` 是作用域描述（存档 + 存档身份指纹 + 构建 + 布局 + 实例范围）的哈希；
    恢复时重算不一致就拒绝继续，避免在错误存档/错误布局上复用旧进度。
    """

    __tablename__ = "identity_scan_runs"
    __table_args__ = (
        UniqueConstraint("fm_save_id", "scan_id", name="uq_identity_scan_save_scan"),
        Index("ix_identity_scan_save_status", "fm_save_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    scan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="Queued", nullable=False)
    cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    total_instances: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload_checksum: Mapped[str | None] = mapped_column(String(64))
    save_identity_fingerprint: Mapped[str | None] = mapped_column(String(128))
    game_build: Mapped[str | None] = mapped_column(String(64))
    layout_version: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class CrossSaveIdentityCandidate(TimestampMixin, Base):
    """不同存档之间「可能是同一个现实球员」的候选（不自动合并）。

    相同 UID 只是证据之一：``uid_equal`` 记录它，但跨存档 UID 不构成身份。
    """

    __tablename__ = "cross_save_identity_candidates"
    __table_args__ = (
        UniqueConstraint(
            "fm_save_id", "other_save_id", "subject_player_id", "other_player_id",
            name="uq_cross_save_pair",
        ),
        Index("ix_cross_save_save_status", "fm_save_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    other_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    subject_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    other_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="CrossSaveCandidate", nullable=False)
    uid_equal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DataRepairAudit(TimestampMixin, Base):
    """V3.3.0 自动导入引擎的修复与隔离审计（只追加，不覆盖）。

    一行代表「一个实体行上的一条决策」：

    * ``decision='repaired'``：Level 1/2 修复已应用，``before_json`` / ``after_json`` 保留原值与新值；
    * ``decision='quarantined'``：Level 3 隔离，该行没有写入正式数据，``requires_review=True``。

    幂等键是 ``(import_job_id, entity, row_index, rule_id, field)``：同一批次重复执行不会重复写审计。
    原始报文本身仍保存在 ``import_jobs.raw_payload_path``，审计只记录必要的前后值。
    """

    __tablename__ = "data_repair_audits"
    __table_args__ = (
        UniqueConstraint(
            "import_job_id", "entity", "row_index", "rule_id", "field",
            name="uq_data_repair_job_row_rule",
        ),
        Index("ix_data_repair_save_scan", "fm_save_id", "scan_id"),
        Index("ix_data_repair_save_decision", "fm_save_id", "decision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    # 导入任务；隔离行在任务创建前就被拦下时允许为空，但正式写入的修复必然绑定任务。
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"), index=True)
    scan_id: Mapped[str | None] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(16), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), default="1", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field: Mapped[str | None] = mapped_column(String(64))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), default="applied", nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


@event.listens_for(DataRepairAudit, "before_update")
@event.listens_for(DataRepairAudit, "before_delete")
def _reject_data_repair_audit_rewrite(*_args: object) -> None:
    """修复审计不可覆盖：错误决策通过新增修正记录表达。"""
    raise ValueError("data_repair_audits 是不可覆盖的审计表：禁止更新或删除")

