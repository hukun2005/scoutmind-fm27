"""V3.3.2-05.2 俱乐部关联修复、健康度与全局聚合的回归测试。

覆盖任务书 10.1 的 12 个身份/关联场景，以及 health / repair 幂等、dry-run、来源标注、
增删改不越权（Save 隔离）与分页聚合。不按姓名自动绑定任何球员或俱乐部。
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    SquadAssignment,
)
from app.services import club_linkage, transfer_radar
from app.utils import utcnow

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def _club(db: Session, save: FmSave, name: str = "Alpha FC", uid: str | None = None) -> Club:
    index = _next()
    club = Club(fm_save_id=save.id, uid=uid or f"club-{index}", name=name)
    db.add(club)
    db.commit()
    return club


def _instance(
    db: Session,
    save: FmSave,
    *,
    name: str = "Player",
    uid: str | None = None,
    club: Club | None = None,
    snapshot_club: Club | None = None,
    snapshot_uid: str | None = None,
    assigned_club: Club | None = None,
    assignment_confidence: float = 1.0,
    ca: int = 140,
    age: int = 25,
    contract_end: date | None = None,
    position: str = "ST",
    listed: bool | None = None,
    loan_listed: bool | None = None,
    set_for_release: bool | None = None,
    create_snapshot: bool = True,
) -> PlayerInstance:
    index = _next()
    player = Player(full_name=name, normalized_name=f"{name.lower()} {index}")
    db.add(player)
    db.flush()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid or f"player-{index}",
        club_id=club.id if club is not None else None,
    )
    db.add(instance)
    db.flush()
    observed = utcnow()
    if create_snapshot:
        snapshot = PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=observed,
            game_date=date(2026, 7, 1),
            age=age,
            ca=ca,
            pa=160,
            market_value=10_000_000,
            wage=20_000,
            contract_end=contract_end,
            club_id=snapshot_club.id if snapshot_club is not None else None,
            club_uid=snapshot_uid,
            position=position,
            source="test",
        )
        db.add(snapshot)
        db.flush()
        instance.latest_snapshot_id = snapshot.id
    if listed is not None or loan_listed is not None or set_for_release is not None:
        db.add(
            PlayerAvailability(
                player_instance_id=instance.id,
                observed_at=observed,
                listed=listed,
                loan_listed=loan_listed,
                set_for_release=set_for_release,
                source="test",
            )
        )
    if assigned_club is not None:
        db.add(
            SquadAssignment(
                fm_save_id=save.id,
                player_instance_id=instance.id,
                club_id=assigned_club.id,
                squad_type="senior",
                loan_status="none",
                source="squad_csv",
                confidence=assignment_confidence,
                observed_at=observed,
                raw_json="{}",
            )
        )
    db.commit()
    return instance


def _reload(db: Session, instance: PlayerInstance) -> PlayerInstance:
    db.expire_all()
    return db.get(PlayerInstance, instance.id)


# ---------------------------------------------------------------- 场景 1/3：正确关联与缺失俱乐部


def test_health_distinguishes_linked_and_missing_source(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    _instance(db, save, name="Linked", club=club, snapshot_club=club)
    _instance(db, save, name="No Field")
    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.LINKED] == 1
    assert report["states"][club_linkage.MISSING_SOURCE_FIELD] == 1
    assert report["states"][club_linkage.UNRESOLVED] == 0
    assert report["states"][club_linkage.INVALID_REFERENCE] == 0
    assert report["club_link_rate"] == 1.0
    assert report["link_rate_of_total"] == 0.5
    assert report["status"] == "PARTIAL_SOURCE"
    assert report["state_notes"][club_linkage.MISSING_SOURCE_FIELD]


def test_missing_club_uid_is_unresolved_and_not_guessed(db: Session, save: FmSave) -> None:
    # 场景 3：来源给了俱乐部引用，但本存档没有这条俱乐部记录。
    instance = _instance(db, save, name="Ghost Club", snapshot_uid="ghost-club")
    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.UNRESOLVED] == 1
    assert report["club_link_rate"] == 0.0

    result = club_linkage.repair(db, save.id)
    assert result["linked"] == 0
    assert result["unresolved"] == 1
    assert _reload(db, instance).club_id is None


# ---------------------------------------------------------------- 场景 4/5：同名俱乐部 / 同名球员


def test_same_name_clubs_are_not_merged(db: Session, save: FmSave) -> None:
    first = _club(db, save, name="United", uid="uid-a")
    second = _club(db, save, name="United", uid="uid-b")
    player_a = _instance(db, save, name="A", club=first, snapshot_club=first)
    player_b = _instance(db, save, name="B", club=second, snapshot_club=second)
    result = club_linkage.repair(db, save.id)
    assert result["linked"] == 0 and result["repaired_reference"] == 0
    assert _reload(db, player_a).club_id == first.id
    assert _reload(db, player_b).club_id == second.id
    assert db.scalar(select(Club).where(Club.fm_save_id == save.id, Club.name == "United")).id in {first.id, second.id}


def test_same_name_players_stay_separate(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    first = _instance(db, save, name="Same Name", uid="p-1", club=club, snapshot_club=club)
    second = _instance(db, save, name="Same Name", uid="p-2", club=club, snapshot_club=club)
    assert first.id != second.id
    assert db.scalar(select(Player).where(Player.id == first.player_id)).full_name == "Same Name"
    assert first.player_id != second.player_id
    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.LINKED] == 2


# ---------------------------------------------------------------- 场景 6/7/8：无俱乐部字段


def test_free_and_retired_players_are_not_counted_as_failures(db: Session, save: FmSave) -> None:
    # 数据源没有俱乐部字段：既不能算关联失败，也不能当成自由球员自动绑定。
    _instance(db, save, name="Free Agent", age=24)
    _instance(db, save, name="Retired", age=41, create_snapshot=True)
    _instance(db, save, name="Empty Club", age=30)
    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.MISSING_SOURCE_FIELD] == 3
    assert report["club_link_rate"] is None  # 分母为 0：没有可识别的俱乐部引用
    assert report["status"] == "BLOCKED_BY_SOURCE"


def test_null_club_id_without_source_reference_is_not_invalid(db: Session, save: FmSave) -> None:
    instance = _instance(db, save, name="Null Club")
    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.INVALID_REFERENCE] == 0
    assert report["states"][club_linkage.MISSING_SOURCE_FIELD] == 1
    club_linkage.repair(db, save.id)
    assert _reload(db, instance).club_id is None


# ---------------------------------------------------------------- 场景 9：int/string UID 差异


def test_uid_whitespace_is_normalized_but_unverifiable_is_not_guessed(db: Session, save: FmSave) -> None:
    club = _club(db, save, name="Numeric", uid="12345")
    normalized = _instance(db, save, name="Padded", snapshot_uid=" 12345 ")
    dotted = _instance(db, save, name="Dotted", snapshot_uid="12345.0")
    result = club_linkage.repair(db, save.id)
    assert result["backfilled_snapshot"] == 1
    assert _reload(db, normalized).club_id == club.id
    assert _reload(db, normalized).club_link_source == club_linkage.SOURCE_BACKFILL
    assert _reload(db, dotted).club_id is None
    assert result["unresolved"] == 1


# ---------------------------------------------------------------- 场景 10：不同 Save ID 的 UID 冲突


def test_cross_save_reference_is_invalid_and_never_bound(db: Session, save: FmSave) -> None:
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test")
    db.add(other)
    db.commit()
    own = _club(db, save, name="Mine", uid="shared-uid")
    foreign = _club(db, other, name="Foreign", uid="shared-uid")
    # 实例引用了另一个存档的俱乐部 id（历史脏数据）；来源 uid 属于本存档，可安全重绑。
    broken = _instance(db, save, name="Cross Save", club=foreign, snapshot_uid="shared-uid")
    # 没有可验证来源的悬空引用：只能清空，不能跨存档绑定。
    dangling = _instance(db, save, name="Dangling", club=foreign, create_snapshot=False)

    report = club_linkage.health(db, save.id)
    assert report["states"][club_linkage.INVALID_REFERENCE] == 2

    result = club_linkage.repair(db, save.id)
    assert result["repaired_reference"] == 1
    assert result["cleared_invalid"] == 1
    assert _reload(db, broken).club_id == own.id
    assert _reload(db, dangling).club_id is None
    # 被引用的另一个存档俱乐部完全不受影响。
    assert db.get(Club, foreign.id) is not None
    assert db.get(Club, foreign.id).fm_save_id == other.id


# ---------------------------------------------------------------- 场景 11：重复回填幂等


def test_repair_is_idempotent_and_keeps_verified_links(db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _instance(db, save, name="Stable", club=club, snapshot_club=club)
    first = club_linkage.repair(db, save.id)
    assert first["already_linked"] == 1
    assert first["linked"] == 0
    source = _reload(db, instance).club_link_source
    assert source == club_linkage.SOURCE_PAYLOAD
    second = club_linkage.repair(db, save.id)
    assert second["already_linked"] == 1
    assert second["linked"] == 0
    assert _reload(db, instance).club_id == club.id
    assert db.scalar(select(Club).where(Club.fm_save_id == save.id)).id == club.id


# ---------------------------------------------------------------- 回填来源：快照 / CSV / dry-run


def test_repair_backfills_from_snapshot_and_csv_assignment(db: Session, save: FmSave) -> None:
    snapshot_club = _club(db, save, name="From Snapshot")
    csv_club = _club(db, save, name="From CSV")
    from_snapshot = _instance(db, save, name="Snapshot Only", snapshot_club=snapshot_club)
    from_csv = _instance(db, save, name="CSV Only", assigned_club=csv_club)
    low_confidence = _instance(db, save, name="Low Confidence", assigned_club=csv_club, assignment_confidence=0.5)

    dry = club_linkage.repair(db, save.id, dry_run=True)
    assert dry["dry_run"] is True
    assert dry["backfilled_snapshot"] == 1
    assert dry["backfilled_assignment"] == 1
    assert _reload(db, from_snapshot).club_id is None  # dry-run 不落库

    result = club_linkage.repair(db, save.id)
    assert result["backfilled_snapshot"] == 1
    assert result["backfilled_assignment"] == 1
    assert _reload(db, from_snapshot).club_id == snapshot_club.id
    assert _reload(db, from_snapshot).club_link_source == club_linkage.SOURCE_BACKFILL
    assert _reload(db, from_csv).club_id == csv_club.id
    assert _reload(db, from_csv).club_link_source == club_linkage.SOURCE_CSV
    assert _reload(db, low_confidence).club_id is None


# ---------------------------------------------------------------- 全局聚合


def test_club_aggregation_filters_state_and_paginates(db: Session, save: FmSave) -> None:
    alpha = _club(db, save, name="Alpha", uid="alpha")
    beta = _club(db, save, name="Beta", uid="beta")
    listed = _instance(db, save, name="Listed", club=alpha, snapshot_club=alpha, listed=True,
                       contract_end=date(2026, 12, 31))
    _instance(db, save, name="Clean", club=alpha, snapshot_club=alpha)
    _instance(db, save, name="Beta One", club=beta, snapshot_club=beta)
    transfer_radar.scan(db, save.id)
    db.commit()

    listing = club_linkage.clubs(db, save.id, limit=1, offset=0)
    assert listing["total"] == 2
    assert len(listing["items"]) == 1
    assert listing["unlinked_players"] == 0

    page = club_linkage.clubs(db, save.id, limit=10)
    alpha_item = next(item for item in page["items"] if item["club_id"] == alpha.id)
    assert alpha_item["players"] == 2
    assert alpha_item["opportunities"]["listed"] == 1

    searched = club_linkage.clubs(db, save.id, search="Bet")
    assert searched["total"] == 1 and searched["items"][0]["club_id"] == beta.id

    listed_players = club_linkage.club_players(db, save.id, alpha.id, state="listed")
    assert listed_players["total"] == 1
    assert listed_players["items"][0]["instance_id"] == listed.id
    assert "listed" in listed_players["items"][0]["opportunity_types"]
    assert club_linkage.club_players(db, save.id, alpha.id, state="loan_listed")["total"] == 0


def test_unlinked_players_report_reason_and_search(db: Session, save: FmSave) -> None:
    _instance(db, save, name="No Source")
    _instance(db, save, name="Ghost Ref", snapshot_uid="ghost")
    all_rows = club_linkage.unlinked_players(db, save.id)
    assert all_rows["total"] == 2
    reasons = {row["player_name"]: row["state"] for row in all_rows["items"]}
    assert reasons["No Source"] == club_linkage.MISSING_SOURCE_FIELD
    assert reasons["Ghost Ref"] == club_linkage.UNRESOLVED
    assert club_linkage.unlinked_players(db, save.id, state=club_linkage.UNRESOLVED)["total"] == 1
    assert club_linkage.unlinked_players(db, save.id, search="Ghost")["total"] == 1


# ---------------------------------------------------------------- API


def test_club_link_api_and_scan_task_api(client: TestClient, db: Session, save: FmSave) -> None:
    club = _club(db, save)
    instance = _instance(db, save, name="Api Linked", club=club, snapshot_club=club)
    health = client.get("/api/v1/transfer-director/club-links/health")
    assert health.status_code == 200
    assert health.json()["states"][club_linkage.LINKED] == 1

    repair = client.post("/api/v1/transfer-director/club-links/repair", json={"dry_run": True})
    assert repair.status_code == 200 and repair.json()["dry_run"] is True
    applied = client.post("/api/v1/transfer-director/club-links/repair", json={"dry_run": False})
    assert applied.status_code == 200 and applied.json()["dry_run"] is False
    status = client.get("/api/v1/transfer-director/club-links/repair/status")
    assert status.status_code == 200
    assert status.json()["latest"]["summary"]["scanned"] >= 1

    clubs = client.get("/api/v1/transfer-director/clubs")
    assert clubs.status_code == 200 and clubs.json()["total"] == 1
    players = client.get(f"/api/v1/transfer-director/clubs/{club.id}/players")
    assert players.status_code == 200
    assert players.json()["items"][0]["instance_id"] == instance.id
    assert client.get("/api/v1/transfer-director/clubs/999999/players").status_code == 404

    unlinked = client.get("/api/v1/transfer-director/clubs/unlinked/players")
    assert unlinked.status_code == 200 and unlinked.json()["total"] == 0
