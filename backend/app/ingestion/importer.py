"""Import one scan payload into the database.

Guarantees that the API and tests rely on:

* ``scan_id`` is an idempotency key; a successful import is never applied twice.
* One scan is applied atomically. A crash leaves a ``failed`` job and no partial rows.
* Snapshots are append-only: an existing ``(instance, observed_at)`` row is never overwritten.
* Every rejected row is recorded with a stable code and message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..analytics.fees import compute_effective_fee
from ..clubs import SOURCE_PAYLOAD_CLUBS, SOURCE_PLAYER_FIELD, ClubResolver
from ..config import settings as default_settings
from ..models import (
    Club,
    DataSource,
    FmSave,
    ImportJob,
    ImportRow,
    LoanRecord,
    PlayerAttributeValue,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    PlayerStatistic,
    Transfer,
    TransferCandidate,
    TransferFeeComponent,
)
from ..utils import iso, payload_checksum, utcnow
from .attributes import ATTRIBUTE_KEYS, ensure_attributes, position_group
from .identity import resolve_player_instance
from .unresolved import persist_unresolved_observation
from .protocol import (
    STATISTIC_FIELDS,
    FeeComponentRecord,
    PlayerRecord,
    RowValidationError,
    ScanPayload,
    TransferRecord,
    parse_payload,
    validate_club_row,
    validate_player_row,
    validate_transfer_row,
)

EXPECTED_PLAYER_FIELDS = ("ca", "pa", "market_value", "wage", "contract_end", "position", "club_uid")
EXPECTED_TRANSFER_FIELDS = ("effective_fee", "transfer_date", "player_ca_at_transfer", "contract_remaining_months")


@dataclass
class ImportOutcome:
    """Counts and warnings produced by one import request."""

    job_id: int
    save_id: int
    scan_id: str
    status: str
    duplicate: bool = False
    players_created: int = 0
    players_updated: int = 0
    instances_matched: int = 0
    snapshots_created: int = 0
    snapshots_skipped: int = 0
    transfers_created: int = 0
    transfers_updated: int = 0
    transfers_skipped: int = 0
    statistics_created: int = 0
    statistics_updated: int = 0
    availability_created: int = 0
    loans_created: int = 0
    loans_updated: int = 0
    pending_transfers_created: int = 0
    candidates_created: int = 0
    rows_rejected: int = 0
    #: Legal-UID player rows applied (new snapshots plus already-known observations).
    players_imported: int = 0
    #: Unresolved candidates created by this scan.
    unresolved_created: int = 0
    #: Unresolved observations written by this scan.
    unresolved_observations_created: int = 0
    #: Unresolved observations already stored for this (save, scan, row).
    unresolved_observations_skipped: int = 0
    #: Unresolved rows that correlated to an existing candidate through a stable identity.
    unresolved_candidates_matched: int = 0
    #: Rows deliberately not written because an identical observation already existed.
    rows_skipped: int = 0
    #: Club-change candidates created from snapshot diffs (never completed transfers).
    canonical_candidates_created: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)


class DuplicateScanError(Exception):
    """Raised when a concurrent request already created the job for this (save, scan_id)."""

    def __init__(self, job: ImportJob) -> None:
        super().__init__(f"scan {job.scan_id} 已经在存档 {job.fm_save_id} 中导入")
        self.job = job


class ImportInProgressError(Exception):
    """Raised when the same scan is still being applied by this backend process.

    ``running`` only survives in-process: a crashed job is recovered to ``failed`` at startup, so a
    ``running`` row means a live import. Re-applying it would reset its rows and duplicate the work.
    """

    def __init__(self, job: ImportJob) -> None:
        super().__init__(f"scan {job.scan_id} 正在导入中")
        self.job = job


class ScanImporter:
    """Applies a validated scan payload for one save."""

    def __init__(self, session: Session, raw_dir: Path | None = None) -> None:
        self.session = session
        self._resolver: ClubResolver | None = None
        self.raw_dir = raw_dir or default_settings.raw_import_dir

    # -- public API ---------------------------------------------------------------------------------------------

    def import_bytes(
        self,
        save_id: int,
        raw: bytes,
        *,
        identity_id: int | None = None,
        session_id: int | None = None,
        final_guard: Callable[[], None] | None = None,
    ) -> ImportOutcome:
        """Parse and import a raw payload (JSON or NDJSON)."""
        payload, structural_warnings = parse_payload(raw)
        payload.warnings.extend(structural_warnings)
        return self.import_payload(
            save_id,
            payload,
            raw,
            identity_id=identity_id,
            session_id=session_id,
            final_guard=final_guard,
        )

    def import_payload(
        self,
        save_id: int,
        payload: ScanPayload,
        raw: bytes | None = None,
        *,
        identity_id: int | None = None,
        session_id: int | None = None,
        final_guard: Callable[[], None] | None = None,
    ) -> ImportOutcome:
        """Import an already parsed payload; the caller owns the ``save_id`` existence check.

        ``identity_id`` / ``session_id`` 由路由层校验后传入，作为审计归属写入 ImportJob；
        ``final_guard`` 在提交前最后执行一次身份校验（Phase 8），失败则回滚全部写入。
        """
        existing = self.session.scalar(
            select(ImportJob).where(
                ImportJob.fm_save_id == save_id,
                ImportJob.scan_id == payload.scan.scan_id,
            )
        )
        if existing is not None and existing.status == "running":
            raise ImportInProgressError(existing)
        if existing is not None and existing.status in {"succeeded", "partial"}:
            return self._duplicate_outcome(existing)

        try:
            job = self._begin_job(save_id, payload, existing, raw, identity_id=identity_id, session_id=session_id)
        except DuplicateScanError as duplicate:
            # 并发提交同一个 scan_id：另一个请求已经写入，返回它的结果而不是重复应用。
            return self._duplicate_outcome(duplicate.job)
        try:
            outcome = self._apply(job, payload)
        except Exception as exc:  # keep the failure visible and leave no partial rows behind
            self.session.rollback()
            self._mark_failed(job.id, str(exc))
            raise

        if final_guard is not None:
            try:
                final_guard()
            except Exception as exc:
                # 最终身份校验失败：本事务写入必须整体作废，任务记为失败而不是“已导入”。
                self.session.rollback()
                self._mark_failed(job.id, f"提交前身份校验失败：{exc}")
                raise

        self.session.commit()
        return outcome

    # -- job lifecycle ------------------------------------------------------------------------------------------

    def _begin_job(
        self,
        save_id: int,
        payload: ScanPayload,
        existing: ImportJob | None,
        raw: bytes | None,
        *,
        identity_id: int | None = None,
        session_id: int | None = None,
    ) -> ImportJob:
        if existing is not None:
            self.session.execute(delete(ImportRow).where(ImportRow.import_job_id == existing.id))
            job = existing
            job.status = "running"
            job.finished_at = None
            job.fm_save_id = save_id
            job.save_identity_id = identity_id or job.save_identity_id
            job.save_session_id = session_id or job.save_session_id
            job.warnings_json = "[]"
            job.coverage_json = "{}"
            job.player_count = 0
            job.transfer_count = 0
            job.received_at = utcnow()
        else:
            job = ImportJob(
                fm_save_id=save_id,
                scan_id=payload.scan.scan_id,
                source=payload.source,
                schema_version=payload.schema_version,
                reader_version=payload.reader_version,
                game_build=payload.game.build,
                status="running",
                received_at=utcnow(),
                save_identity_id=identity_id,
                save_session_id=session_id,
            )
            self.session.add(job)
        if raw is not None:
            target = self._raw_target(save_id)
            target.write_bytes(raw)
            job.raw_payload_path = str(target)
            job.checksum = payload_checksum(raw)
        try:
            self.session.commit()
        except IntegrityError as exc:
            # 同一存档并发提交同一个 scan_id：唯一约束兜底，回滚后交出已有的那份导入。
            self.session.rollback()
            existing = self.session.scalar(
                select(ImportJob).where(
                    ImportJob.fm_save_id == save_id,
                    ImportJob.scan_id == payload.scan.scan_id,
                )
            )
            if existing is None:
                raise
            raise DuplicateScanError(existing) from exc
        return job

    @staticmethod
    def _duplicate_outcome(job: ImportJob) -> ImportOutcome:
        """同一存档里重复提交同一个 scan_id 时的返回体；不会再次写入数据。"""
        return ImportOutcome(
            job_id=job.id,
            save_id=job.fm_save_id,
            scan_id=job.scan_id,
            status=job.status,
            duplicate=True,
            players_created=job.player_count,
            snapshots_created=0,
            transfers_created=job.transfer_count,
            warnings=_load_json(job.warnings_json, []),
            coverage=_load_json(job.coverage_json, {}),
        )

    def _raw_target(self, save_id: int) -> Path:
        """Return a backend-generated path inside this save's raw directory.

        The filename never comes from the payload: a malicious or malformed ``scan_id`` must not be able
        to escape the directory, overwrite another save's file, or create a file elsewhere on disk.
        """
        root = (self.raw_dir / str(int(save_id))).resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = (root / f"{uuid4().hex}.json").resolve()
        if target.parent != root:
            raise ValueError(f"拒绝写入 {target}：不在存档 raw 目录 {root} 内")
        return target

    def _mark_failed(self, job_id: int, message: str) -> None:
        job = self.session.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.finished_at = utcnow()
        job.warnings_json = json.dumps([f"导入失败：{message}"], ensure_ascii=False)
        self.session.commit()

    # -- main pass ----------------------------------------------------------------------------------------------

    def _apply(self, job: ImportJob, payload: ScanPayload) -> ImportOutcome:
        outcome = ImportOutcome(
            job_id=job.id,
            save_id=job.fm_save_id,
            scan_id=payload.scan.scan_id,
            status="succeeded",
        )
        outcome.warnings.extend(payload.warnings)
        attribute_ids = ensure_attributes(self.session)
        clubs = self._upsert_clubs(job.fm_save_id, payload, outcome)
        instance_by_record = self._upsert_players(job, payload, clubs, attribute_ids, outcome)
        self._upsert_transfers(job, payload, clubs, instance_by_record, outcome)
        # A club change between two snapshots is only a candidate event; it must be confirmed before it counts.
        self._detect_club_changes(job, payload, instance_by_record, outcome)
        outcome.canonical_candidates_created = outcome.candidates_created
        outcome.rows_skipped = outcome.snapshots_skipped + outcome.unresolved_observations_skipped
        outcome.coverage = self._coverage(payload, outcome)
        outcome.status = (
            "failed"
            if outcome.rows_rejected
            and not (outcome.snapshots_created or outcome.unresolved_observations_created)
            else ("partial" if outcome.rows_rejected else "succeeded")
        )
        self._touch_source(job, payload, outcome)
        job.status = outcome.status
        job.finished_at = utcnow()
        job.player_count = outcome.snapshots_created
        job.transfer_count = outcome.transfers_created
        job.warnings_json = json.dumps(outcome.warnings, ensure_ascii=False)
        job.coverage_json = json.dumps(outcome.coverage, ensure_ascii=False)
        label = f"扫描 {payload.scan.scan_id}"
        self.session.add(
            ImportRow(
                import_job_id=job.id,
                row_index=0,
                entity="scan",
                code="summary",
                message=(
                    f"{label} 导入 {outcome.snapshots_created} 名球员快照、"
                    f"{outcome.unresolved_observations_created} 条无 UID 观察、"
                    f"{outcome.transfers_created} 笔交易"
                ),
            )
        )
        return outcome

    def _upsert_clubs(
        self, save_id: int, payload: ScanPayload, outcome: ImportOutcome
    ) -> dict[str, Club]:
        """Register the clubs declared by the payload, through the shared resolver.

        A club object with a uid is the strongest source (confidence 1.0); a name that only appears in a player row
        is weaker (0.6) and gets a deterministic ``name:<slug>`` uid, so the same name never duplicates.
        """
        resolver = self._resolver_for(save_id)
        cache: dict[str, Club] = {}
        for raw in payload.clubs:
            try:
                record = validate_club_row(raw)
            except RowValidationError as exc:
                outcome.rows_rejected += 1
                outcome.errors.append({"entity": "club", "code": exc.code, "message": exc.message})
                continue
            resolved = resolver.resolve(
                uid=record.uid,
                name=record.name,
                league=record.league,
                reputation=record.reputation,
                nation=record.nation,
                source=SOURCE_PAYLOAD_CLUBS,
                source_uid=record.uid,
            )
            if resolved is None:
                continue
            club = resolved.club
            cache[record.uid] = club
            # A payload that names the managed club is evidence too, but never overrides an explicit choice.
            save = self.session.get(FmSave, save_id)
            if record.is_user_club and save is not None and save.user_club_id is None:
                resolver.set_user_club(club.id, source=SOURCE_PAYLOAD_CLUBS)
        self.session.flush()
        return cache

    def _club_for(
        self, save_id: int, uid: str | None, name: str | None, cache: dict[str, Club], is_user: bool = False
    ) -> Club | None:
        """Resolve a player's club; ``uid`` first, then the name, then nothing (never a guessed club)."""
        if uid and uid in cache:
            return cache[uid]
        if not uid and not name:
            return None
        resolver = self._resolver_for(save_id)
        resolved = resolver.resolve(uid=uid, name=name, source=SOURCE_PLAYER_FIELD, source_uid=uid)
        if resolved is None:
            return None
        if is_user:
            resolved.club.is_user_club = True
        if uid:
            cache[uid] = resolved.club
        elif name:
            cache[name] = resolved.club
        return resolved.club

    def _resolver_for(self, save_id: int) -> ClubResolver:
        """One resolver per import so name/uid lookups stay in memory."""
        if self._resolver is None or self._resolver.save_id != save_id:
            self._resolver = ClubResolver(self.session, save_id)
        return self._resolver

    def _upsert_players(
        self,
        job: ImportJob,
        payload: ScanPayload,
        clubs: dict[str, Club],
        attribute_ids: dict[str, int],
        outcome: ImportOutcome,
    ) -> dict[str, int]:
        instance_by_record: dict[str, int] = {}
        observed_at = payload.scan.observed_at
        for index, raw in enumerate(payload.players, start=1):
            try:
                record = validate_player_row(raw)
            except RowValidationError as exc:
                self._reject(job, index, "player", exc, outcome, raw)
                continue
            if not record.has_valid_uid:
                self._persist_unresolved(job, payload, index, record, raw, clubs, outcome)
                continue
            resolved = resolve_player_instance(self.session, job.fm_save_id, record, outcome.warnings)
            instance = resolved.instance
            if resolved.created_player:
                outcome.players_created += 1
            elif resolved.created_instance:
                outcome.instances_matched += 1
            else:
                outcome.players_updated += 1
            club = self._club_for(job.fm_save_id, record.club_uid, None, clubs)
            if club is not None:
                instance.club_id = club.id
            self._create_snapshot(job, payload, record, instance, club, clubs, attribute_ids, outcome)
            self._upsert_statistics(job, payload, record, instance, outcome)
            outcome.players_imported += 1
            if record.record_id:
                instance_by_record[record.record_id] = instance.id
            instance_by_record[record.save_local_uid] = instance.id
            if observed_at > (instance.last_seen_at or datetime.min):
                instance.last_seen_at = observed_at
        self.session.flush()
        return instance_by_record

    def _persist_unresolved(
        self,
        job: ImportJob,
        payload: ScanPayload,
        index: int,
        record: PlayerRecord,
        raw_row: dict[str, object],
        clubs: dict[str, Club],
        outcome: ImportOutcome,
    ) -> None:
        """Store a row without a usable identity; never resolve it to a player instance.

        The savepoint keeps a failing row from aborting the whole scan while still making the failure
        visible: the row is recorded and the job ends ``partial``, never ``succeeded``.
        """
        club_name = None
        if record.club_uid:
            club = clubs.get(record.club_uid)
            club_name = club.name if club is not None else record.club_uid
        try:
            with self.session.begin_nested():
                persist_unresolved_observation(
                    self.session,
                    job=job,
                    payload=payload,
                    row_index=index,
                    record=record,
                    raw_row=raw_row,
                    outcome=outcome,
                    club_name=club_name,
                )
        except Exception as exc:  # noqa: BLE001 - one row must not abort the scan; the failure is recorded
            reason = RowValidationError("unresolved_persist_failed", f"无 UID 球员持久化失败：{exc}")
            self._reject(job, index, "player", reason, outcome, raw_row)

    def _create_snapshot(
        self,
        job: ImportJob,
        payload: ScanPayload,
        record: PlayerRecord,
        instance: PlayerInstance,
        club: Club | None,
        clubs: dict[str, Club],
        attribute_ids: dict[str, int],
        outcome: ImportOutcome,
    ) -> None:
        observed_at = payload.scan.observed_at
        exists = self.session.scalar(
            select(PlayerSnapshot.id).where(
                PlayerSnapshot.player_instance_id == instance.id,
                PlayerSnapshot.observed_at == observed_at,
            )
        )
        if exists is not None:
            outcome.snapshots_skipped += 1
            return
        known = {key: value for key, value in record.attributes.items() if key in ATTRIBUTE_KEYS}
        unknown = sorted(set(record.attributes) - ATTRIBUTE_KEYS)
        if unknown:
            outcome.warnings.append(f"球员 {record.name} 含未知属性 {', '.join(unknown)}，已忽略")
        completeness = _completeness(record)
        snapshot = PlayerSnapshot(
            player_instance_id=instance.id,
            import_job_id=job.id,
            observed_at=observed_at,
            game_date=payload.scan.game_date,
            imported_at=utcnow(),
            age=_age(record, payload.scan.game_date),
            ca=record.ca,
            pa=record.pa,
            market_value=record.market_value,
            wage=record.wage,
            contract_end=record.contract_end,
            club_id=club.id if club is not None else None,
            position=record.position,
            minutes_played=record.minutes_played,
            appearances=record.appearances,
            goals=record.goals,
            assists=record.assists,
            data_completeness=completeness,
            height_cm=record.height_cm,
            foot=record.foot,
            world_reputation=record.world_reputation,
            source=payload.source,
            reader_version=payload.reader_version,
            game_build=payload.game.build,
        )
        self.session.add(snapshot)
        self.session.flush()
        for key, value in known.items():
            self.session.add(
                PlayerAttributeValue(
                    player_snapshot_id=snapshot.id,
                    attribute_id=attribute_ids[key],
                    value=float(value),
                )
            )
        outcome.snapshots_created += 1
        self._upsert_availability(job, payload, record, instance, clubs, outcome)
        self._upsert_loan(job, payload, record, instance, clubs, outcome)
        self._upsert_agreed_transfer(job, payload, record, instance, clubs, outcome)

    def _upsert_availability(
        self,
        job: ImportJob,
        payload: ScanPayload,
        record: PlayerRecord,
        instance: PlayerInstance,
        clubs: dict[str, Club],
        outcome: ImportOutcome,
    ) -> None:
        """Store the listing / injury / registration observation for this scan.

        Absent fields stay NULL: a source without injury data must not look like "fit".
        """
        availability = record.availability
        ownership = record.ownership
        agreed = record.agreed_transfer
        if availability is None and ownership is None and agreed is None:
            return
        observed_at = payload.scan.observed_at
        exists = self.session.scalar(
            select(PlayerAvailability.id).where(
                PlayerAvailability.player_instance_id == instance.id,
                PlayerAvailability.observed_at == observed_at,
            )
        )
        if exists is not None:
            return
        parent = _club_by_name(clubs, ownership.parent_club_uid if ownership else None)
        loan = _club_by_name(clubs, ownership.loan_club_uid if ownership else None)
        target = _club_by_name(clubs, agreed.to_club_uid if agreed else None)
        row = PlayerAvailability(
            player_instance_id=instance.id,
            import_job_id=job.id,
            observed_at=observed_at,
            game_date=payload.scan.game_date,
            listed=availability.listed if availability else None,
            loan_listed=availability.loan_listed if availability else None,
            not_for_sale=availability.not_for_sale if availability else None,
            set_for_release=availability.set_for_release if availability else None,
            injury_proneness=availability.injury_proneness if availability else None,
            injured=availability.injured if availability else None,
            injury_start_date=availability.injury_start_date if availability else None,
            expected_return_date=availability.expected_return_date if availability else None,
            injury_note=availability.injury_note if availability else None,
            parent_club_id=parent.id if parent else None,
            loan_club_id=loan.id if loan else None,
            team_type=ownership.team_type if ownership and ownership.team_type != "unknown" else None,
            agreed_to_club_id=target.id if target else None,
            agreed_transfer_date=agreed.transfer_date if agreed else None,
            source=payload.source,
            reader_version=payload.reader_version,
            game_build=payload.game.build,
        )
        self.session.add(row)
        outcome.availability_created += 1

    def _upsert_loan(
        self,
        job: ImportJob,
        payload: ScanPayload,
        record: PlayerRecord,
        instance: PlayerInstance,
        clubs: dict[str, Club],
        outcome: ImportOutcome,
    ) -> None:
        """Persist a loan relationship when the source states both clubs; otherwise record nothing."""
        ownership = record.ownership
        if ownership is None or not ownership.parent_club_uid or not ownership.loan_club_uid:
            return
        if ownership.parent_club_uid == ownership.loan_club_uid:
            return
        record_id = f"{instance.save_local_uid}:{ownership.parent_club_uid}:{ownership.loan_club_uid}"
        existing = self.session.scalar(
            select(LoanRecord).where(
                LoanRecord.fm_save_id == job.fm_save_id,
                LoanRecord.source_record_id == record_id,
            )
        )
        parent = _club_by_name(clubs, ownership.parent_club_uid)
        loan = _club_by_name(clubs, ownership.loan_club_uid)
        values = {
            "player_instance_id": instance.id,
            "parent_club_id": parent.id if parent else None,
            "loan_club_id": loan.id if loan else None,
            "parent_club_name": parent.name if parent else ownership.parent_club_uid,
            "loan_club_name": loan.name if loan else ownership.loan_club_uid,
            "start_date": ownership.loan_start_date,
            "end_date": ownership.loan_end_date,
            "has_option": ownership.has_option,
            "has_obligation": ownership.has_obligation,
            "status": "active" if ownership.loan_end_date is None else "unknown",
            "observed_at": payload.scan.observed_at,
            "source": payload.source,
            "reader_version": payload.reader_version,
            "game_build": payload.game.build,
            "import_job_id": job.id,
        }
        if existing is None:
            self.session.add(
                LoanRecord(fm_save_id=job.fm_save_id, source_record_id=record_id, **values)
            )
            outcome.loans_created += 1
            return
        # Re-observations refresh dates and clauses; a clause once reported is not silently erased.
        for key in ("start_date", "end_date", "has_option", "has_obligation", "parent_club_id", "loan_club_id"):
            value = values[key]
            if value is not None:
                setattr(existing, key, value)
        existing.observed_at = payload.scan.observed_at
        existing.import_job_id = job.id
        outcome.loans_updated += 1

    def _upsert_agreed_transfer(
        self,
        job: ImportJob,
        payload: ScanPayload,
        record: PlayerRecord,
        instance: PlayerInstance,
        clubs: dict[str, Club],
        outcome: ImportOutcome,
    ) -> None:
        """An agreed-but-not-yet-registered deal becomes a ``status='agreed'`` transfer, never spending."""
        agreed = record.agreed_transfer
        if agreed is None or not agreed.to_club_uid:
            return
        record_id = f"agreed:{instance.save_local_uid}:{agreed.to_club_uid}"
        existing = self.session.scalar(
            select(Transfer.id).where(
                Transfer.fm_save_id == job.fm_save_id,
                Transfer.source_record_id == record_id,
            )
        )
        if existing is not None:
            return
        target = _club_by_name(clubs, agreed.to_club_uid)
        current = self.session.get(Club, instance.club_id) if instance.club_id else None
        transfer_date = agreed.transfer_date or payload.scan.game_date or payload.scan.observed_at.date()
        self.session.add(
            Transfer(
                fm_save_id=job.fm_save_id,
                import_job_id=job.id,
                source_record_id=record_id,
                player_instance_id=instance.id,
                player_name=record.name,
                from_club_id=current.id if current else None,
                to_club_id=target.id if target else None,
                from_club_name=current.name if current else None,
                to_club_name=target.name if target else agreed.to_club_uid,
                transfer_type="permanent",
                status="agreed",
                transfer_date=transfer_date,
                season=_season_label(transfer_date),
                currency="EUR",
                source=payload.source,
                confidence=0.8,
            )
        )
        outcome.pending_transfers_created += 1

    def _detect_club_changes(
        self,
        job: ImportJob,
        payload: ScanPayload,
        instance_by_record: dict[str, int],
        outcome: ImportOutcome,
    ) -> None:
        """Diff each player's last two snapshots and record club changes as unconfirmed candidates."""
        instance_ids = list(instance_by_record.values())
        if not instance_ids:
            return
        # SQLite 的绑定参数上限是 32766，全量扫描（4.8 万球员）必须分批查询。
        rows = []
        for start in range(0, len(instance_ids), 500):
            chunk = instance_ids[start : start + 500]
            rows.extend(
                self.session.execute(
                    select(
                        PlayerSnapshot.player_instance_id,
                        PlayerSnapshot.club_id,
                        PlayerSnapshot.observed_at,
                    )
                    .where(PlayerSnapshot.player_instance_id.in_(chunk))
                    .order_by(PlayerSnapshot.player_instance_id, PlayerSnapshot.observed_at)
                ).all()
            )
        history: dict[int, list[tuple[int | None, object]]] = {}
        for instance_id, club_id, observed_at in rows:
            history.setdefault(instance_id, []).append((club_id, observed_at))
        detected = payload.scan.observed_at
        for instance_id, points in history.items():
            if len(points) < 2:
                continue
            (previous_club, previous_at), (current_club, current_at) = points[-2], points[-1]
            if current_at != detected or previous_club is None or current_club == previous_club:
                continue  # first observation, or no change, or an older scan
            exists = self.session.scalar(
                select(TransferCandidate.id).where(
                    TransferCandidate.fm_save_id == job.fm_save_id,
                    TransferCandidate.player_instance_id == instance_id,
                    TransferCandidate.to_club_id == current_club,
                    TransferCandidate.detected_at == detected,
                )
            )
            if exists is not None:
                continue
            self.session.add(
                TransferCandidate(
                    fm_save_id=job.fm_save_id,
                    player_instance_id=instance_id,
                    from_club_id=previous_club,
                    to_club_id=current_club,
                    kind=self._change_kind(instance_id, current_club),
                    previous_observed_at=previous_at,  # type: ignore[arg-type]
                    detected_at=detected,
                    status="candidate",
                    evidence_json=json.dumps(
                        {
                            "previous_club_id": previous_club,
                            "current_club_id": current_club,
                            "previous_observed_at": iso(previous_at),  # type: ignore[arg-type]
                            "source": payload.source,
                            "rule": "快照对比只能作为候选事件，必须确认后才计入统计",
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            outcome.candidates_created += 1

    def _change_kind(self, instance_id: int, to_club_id: int) -> str:
        """``loan`` only when a stored loan record names the destination club; otherwise ``unknown``."""
        loan = self.session.scalar(
            select(LoanRecord).where(
                LoanRecord.player_instance_id == instance_id,
                LoanRecord.loan_club_id == to_club_id,
            )
        )
        return "loan" if loan is not None else "unknown"

    def _upsert_statistics(
        self,
        job: ImportJob,
        payload: ScanPayload,
        record: PlayerRecord,
        instance: PlayerInstance,
        outcome: ImportOutcome,
    ) -> None:
        """Store optional season aggregates; a newer observation replaces older counts for the same period."""
        if not record.statistics:
            return
        observed_at = payload.scan.observed_at
        for statistics in record.statistics:
            values = {name: getattr(statistics, name) for name in STATISTIC_FIELDS}
            if all(value is None for value in values.values()):
                outcome.warnings.append(
                    f"球员 {record.name} 的 {statistics.period} 统计块没有任何可用字段，已忽略"
                )
                continue
            existing = self.session.scalar(
                select(PlayerStatistic).where(
                    PlayerStatistic.player_instance_id == instance.id,
                    PlayerStatistic.scope == "season",
                    PlayerStatistic.period == statistics.period,
                )
            )
            if existing is not None:
                if existing.observed_at >= observed_at:
                    continue
                for name, value in values.items():
                    setattr(existing, name, value)
                existing.competition = statistics.competition or existing.competition
                existing.observed_at = observed_at
                existing.import_job_id = job.id
                outcome.statistics_updated += 1
                continue
            row = PlayerStatistic(
                player_instance_id=instance.id,
                import_job_id=job.id,
                scope="season",
                period=statistics.period,
                competition=statistics.competition,
                observed_at=observed_at,
                source=payload.source,
                reader_version=payload.reader_version,
            )
            for name, value in values.items():
                setattr(row, name, value)
            self.session.add(row)
            outcome.statistics_created += 1

    def _upsert_transfers(
        self,
        job: ImportJob,
        payload: ScanPayload,
        clubs: dict[str, Club],
        instance_by_record: dict[str, int],
        outcome: ImportOutcome,
    ) -> None:
        for index, raw in enumerate(payload.transfers, start=1):
            try:
                record = validate_transfer_row(raw)
            except RowValidationError as exc:
                self._reject(job, index, "transfer", exc, outcome, raw)
                continue
            existing = self.session.scalar(
                select(Transfer).where(
                    Transfer.fm_save_id == job.fm_save_id,
                    Transfer.source_record_id == record.record_id,
                )
            )
            effective_fee = _effective_fee(record)
            if existing is not None:
                if existing.status in {"pending", "future", "unknown"} and record.status != existing.status:
                    existing.status = record.status
                    existing.effective_fee = effective_fee
                    existing.fee_paid = record.fee_paid
                    outcome.transfers_updated += 1
                else:
                    outcome.transfers_skipped += 1
                continue
            from_club = self._club_for(job.fm_save_id, record.from_club_uid, record.from_club_name, clubs)
            to_club = self._club_for(job.fm_save_id, record.to_club_uid, record.to_club_name, clubs)
            instance_id = None
            if record.player_record_id:
                instance_id = instance_by_record.get(record.player_record_id)
                if instance_id is None:
                    instance = self.session.scalar(
                        select(PlayerInstance).where(
                            PlayerInstance.fm_save_id == job.fm_save_id,
                            PlayerInstance.save_local_uid == record.player_record_id,
                        )
                    )
                    instance_id = instance.id if instance is not None else None
            transfer = Transfer(
                fm_save_id=job.fm_save_id,
                import_job_id=job.id,
                source_record_id=record.record_id,
                player_instance_id=instance_id,
                player_name=record.player_name,
                from_club_id=from_club.id if from_club is not None else None,
                to_club_id=to_club.id if to_club is not None else None,
                from_club_name=record.from_club_name or (from_club.name if from_club else None),
                to_club_name=record.to_club_name or (to_club.name if to_club else None),
                transfer_type=record.transfer_type,
                status=record.status,
                transfer_date=record.transfer_date,
                season=record.season,
                currency=record.currency or "EUR",
                base_fee=record.base_fee,
                fee_paid=record.fee_paid,
                addons_potential=record.addons_potential,
                effective_fee=effective_fee,
                player_age_at_transfer=record.player_age_at_transfer,
                player_ca_at_transfer=record.player_ca_at_transfer,
                player_pa_at_transfer=record.player_pa_at_transfer,
                contract_remaining_months=record.contract_remaining_months,
                source=payload.source,
                confidence=record.confidence,
            )
            self.session.add(transfer)
            self.session.flush()
            for component in record.fee_components:
                self.session.add(
                    TransferFeeComponent(
                        transfer_id=transfer.id,
                        component_type=component.type,
                        amount=component.amount,
                        status=component.status,
                        due_date=component.due_date,
                        condition=component.condition,
                    )
                )
            outcome.transfers_created += 1
        self.session.flush()

    def _reject(
        self,
        job: ImportJob,
        index: int,
        entity: str,
        exc: RowValidationError,
        outcome: ImportOutcome,
        raw: dict[str, object],
    ) -> None:
        outcome.rows_rejected += 1
        outcome.errors.append({"entity": entity, "code": exc.code, "message": exc.message})
        outcome.warnings.append(f"{entity} 第 {index} 行被拒绝：{exc.message}")
        self.session.add(
            ImportRow(
                import_job_id=job.id,
                row_index=index,
                entity=entity,
                code=exc.code,
                message=exc.message,
                payload_json=json.dumps(raw, ensure_ascii=False, default=str)[:4000],
            )
        )

    def _coverage(self, payload: ScanPayload, outcome: ImportOutcome) -> dict[str, float]:
        players = payload.players
        transfers = payload.transfers
        attribution = {
            "players": len(players),
            "transfers": len(transfers),
            "player_fields": _field_ratio(
                players,
                ("ca", "pa", "market_value", "wage", "contract_end", "position"),
            ),
            "transfer_fields": _field_ratio(
                transfers,
                ("base_fee", "fee_paid", "player_ca_at_transfer", "contract_remaining_months"),
            ),
            "statistics": round(
                sum(1 for row in players if isinstance(row.get("statistics"), dict)) / len(players), 4
            )
            if players
            else 0.0,
        }
        return {key: round(value, 4) for key, value in attribution.items()}

    def _touch_source(self, job: ImportJob, payload: ScanPayload, outcome: ImportOutcome) -> None:
        source = self.session.scalar(
            select(DataSource).where(
                DataSource.fm_save_id == job.fm_save_id,
                DataSource.source == payload.source,
            )
        )
        if source is None:
            source = DataSource(fm_save_id=job.fm_save_id, source=payload.source)
            self.session.add(source)
        source.reader_version = payload.reader_version or source.reader_version
        source.game_build = payload.game.build or source.game_build
        source.record_count = (source.record_count or 0) + len(payload.players)
        source.first_seen_at = source.first_seen_at or utcnow()
        source.last_seen_at = utcnow()


def _load_json(text: str, fallback: object) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def _season_label(moment: date) -> str:
    """Season label such as ``2026/27`` from the date a move takes effect."""
    start = moment.year if moment.month >= 7 else moment.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def _club_by_name(clubs: dict[str, Club], uid: str | None) -> Club | None:
    """Resolve a club uid from the payload cache; unknown uids stay unresolved rather than guessed."""
    if not uid:
        return None
    return clubs.get(uid)


def _effective_fee(record: TransferRecord | FeeComponentRecord) -> float | None:
    components = getattr(record, "fee_components", [])
    return compute_effective_fee(
        record.base_fee if hasattr(record, "base_fee") else None,
        record.fee_paid if hasattr(record, "fee_paid") else None,
        record.addons_potential if hasattr(record, "addons_potential") else None,
        components,  # type: ignore[arg-type]
    )


def _field_ratio(rows: list[dict[str, object]], fields: tuple[str, ...]) -> float:
    if not rows:
        return 0.0
    present = 0
    total = 0
    for row in rows:
        for name in fields:
            value = row.get(name)
            total += 1
            if value is not None and value != "":
                present += 1
    return present / total if total else 0.0


def _completeness(record: PlayerRecord) -> float:
    present = sum(1 for name in EXPECTED_PLAYER_FIELDS if getattr(record, name, None) is not None)
    return round(present / len(EXPECTED_PLAYER_FIELDS), 4)


def _age(record: PlayerRecord, game_date: object) -> int | None:
    """Reported age wins over a derived one: a source that knows the age is not second-guessed from a birth year."""
    if record.age is not None:
        return record.age
    if record.birth_date is None:
        return None
    reference = game_date if hasattr(game_date, "year") else utcnow().date()
    years = reference.year - record.birth_date.year
    if (reference.month, reference.day) < (record.birth_date.month, record.birth_date.day):
        years -= 1
    return max(years, 0)


def describe_payload(payload: ScanPayload) -> str:
    """Short human-readable description used in logs and job summaries."""
    return f"{payload.source} scan {payload.scan.scan_id} at {iso(payload.scan.observed_at)} ({len(payload.players)} players)"


def recover_interrupted_imports(session_factory: Callable[[], Session]) -> int:
    """Fail jobs a previous process left in ``running`` so they can be retried.

    ``_begin_job`` commits the job before applying rows, so a crash keeps a visible but stuck job.
    Marking it failed with an ``interrupted`` import row makes the next upload of the same ``scan_id``
    retry instead of looking like an import that is still in progress.
    """
    session = session_factory()
    try:
        jobs = list(session.scalars(select(ImportJob).where(ImportJob.status == "running")))
        if not jobs:
            return 0
        now = utcnow()
        for job in jobs:
            job.status = "failed"
            job.finished_at = now
            session.add(
                ImportRow(
                    import_job_id=job.id,
                    row_index=0,
                    entity="scan",
                    code="interrupted",
                    message="后端在导入完成前退出：任务已标记失败，重新上传同一 scan_id 即可重试",
                )
            )
        session.commit()
        return len(jobs)
    finally:
        session.close()

