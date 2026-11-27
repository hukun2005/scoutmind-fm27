"""V3.3.2-05.2 导入链路回归：俱乐部 UID 保留、重复导入、改俱乐部、Save 隔离与 CSV 同步。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import Club, FmSave, PlayerInstance, PlayerSnapshot, SquadAssignment
from app.services import club_linkage


def _payload(
    players: list[dict],
    *,
    scan_id: str = "link-1",
    observed_at: str = "2027-03-01T18:30:00",
    clubs: list[dict] | None = None,
) -> ScanPayload:
    document = {
        "schema_version": "1.0",
        "source": "fmsuperscout",
        "scan": {"scan_id": scan_id, "observed_at": observed_at, "game_date": "2027-03-01"},
        "clubs": clubs or [],
        "players": players,
        "transfers": [],
    }
    return ScanPayload.model_validate(document)


def _player(uid: str, name: str, club_uid: str | None = None) -> dict:
    row = {"save_local_uid": uid, "name": name, "birth_date": "2004-02-06", "nationality": "England"}
    if club_uid:
        row["club_uid"] = club_uid
    return row


def _import(db, save_id: int, payload: ScanPayload):
    outcome = ScanImporter(db).import_payload(save_id, payload, None)
    db.commit()
    return outcome


def _instance(db, save_id: int, uid: str = "p-1") -> PlayerInstance:
    return db.scalars(
        select(PlayerInstance).where(
            PlayerInstance.fm_save_id == save_id, PlayerInstance.save_local_uid == uid
        )
    ).one()


def test_import_preserves_club_uid_and_links_instance(db, save: FmSave) -> None:
    _import(
        db,
        save.id,
        _payload(
            [_player("p-1", "Linked Player", club_uid="c-1")],
            clubs=[{"uid": "c-1", "name": "Club One"}],
        ),
    )
    instance = _instance(db, save.id)
    club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == "c-1"))
    assert club is not None and instance.club_id == club.id
    assert instance.club_link_source == "player_club_field"
    assert instance.club_linked_at is not None
    snapshot = db.scalar(
        select(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == instance.id)
    )
    assert snapshot.club_uid == "c-1", "原始俱乐部引用必须保留，供可验证回填"

    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.LINKED] == 1
    assert report["sources"]["player_club_field"] == 1


def test_repeated_import_does_not_duplicate_club_or_link(db, save: FmSave) -> None:
    for scan_id, observed in (("link-1", "2027-03-01T18:30:00"), ("link-2", "2027-04-01T18:30:00")):
        _import(
            db,
            save.id,
            _payload(
                [_player("p-1", "Repeat", club_uid="c-1")],
                scan_id=scan_id,
                observed_at=observed,
                clubs=[{"uid": "c-1", "name": "Club One"}],
            ),
        )
    assert db.scalar(select(Club).where(Club.fm_save_id == save.id)).uid == "c-1"
    assert len(db.scalars(select(Club).where(Club.fm_save_id == save.id)).all()) == 1
    instance = _instance(db, save.id)
    assert len(
        db.scalars(
            select(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == instance.id)
        ).all()
    ) == 2
    first = club_linkage.repair(db, save.id)
    second = club_linkage.repair(db, save.id)
    assert first["linked"] == 0 and second["linked"] == 0


def test_changed_club_updates_instance_link(db, save: FmSave) -> None:
    _import(
        db,
        save.id,
        _payload(
            [_player("p-1", "Mover", club_uid="c-1")],
            clubs=[{"uid": "c-1", "name": "Club One"}],
        ),
    )
    _import(
        db,
        save.id,
        _payload(
            [_player("p-1", "Mover", club_uid="c-2")],
            scan_id="link-2",
            observed_at="2027-04-01T18:30:00",
            clubs=[{"uid": "c-1", "name": "Club One"}, {"uid": "c-2", "name": "Club Two"}],
        ),
    )
    instance = _instance(db, save.id)
    new_club = db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.uid == "c-2"))
    assert instance.club_id == new_club.id
    assert instance.club_link_source == "player_club_field"


def test_same_uid_in_two_saves_stays_isolated(db, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test")
    db.add(other)
    db.commit()
    for target in (save.id, other.id):
        _import(
            db,
            target,
            _payload([_player("p-1", "Shared", club_uid="c-1")], clubs=[{"uid": "c-1", "name": "Club"}],),
        )
    clubs = db.scalars(select(Club)).all()
    assert len(clubs) == 2 and len({club.fm_save_id for club in clubs}) == 2
    first = _instance(db, save.id)
    second = _instance(db, other.id)
    assert first.club_id != second.club_id
    assert db.get(Club, first.club_id).fm_save_id == save.id
    assert db.get(Club, second.club_id).fm_save_id == other.id


def test_csv_assignment_backfills_only_missing_links(db, save: FmSave, client: TestClient) -> None:
    # 来源没有俱乐部字段：导入后不关联。
    _import(db, save.id, _payload([_player("9001", "Csv Player")]))
    instance = _instance(db, save.id, uid="9001")
    assert instance.club_id is None

    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save.id}",
        content="姓名,球员ID,俱乐部,阵容\nCsv Player,9001,CSV Club,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    assert db.scalar(select(SquadAssignment)) is not None
    db.expire_all()
    assert db.get(PlayerInstance, instance.id).club_id is None  # CSV 只写声明，回填由修复服务统一执行

    result = club_linkage.repair(db, save.id)
    assert result["backfilled_assignment"] == 1
    refreshed = db.get(PlayerInstance, instance.id)
    assert refreshed.club_id is not None
    assert refreshed.club_link_source == "squad_csv"


def test_csv_does_not_overwrite_verified_scan_link(db, save: FmSave, client: TestClient) -> None:
    _import(
        db,
        save.id,
        _payload([_player("9002", "Scan Linked", club_uid="c-1")], clubs=[{"uid": "c-1", "name": "Scan Club"}]),
    )
    before = _instance(db, save.id, uid="9002").club_id
    client.post(
        f"/api/v1/imports/squad-csv?save_id={save.id}",
        content="姓名,球员ID,俱乐部,阵容\nScan Linked,9002,CSV Club,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    db.expire_all()
    assert db.get(PlayerInstance, _instance(db, save.id, uid="9002").id).club_id == before
    result = club_linkage.repair(db, save.id)
    assert result["repaired_reference"] == 0 and result["backfilled_assignment"] == 0


def test_missing_player_uid_is_not_linked_by_name(db, save: FmSave, client: TestClient) -> None:
    _import(db, save.id, _payload([_player("p-1", "Known", club_uid="c-1")], clubs=[{"uid": "c-1", "name": "Club"}]))
    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save.id}",
        content="姓名,球员ID,俱乐部,阵容\nUnknown Person,9999,Some Club,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    body = response.json()
    assert body["rows"][0]["status"] == "unmatched"
    assert db.scalar(select(SquadAssignment)) is None
