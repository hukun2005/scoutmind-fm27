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

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..analytics.fees import compute_effective_fee
from ..clubs import SOURCE_PAYLOAD_CLUBS, SOURCE_PLAYER_FIELD, ClubResolver
from ..config import settings as default_settings
from ..models import (
    Club,
    DataRepairAudit,
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
    TransferStatusHistory,
)
from ..utils import iso, payload_checksum, utcnow
from ..services.save_identity import record_audit
from ..services.write_safety import WriteFence, WriteRejected
from . import cancellation
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


class ImportCancelled(Exception):
    """任务在提交前被取消；所有业务写入已回滚，任务进入 ``cancelled``。"""

    def __init__(self, job: ImportJob) -> None:
        super().__init__(f"导入任务 {job.id} 已取消")
        self.job = job


class OperationConflict(Exception):
    """同一幂等键承载了不同内容：绝不写入，返回冲突。

    ``code`` 为 ``operation_conflict``（operation_id 相同、payload 不同）或
    ``scan_payload_mismatch``（scan_id 相同、payload 不同）。
    """

    def __init__(self, job: ImportJob, code: str, message: str) -> None:
        super().__init__(message)
        self.job = job
        self.code = code
        self.message = message


class OperationRejected(Exception):
    """该 operation_id 的写入曾被 fence 拒绝；重放必须重新识别并生成新 operation_id。"""

    def __init__(self, job: ImportJob) -> None:
        super().__init__("该操作曾被写入安全策略拒绝，不能自动重放")
        self.job = job


#: 已成功落盘的任务状态；重放时返回原结果而不是再次写入。
_COMPLETED_STATUSES = {"succeeded", "partial"}
#: 每处理多少行检查一次取消信号；过小会拖慢大存档导入，过大则取消响应变慢。
_CANCEL_CHECKPOINT_ROWS = 200


class ScanImporter:
    """Applies a validated scan payload for one save."""

    def __init__(self, session: Session, raw_dir: Path | None = None) -> None:
        self.session = session
        self._resolver: ClubResolver | None = None
        self.raw_dir = raw_dir or default_settings.raw_import_dir
        #: V3.3.0 修复审计行，在 ``_apply`` 内与业务写入同一个事务提交。
        self._pending_repair_audits: list[dict[str, object]] | None = None

    # -- public API ---------------------------------------------------------------------------------------------

    def import_bytes(
        self,
        save_id: int,
        raw: bytes,
        *,
        identity_id: int | None = None,
        session_id: int | None = None,
        final_guard: Callable[[], None] | None = None,
        fence: WriteFence | None = None,
        operation_id: str | None = None,
        repair_audits: list[dict[str, object]] | None = None,
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
            fence=fence,
            operation_id=operation_id,
            repair_audits=repair_audits,
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
        fence: WriteFence | None = None,
        operation_id: str | None = None,
        repair_audits: list[dict[str, object]] | None = None,
    ) -> ImportOutcome:
        """Import an already parsed payload; the caller owns the ``save_id`` existence check.

        ``identity_id`` / ``session_id`` 由路由层校验后传入，作为审计归属写入 ImportJob；
        ``fence`` 在**同一事务内**做代次校验（V3.2.7.3），失败则回滚全部写入并标记 rejected；
        ``final_guard`` 保留为旧版独立事务校验（无 fence 时的兼容路径）。
        ``repair_audits`` 是 V3.3.0 自动修复审计行：与业务写入同属一个事务，失败一起回滚。
        """
        existing = self.session.scalar(
            select(ImportJob).where(
                ImportJob.fm_save_id == save_id,
                ImportJob.scan_id == payload.scan.scan_id,
            )
        )
        if existing is not None and existing.status in {"queued", "running", "cancel_requested"}:
            # queued 也可能是另一个请求刚创建、尚未认领的任务；此时重放会与它争抢同一行。
            raise ImportInProgressError(existing)
        if existing is not None and existing.status in _COMPLETED_STATUSES:
            # scan_id 与 operation_id 同时命中时，以更强的 operation 语义报冲突。
            matched_by = "operation" if operation_id and existing.operation_id == operation_id else "scan"
            return self._replay(existing, raw, operation_id, matched_by=matched_by)
        if operation_id:
            # 同一操作 ID 已成功/被拒绝：返回既有结果或明确拒绝，绝不再写一次。
            previous = self.session.scalar(
                select(ImportJob).where(
                    ImportJob.fm_save_id == save_id,
                    ImportJob.operation_id == operation_id,
                    ImportJob.status.in_(("succeeded", "partial", "rejected")),
                )
            )
            if previous is not None:
                return self._replay(previous, raw, operation_id, matched_by="operation")

        # 每次导入重新读取每个实例的最新快照观测时间，避免复用上一次导入的缓存。
        self._latest_observed = {}
        try:
            job = self._begin_job(
                save_id,
                payload,
                existing,
                raw,
                identity_id=identity_id,
                session_id=session_id,
                operation_id=operation_id,
                save_generation=fence.generation if fence is not None else None,
            )
        except DuplicateScanError as duplicate:
            # 并发提交同一个 scan_id：另一个请求已经写入，返回它的结果而不是重复应用。
            return self._replay(duplicate.job, raw, operation_id, matched_by="scan")
        # 认领排队任务：queued → running 的条件更新保证同一任务只有一个 Worker 真正执行。
        job = self._claim_job(job)
        try:
            # 审计行通过实例属性传递，保持 ``_apply(job, payload)`` 的既有签名（测试与子类会替换它）。
            self._pending_repair_audits = repair_audits
            outcome = self._apply(job, payload)
        except ImportCancelled:
            self.session.rollback()
            self._mark_cancelled(job.id, "cancel_requested")
            raise
        except Exception as exc:  # keep the failure visible and leave no partial rows behind
            self.session.rollback()
            self._mark_failed(job.id, str(exc))
            raise
        finally:
            self._pending_repair_audits = None

        if cancellation.is_requested(job.id):
            # 提交前最后一次取消检查：与 commit 之间只剩 fence 校验；取消在此之后到达则
            # 提交已经生效，取消 API 会返回 409，而不是伪造“已取消”。
            self.session.rollback()
            self._mark_cancelled(job.id, "cancel_requested")
            raise ImportCancelled(job)

        if fence is not None:
            try:
                # 与 _apply 的写入同属一个事务：提交前代次变化则整体作废。
                fence.assert_current(self.session)
            except WriteRejected as rejection:
                self.session.rollback()
                self._mark_rejected(job.id, rejection.code, rejection.message)
                raise

        if final_guard is not None:
            try:
                final_guard()
            except Exception as exc:
                # 最终身份校验失败：本事务写入必须整体作废，任务记为失败而不是“已导入”。
                self.session.rollback()
                self._mark_failed(job.id, f"提交前身份校验失败：{exc}")
                raise

        # 跨进程取消保护：终态必须绑定 ``status='running'`` 守卫再写入。
        # 另一个后端进程可能已把任务改为 cancel_requested，此时 rowcount=0 表示取消获胜，
        # 业务写入整体回滚，不能把取消覆盖成 succeeded。
        guarded = self.session.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.status == "running")
            .values(status=outcome.status)
            .execution_options(synchronize_session=False)
        )
        if guarded.rowcount != 1:
            self.session.rollback()
            self._mark_cancelled(job.id, "cancel_requested_cross_process")
            raise ImportCancelled(job)
        job.status = outcome.status

        # 成功写入与审计同一事务提交：要么数据+“已接受”一起可见，要么都不可见。
        self._audit(
            job,
            "write_accepted",
            {
                "job_id": job.id,
                "scan_id": job.scan_id,
                "operation_id": job.operation_id,
                "player_count": job.player_count,
                "transfer_count": job.transfer_count,
                "attempt_count": job.attempt_count,
            },
        )
        self.session.commit()
        cancellation.clear(job.id)
        return outcome

    # -- 幂等重放 ------------------------------------------------------------------------------------------------

    def _replay(
        self,
        job: ImportJob,
        raw: bytes | None,
        operation_id: str | None,
        *,
        matched_by: str,
    ) -> ImportOutcome:
        """处理幂等重放：内容一致才返回原结果，内容不一致必须冲突，被拒绝的任务必须显式失败。"""
        if job.status in {"queued", "running", "cancel_requested"}:
            raise ImportInProgressError(job)
        if job.status == "rejected":
            self._record_replay(job, event_type="operation_replay_rejected", raw=raw)
            raise OperationRejected(job)
        incoming = payload_checksum(raw) if raw is not None else None
        if incoming and job.checksum and incoming != job.checksum:
            code = "operation_conflict" if matched_by == "operation" else "scan_payload_mismatch"
            message = (
                "同一 operation_id 提交了不同内容，已拒绝；请为新内容生成新的 operation_id"
                if operation_id
                else "同一 scan_id 提交了不同内容，已拒绝；请为新内容生成新的 scan_id"
            )
            self._record_replay(job, event_type="operation_conflict", raw=raw, conflict_code=code)
            raise OperationConflict(job, code, message)
        self._record_replay(job, event_type="operation_replayed", raw=raw)
        return self._duplicate_outcome(job)

    def _record_replay(
        self,
        job: ImportJob,
        *,
        event_type: str,
        raw: bytes | None,
        conflict_code: str | None = None,
    ) -> None:
        """重放/冲突也要留下审计与尝试次数；不写任何业务数据。"""
        self.session.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id)
            .values(attempt_count=ImportJob.attempt_count + 1)
            .execution_options(synchronize_session=False)
        )
        record_audit(
            self.session,
            save_id=job.fm_save_id,
            identity_id=job.save_identity_id,
            session_id=job.save_session_id,
            event_type=event_type,
            new_status=job.status,
            evidence_summary={
                "job_id": job.id,
                "scan_id": job.scan_id,
                "operation_id": job.operation_id,
                "generation": job.save_generation,
                "checksum": job.checksum,
                "incoming_checksum": payload_checksum(raw) if raw is not None else None,
                "conflict_code": conflict_code,
            },
            actor="backend",
        )
        self.session.commit()

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
        operation_id: str | None = None,
        save_generation: int | None = None,
    ) -> ImportJob:
        if existing is not None:
            self.session.execute(delete(ImportRow).where(ImportRow.import_job_id == existing.id))
            job = existing
            job.status = "queued"
            job.finished_at = None
            job.cancel_requested_at = None
            job.cancelled_at = None
            job.fm_save_id = save_id
            job.save_identity_id = identity_id or job.save_identity_id
            job.save_session_id = session_id or job.save_session_id
            job.operation_id = operation_id or job.operation_id
            job.save_generation = save_generation if save_generation is not None else job.save_generation
            job.rejected_reason = None
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
                status="queued",
                received_at=utcnow(),
                save_identity_id=identity_id,
                save_session_id=session_id,
                operation_id=operation_id,
                save_generation=save_generation,
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
            # 并发提交同一 scan_id 或同一 operation_id：唯一约束兜底，回滚后交出已有的那份导入。
            self.session.rollback()
            existing = self.session.scalar(
                select(ImportJob).where(
                    ImportJob.fm_save_id == save_id,
                    ImportJob.scan_id == payload.scan.scan_id,
                )
            )
            if existing is None and operation_id:
                existing = self.session.scalar(
                    select(ImportJob).where(
                        ImportJob.fm_save_id == save_id,
                        ImportJob.operation_id == operation_id,
                    )
                )
            if existing is None:
                raise
            if existing.status == "running":
                raise ImportInProgressError(existing) from exc
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

    # -- worker lifecycle ---------------------------------------------------------------------------------------

    def _claim_job(self, job: ImportJob) -> ImportJob:
        """用条件更新认领排队任务；同一任务只会有一个 Worker 从 queued 进入 running。

        另一个请求在同一时刻认领失败时：
        * 已被取消 → 落 cancelled 并抛 :class:`ImportCancelled`；
        * 已被其他 Worker 认领 → 抛 :class:`ImportInProgressError`。
        """
        result = self.session.execute(
            update(ImportJob)
            .where(ImportJob.id == job.id, ImportJob.status == "queued")
            .values(
                status="running",
                attempt_count=ImportJob.attempt_count + 1,
                received_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        self.session.commit()
        self.session.expire_all()
        claimed = self.session.get(ImportJob, job.id)
        if claimed is None:
            raise ImportInProgressError(job)
        if result.rowcount == 1:
            self._audit(claimed, "worker_started", {"job_id": claimed.id, "status": "running"})
            self.session.commit()
            return claimed
        if claimed.status in {"cancel_requested", "cancelled"}:
            self._mark_cancelled(claimed.id, "cancel_requested_before_start")
            raise ImportCancelled(claimed)
        raise ImportInProgressError(claimed)

    def _mark_cancelled(self, job_id: int, reason: str) -> None:
        """取消落库：状态、时间与审计一次提交；业务写入由调用方先行回滚。"""
        job = self.session.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "cancelled"
        job.cancelled_at = utcnow()
        job.finished_at = utcnow()
        job.warnings_json = json.dumps([f"导入被取消：{reason}"], ensure_ascii=False)
        record_audit(
            self.session,
            save_id=job.fm_save_id,
            identity_id=job.save_identity_id,
            session_id=job.save_session_id,
            event_type="worker_cancelled",
            new_status="cancelled",
            evidence_summary={
                "job_id": job.id,
                "scan_id": job.scan_id,
                "operation_id": job.operation_id,
                "generation": job.save_generation,
                "reason": reason,
            },
            reason=reason,
            actor="backend",
        )
        self.session.commit()
        cancellation.clear(job_id)

    def _audit(self, job: ImportJob, event_type: str, summary: dict[str, object]) -> None:
        record_audit(
            self.session,
            save_id=job.fm_save_id,
            identity_id=job.save_identity_id,
            session_id=job.save_session_id,
            event_type=event_type,
            new_status=job.status,
            evidence_summary=summary,
            actor="backend",
        )

    def _check_cancel(self, job: ImportJob, processed: int) -> None:
        """每 N 行检查一次取消信号；只在安全检查点响应，保证不会留下半行数据。

        先查进程内事件（同进程取消立即生效），再查数据库状态（覆盖跨进程取消：
        另一个后端进程只能把任务改成 ``cancel_requested``，无法置位本进程的事件）。
        """
        if processed % _CANCEL_CHECKPOINT_ROWS != 0:
            return
        if cancellation.is_requested(job.id) or self._cancel_requested_in_db(job.id):
            raise ImportCancelled(job)

    def _cancel_requested_in_db(self, job_id: int) -> bool:
        """读取**已提交**的任务状态，用于跨进程取消。

        使用独立连接而不是当前会话：导入事务尚未提交，当前会话看不到其他进程在事务开始后
        写入的 ``cancel_requested``。SQLite 单写者模型下读取可能短暂返回 busy，此时按“未取消”
        处理，由提交前的 ``status='running'`` 守卫兜底。
        """
        try:
            with self.session.get_bind().connect() as conn:
                status = conn.execute(
                    select(ImportJob.status).where(ImportJob.id == job_id)
                ).scalar_one_or_none()
        except OperationalError:
            return False
        return status in {"cancel_requested", "cancelled"}

    def _mark_failed(self, job_id: int, message: str) -> None:
        job = self.session.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "failed"
        job.finished_at = utcnow()
        job.warnings_json = json.dumps([f"导入失败：{message}"], ensure_ascii=False)
        self.session.commit()
        cancellation.clear(job_id)

    def _mark_rejected(self, job_id: int, code: str, message: str) -> None:
        """写入被 fence 拒绝：任务进入 rejected，不保留任何业务数据。

        rejected 任务不能被自动重试继续使用旧上下文；客户端必须重新识别存档并生成新的
        operation_id。
        """
        job = self.session.get(ImportJob, job_id)
        if job is None:
            return
        job.status = "rejected"
        job.rejected_reason = code
        job.finished_at = utcnow()
        job.warnings_json = json.dumps([f"写入被拒绝（{code}）：{message}"], ensure_ascii=False)
        self.session.commit()
        cancellation.clear(job_id)

    # -- main pass ----------------------------------------------------------------------------------------------

    def _apply(self, job: ImportJob, payload: ScanPayload) -> ImportOutcome:
        outcome = ImportOutcome(
            job_id=job.id,
            save_id=job.fm_save_id,
            scan_id=payload.scan.scan_id,
            status="succeeded",
        )
        repair_audits = getattr(self, "_pending_repair_audits", None)
        if repair_audits:
            # 与业务写入同一事务：任何后续失败都会把审计一起回滚，不存在“业务成功但审计丢失”。
            for spec in repair_audits:
                self.session.add(
                    DataRepairAudit(
                        fm_save_id=job.fm_save_id,
                        import_job_id=job.id,
                        scan_id=job.scan_id,
                        **spec,
                    )
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
            self._check_cancel(job, index)
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
            # 旧库/直接写入的快照可能还没有引用：重复导入时补上，但不覆盖已有引用。
            if instance.latest_snapshot_id is None:
                instance.latest_snapshot_id = exists
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
        # 只有不早于现有最新快照的观测时间时才更新引用；历史回补不会覆盖新数据。
        # last_seen_at 是导入时间戳，不能用来比较快照新旧，因此这里读一次真实的最新观测时间并缓存。
        cache = getattr(self, "_latest_observed", None)
        if cache is None:
            cache = {}
            self._latest_observed = cache
        current_observed = cache.get(instance.id, "unset")
        if current_observed == "unset":
            current_observed = (
                self.session.scalar(
                    select(PlayerSnapshot.observed_at).where(
                        PlayerSnapshot.id == instance.latest_snapshot_id
                    )
                )
                if instance.latest_snapshot_id is not None
                else None
            )
        if current_observed is None or observed_at >= current_observed:
            instance.latest_snapshot_id = snapshot.id
            cache[instance.id] = observed_at
        else:
            cache.setdefault(instance.id, current_observed)
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
            self._check_cancel(job, index)
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
                    previous_status = existing.status
                    existing.status = record.status
                    existing.effective_fee = effective_fee
                    existing.fee_paid = record.fee_paid
                    self.session.add(
                        TransferStatusHistory(
                            transfer_id=existing.id,
                            fm_save_id=job.fm_save_id,
                            previous_status=previous_status,
                            new_status=record.status,
                            changed_at=utcnow(),
                            source=payload.source,
                            evidence_json=json.dumps({"import_job_id": job.id}, ensure_ascii=False),
                        )
                    )
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
            self.session.add(
                TransferStatusHistory(
                    transfer_id=transfer.id,
                    fm_save_id=job.fm_save_id,
                    previous_status=None,
                    new_status=record.status,
                    changed_at=utcnow(),
                    source=payload.source,
                    evidence_json=json.dumps({"import_job_id": job.id}, ensure_ascii=False),
                )
            )
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
    """收尾上一个进程遗留的未完成任务，并写入恢复审计。

    * ``running``：后端在导入完成前退出 → ``failed``（可用同一 scan_id 重试）。
    * ``queued``：请求已创建任务但从未开始 → ``failed``（重试会重新认领）。
    * ``cancel_requested``：取消请求已记录但 Worker 未响应就退出 → ``cancelled``（取消意图必须生效）。

    每条恢复都写 ``worker_recovered``；每个受影响存档再写一条 ``backend_restarted`` 汇总事件，
    使事件能通过按存档过滤的审计 API 观察到。
    """
    session = session_factory()
    try:
        jobs = list(
            session.scalars(
                select(ImportJob).where(ImportJob.status.in_(("running", "queued", "cancel_requested")))
            )
        )
        if not jobs:
            return 0
        now = utcnow()
        per_save: dict[int, dict[str, int]] = {}
        for job in jobs:
            old_status = job.status
            save_counts = per_save.setdefault(job.fm_save_id, {"running": 0, "queued": 0, "cancel_requested": 0})
            save_counts[old_status] = save_counts.get(old_status, 0) + 1
            if old_status == "cancel_requested":
                job.status = "cancelled"
                job.cancelled_at = now
                code = "cancelled"
                message = "后端在取消完成前退出：任务已按取消处理，未提交任何业务数据"
            else:
                job.status = "failed"
                code = "interrupted"
                message = "后端在导入完成前退出：任务已标记失败，重新上传同一 scan_id 即可重试"
            job.finished_at = now
            session.add(
                ImportRow(
                    import_job_id=job.id,
                    row_index=0,
                    entity="scan",
                    code=code,
                    message=message,
                )
            )
            record_audit(
                session,
                save_id=job.fm_save_id,
                identity_id=job.save_identity_id,
                session_id=job.save_session_id,
                event_type="worker_recovered",
                old_status=old_status,
                new_status=job.status,
                evidence_summary={
                    "job_id": job.id,
                    "scan_id": job.scan_id,
                    "operation_id": job.operation_id,
                    "generation": job.save_generation,
                    "attempt_count": job.attempt_count,
                },
                reason="backend_restarted",
                actor="backend",
            )
        for save_id, save_counts in per_save.items():
            record_audit(
                session,
                save_id=save_id,
                event_type="backend_restarted",
                evidence_summary={"recovered_jobs": sum(save_counts.values()), **save_counts},
                actor="backend",
            )
        session.commit()
        return len(jobs)
    finally:
        session.close()

