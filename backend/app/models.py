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
    __table_args__ = (UniqueConstraint("fm_save_id", "scan_id", name="uq_import_jobs_save_scan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fm_save_id: Mapped[int] = mapped_column(ForeignKey("fm_saves.id"), nullable=False, index=True)
    scan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    reader_version: Mapped[str | None] = mapped_column(String(32))
    game_build: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    player_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    raw_payload_path: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(64))

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

    components: Mapped[list[TransferFeeComponent]] = relationship(
        back_populates="transfer", cascade="all, delete-orphan"
    )


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
