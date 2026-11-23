"""SM-121：多存档、重载与"重启"验证（文件型数据库，真实落盘）。

这不是内存库：每一步都关闭会话并释放引擎，然后在新引擎上重新查询，等价于后端进程重启。
真实 FM27 的读取需要游戏在运行，属于最终验收（见 docs/SCOUTMIND-V3.2.2.8-IMPLEMENTATION-REPORT.md）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import build_engine
from app.ingestion.importer import ImportOutcome, ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import (
    Base,
    FmSave,
    PlayerInstance,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
    User,
)
from tests.helpers import player_row, scan_document
from tests.test_unresolved_persistence import unresolved_row

SECOND_SCAN = datetime(2026, 11, 2, 12)
THIRD_SCAN = datetime(2026, 11, 3, 12)


class Database:
    """A file-backed database that can be closed and reopened like a restarted backend."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = build_engine(f"sqlite:///{path.as_posix()}")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session: Session = self.factory()

    def restart(self) -> None:
        """Drop every open session and engine, then reconnect to the same file."""
        self.session.close()
        self.engine.dispose()
        self.engine = build_engine(f"sqlite:///{self.path.as_posix()}")
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()


def _import(database: Database, save_id: int, document: dict) -> ImportOutcome:
    outcome = ScanImporter(database.session, raw_dir=database.path.parent / "raw").import_payload(
        save_id, ScanPayload.model_validate(document)
    )
    database.session.commit()
    return outcome


def _seed_saves(database: Database) -> tuple[int, int]:
    user = User(username="local", display_name="本地用户")
    database.session.add(user)
    database.session.commit()
    first = FmSave(user_id=user.id, name="存档 A", game_version="27.1", is_active=True)
    second = FmSave(user_id=user.id, name="存档 B", game_version="27.1", is_active=False)
    database.session.add_all([first, second])
    database.session.commit()
    return first.id, second.id


def test_full_flow_survives_restart_and_stays_save_isolated(tmp_path: Path) -> None:
    database = Database(tmp_path / "flow.db")
    try:
        save_a, save_b = _seed_saves(database)

        # A. 第一次扫描：3 名正常球员 + 2 名自由球员（哨兵 UID）。
        first = _import(
            database,
            save_a,
            scan_document(
                scan_id="scan-A1",
                players=[
                    player_row("A100", "Known One"),
                    player_row("A101", "Known Two"),
                    player_row("A102", "Known Three"),
                    unresolved_row("Free Agent One"),
                    unresolved_row("Free Agent Two"),
                ],
            ),
        )
        assert first.players_imported == 3
        assert first.unresolved_observations_created == 2

        # B. 同一存档重复上传同一个 scan_id：不新增观察，也不新增快照。
        duplicate = _import(
            database,
            save_a,
            scan_document(
                scan_id="scan-A1",
                players=[
                    player_row("A100", "Known One"),
                    unresolved_row("Free Agent One"),
                ],
            ),
        )
        assert duplicate.duplicate is True
        assert database.session.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2

        # C. 同一存档新的 scan_id：保存新观察，不自动合并同名候选。
        second = _import(
            database,
            save_a,
            scan_document(
                scan_id="scan-A2",
                when=SECOND_SCAN,
                players=[unresolved_row("Free Agent One")],
            ),
        )
        assert second.unresolved_created == 1
        assert database.session.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 3

        # D. 另一个存档：同名 + 同哨兵也不跨存档合并。
        other = _import(
            database,
            save_b,
            scan_document(scan_id="scan-B1", players=[unresolved_row("Free Agent One")]),
        )
        assert other.unresolved_created == 1
        per_save = dict(
            database.session.execute(
                select(UnresolvedPlayerCandidate.fm_save_id, func.count()).group_by(
                    UnresolvedPlayerCandidate.fm_save_id
                )
            ).all()
        )
        assert per_save == {save_a: 3, save_b: 1}

        # E. 重启：数据完整保留。
        database.restart()
        assert database.session.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 4
        assert database.session.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 4
        assert database.session.scalar(select(func.count()).select_from(PlayerInstance)) == 3
        names = {row for row in database.session.scalars(select(UnresolvedPlayerCandidate.display_name))}
        assert names == {"Free Agent One", "Free Agent Two"}

        # F. 重启后再扫描：没有新的候选把历史候选"粘连"，仍然按 scan 新建观察。
        third = _import(
            database,
            save_a,
            scan_document(
                scan_id="scan-A3",
                when=THIRD_SCAN,
                players=[unresolved_row("Free Agent One")],
            ),
        )
        assert third.unresolved_created == 1

        # G. 后续自由球员签约：出现合法 UID 后只产生关联建议，不自动合并历史候选。
        signed = _import(
            database,
            save_a,
            scan_document(
                scan_id="scan-A4",
                when=datetime(2026, 11, 4, 12),
                players=[player_row("A200", "Free Agent One", age=23)],
            ),
        )
        assert signed.players_imported == 1
        before = database.session.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate))
        assert before == 5
        candidate = database.session.scalar(
            select(UnresolvedPlayerCandidate)
            .where(
                UnresolvedPlayerCandidate.fm_save_id == save_a,
                UnresolvedPlayerCandidate.display_name == "Free Agent One",
            )
            .order_by(UnresolvedPlayerCandidate.id)
        )
        assert candidate is not None
        assert candidate.status in {"pending", "review_required"}
        assert candidate.resolved_player_id is None

        from app.ingestion.unresolved import identity_suggestions

        suggestions = identity_suggestions(
            database.session, save_a, name="Free Agent One", birth_date=candidate.birth_date
        )
        assert any(item["save_local_uid"] == "A200" for item in suggestions), "新的合法 UID 应作为建议出现"

        # 重启后建议与候选都还在。
        database.restart()
        assert database.session.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 5
        assert database.session.scalar(select(func.count()).select_from(PlayerInstance)) == 4
    finally:
        database.close()


def test_candidates_are_not_shared_after_restart(tmp_path: Path) -> None:
    database = Database(tmp_path / "isolation.db")
    try:
        save_a, save_b = _seed_saves(database)
        _import(database, save_a, scan_document(scan_id="iso-A", players=[unresolved_row("Twin")]))
        _import(database, save_b, scan_document(scan_id="iso-B", players=[unresolved_row("Twin")]))
        database.restart()

        a_ids = set(
            database.session.scalars(
                select(UnresolvedPlayerCandidate.id).where(UnresolvedPlayerCandidate.fm_save_id == save_a)
            )
        )
        b_ids = set(
            database.session.scalars(
                select(UnresolvedPlayerCandidate.id).where(UnresolvedPlayerCandidate.fm_save_id == save_b)
            )
        )
        assert a_ids and b_ids
        assert a_ids.isdisjoint(b_ids)
    finally:
        database.close()
