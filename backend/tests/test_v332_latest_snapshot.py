"""V3.3.2 最新快照引用：导入维护、历史回补不覆盖、列表读取一致。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.analytics.players import PlayerFilter, list_players
from app.models import FmSave, PlayerInstance, PlayerSnapshot, User
from tests.helpers import import_document, player_row, scan_document


def _doc(scan_id: str, when: datetime, ca: int) -> dict:
    return scan_document(
        scan_id=scan_id,
        when=when,
        players=[player_row("P1", "Mario Bianchi", ca=ca, pa=180)],
    )


def test_import_maintains_latest_snapshot_reference(db) -> None:
    import_document(db, _doc("scan-1", datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 120))
    instance = db.scalar(select(PlayerInstance))
    assert instance.latest_snapshot_id is not None
    first = db.get(PlayerSnapshot, instance.latest_snapshot_id)
    assert first is not None and first.ca == 120

    import_document(db, _doc("scan-2", datetime(2026, 11, 1, 12, tzinfo=timezone.utc), 150))
    db.expire_all()
    instance = db.scalar(select(PlayerInstance))
    latest = db.get(PlayerSnapshot, instance.latest_snapshot_id)
    assert latest is not None
    assert latest.ca == 150
    assert latest.observed_at == datetime(2026, 11, 1, 12)


def test_backdated_import_does_not_override_latest(db) -> None:
    import_document(db, _doc("scan-new", datetime(2026, 11, 1, 12, tzinfo=timezone.utc), 150))
    import_document(db, _doc("scan-old", datetime(2026, 9, 1, 12, tzinfo=timezone.utc), 110))
    db.expire_all()
    instance = db.scalar(select(PlayerInstance))
    latest = db.get(PlayerSnapshot, instance.latest_snapshot_id)
    assert latest is not None and latest.ca == 150, "历史回补不能把最新快照改回旧数据"
    assert len(list(db.scalars(select(PlayerSnapshot)))) == 2, "历史快照必须保留"


def test_list_players_uses_materialized_latest_snapshot(db) -> None:
    import_document(db, _doc("scan-1", datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 120))
    import_document(db, _doc("scan-2", datetime(2026, 11, 1, 12, tzinfo=timezone.utc), 150))
    save_id = db.scalar(select(PlayerInstance.fm_save_id))
    body = list_players(db, save_id, PlayerFilter(), limit=10)
    assert body["total"] == 1
    row = body["items"][0]
    assert row["ca"] == 150
    assert row["observed_at"].startswith("2026-11-01T12:00:00")


def test_legacy_snapshot_without_reference_still_readable(db) -> None:
    """没有 latest_snapshot_id 的旧数据仍走回退逻辑，不会从列表消失。"""
    from tests.test_v331_watchlist_workflow import _player

    save = db.query(FmSave).first()
    if save is None:
        user = User(username="legacy", display_name="旧库")
        db.add(user)
        db.flush()
        save = FmSave(user_id=user.id, name="旧库存档", is_active=True)
        db.add(save)
        db.commit()
    _player(db, save, "Legacy Striker", "LEG-1")
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "LEG-1"))
    assert instance is not None and instance.latest_snapshot_id is None
    body = list_players(db, save.id, PlayerFilter(), limit=10)
    assert [item["name"] for item in body["items"]] == ["Legacy Striker"]
