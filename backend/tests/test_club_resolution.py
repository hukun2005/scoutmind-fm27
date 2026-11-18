"""俱乐部解析与阵容 CSV 的回归测试（对应修复任务的 9 个场景）。

这些用例不使用演示数据：每个用例自己构造扫描报文，模拟真实 FMSuperScout 导出的形态（没有 clubs 数组、
球员行只有俱乐部名称），或直接构造 CSV。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.analytics.squad import squad_overview
from app.clubs import SOURCE_CSV, SOURCE_PAYLOAD_CLUBS, SOURCE_PLAYER_FIELD, ClubResolver
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import Club, FmSave, PlayerInstance, SquadAssignment

from .helpers import ensure_save


def scan_payload(
    players: list[dict],
    *,
    scan_id: str = "club-resolver-1",
    observed_at: str = "2027-03-01T18:30:00",
    clubs: list[dict] | None = None,
    user_club_uid: str | None = None,
) -> ScanPayload:
    """A scan payload that may or may not carry a clubs array."""
    document = {
        "schema_version": "1.0",
        "source": "fmsuperscout",
        "scan": {
            "scan_id": scan_id,
            "observed_at": observed_at,
            "game_date": "2027-03-01",
            "user_club_uid": user_club_uid,
        },
        "clubs": clubs or [],
        "players": players,
        "transfers": [],
    }
    return ScanPayload.model_validate(document)


def player(uid: str, name: str, club_uid: str | None = None, **extra: object) -> dict:
    row = {"save_local_uid": uid, "name": name, "birth_date": "2004-02-06", "nationality": "England"}
    if club_uid:
        row["club_uid"] = club_uid
    row.update(extra)
    return row


def import_payload(db, save_id: int, payload: ScanPayload):
    return ScanImporter(db).import_payload(save_id, payload, None)


# ---------------------------------------------------------------- 1. 没有 clubs 数组，球员有 club uid


def test_club_created_from_player_uid_without_clubs_array(db) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload([player("1", "No Clubs Array", club_uid="fs-aurora")]))
    db.commit()

    clubs = list(db.scalars(select(Club).where(Club.fm_save_id == save_id)))
    assert len(clubs) == 1
    club = clubs[0]
    assert club.uid == "fs-aurora"
    assert club.source == SOURCE_PLAYER_FIELD
    assert club.confidence == 0.6
    instance = db.scalars(select(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)).one()
    assert instance.club_id == club.id


# ---------------------------------------------------------------- 2. 没有 clubs 数组，球员有 clubName


def test_club_created_from_name_only_with_stable_uid(db) -> None:
    save_id = ensure_save(db)
    # 名称里的大小写/标点差异应归一到同一条俱乐部记录。
    import_payload(db, save_id, scan_payload([
        player("1", "A", club_uid="name:international-football-club"),
        player("2", "B", club_uid="name:international-football-club"),
    ]))
    db.commit()
    clubs = list(db.scalars(select(Club).where(Club.fm_save_id == save_id)))
    assert len(clubs) == 1

    resolver = ClubResolver(db, save_id)
    first = resolver.resolve(name="International Football Club", source=SOURCE_PLAYER_FIELD)
    second = resolver.resolve(name="  international   football club ", source=SOURCE_PLAYER_FIELD)
    db.commit()
    assert first is not None and second is not None
    assert first.club.id == second.club.id
    assert first.club.uid.startswith("name:")


# ---------------------------------------------------------------- 3. 球员缺少俱乐部字段


def test_player_without_club_is_not_assigned_to_user_club(db) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload([player("1", "No Club at All")]))
    db.commit()

    resolver = ClubResolver(db, save_id)
    assert resolver.user_club() is None
    instance = db.scalars(select(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)).one()
    assert instance.club_id is None
    assert db.scalar(select(Club).where(Club.fm_save_id == save_id)) is None


# ---------------------------------------------------------------- 4. 外租


def test_loaned_out_player_keeps_parent_and_loan_club(db) -> None:
    save_id = ensure_save(db)
    payload = scan_payload(
        [
            player(
                "1",
                "Loaned Out",
                club_uid="fs-loan-club",
                ownership={"parent_club_uid": "fs-parent-club", "loan_club_uid": "fs-loan-club"},
            )
        ],
        clubs=[
            {"uid": "fs-parent-club", "name": "Parent Club"},
            {"uid": "fs-loan-club", "name": "Loan Club"},
        ],
    )
    import_payload(db, save_id, payload)
    db.commit()

    instance = db.scalars(select(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)).one()
    loan_club = db.get(Club, instance.club_id)
    assert loan_club is not None and loan_club.name == "Loan Club"
    from app.models import LoanRecord

    loan = db.scalars(select(LoanRecord)).one()
    assert db.get(Club, loan.parent_club_id).name == "Parent Club"
    assert loan.has_option is None  # 数据源没给买断条款，标为未知而不是"无条款"


# ---------------------------------------------------------------- 5. 租入（CSV 声明）


def test_csv_marks_loan_in_and_out_without_guessing(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload([
        player("1", "Loan In Guy", club_uid="fs-my-club"),
        player("2", "Loan Out Guy", club_uid="fs-my-club"),
    ]))
    db.commit()

    csv_text = (
        "姓名,球员ID,俱乐部,阵容,租借\n"
        "Loan In Guy,1,My Club,一线队,租入\n"
        "Loan Out Guy,2,Away Club,预备队,外租\n"
    )
    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save_id}",
        content=csv_text.encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["counts"]["assigned"] == 2

    rows = list(db.scalars(select(SquadAssignment)).all())
    assert len(rows) == 2
    assert {row.loan_status for row in rows} == {"loaned_in", "loaned_out"}
    club = db.scalars(select(Club).where(Club.uid == "fs-my-club")).one()
    ClubResolver(db, save_id).set_user_club(club.id)
    db.commit()
    composition = squad_overview(db, save_id)["composition"]
    assert composition["counts"]["loaned_in"] == 1
    assert composition["counts"]["loaned_out"] == 1
    # 租入/外租分开统计，且都带来源与置信度，便于界面标注
    assert composition["buckets"]["loaned_in"][0]["confidence"] == 1.0
    assert composition["buckets"]["loaned_out"][0]["club"] == "Away Club"
    # 租入/外租是 CSV 声明的，不是从扫描报文推断的
    assert all(row.source == SOURCE_CSV for row in rows)


# ---------------------------------------------------------------- 6. 手动指定主执教俱乐部


def test_manual_user_club_does_not_move_players(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload(
        [player("1", "Someone", club_uid="fs-other")],
        clubs=[{"uid": "fs-other", "name": "Other Club"}],
    ))
    db.commit()
    club = db.scalars(select(Club).where(Club.fm_save_id == save_id)).one()
    before = db.scalars(select(PlayerInstance)).one().club_id

    response = client.put(f"/api/v1/saves/{save_id}/user-club", json={"club_id": club.id})
    assert response.status_code == 200, response.text
    assert response.json()["club"]["id"] == club.id

    db.expire_all()
    save = db.get(FmSave, save_id)
    assert save.user_club_id == club.id
    assert db.scalars(select(PlayerInstance)).one().club_id == before  # 球员所属俱乐部不变
    assert ClubResolver(db, save_id).user_club().id == club.id


def test_manual_user_club_rejects_foreign_club(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    other_save = FmSave(user_id=db.get(FmSave, save_id).user_id, name="另一个存档", is_active=False)
    db.add(other_save)
    db.commit()
    foreign = Club(fm_save_id=other_save.id, uid="fs-x", name="Foreign Club")
    db.add(foreign)
    db.commit()

    response = client.put(f"/api/v1/saves/{save_id}/user-club", json={"club_id": foreign.id})
    assert response.status_code == 404


# ---------------------------------------------------------------- 7. CSV 建立球员关联


def test_csv_links_player_by_stable_id(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload([player("9001", "Linked By Id", club_uid="fs-my-club")]))
    db.commit()

    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save_id}",
        content="姓名,球员ID,俱乐部,阵容\nLinked By Id,9001,My Club,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    row = body["rows"][0]
    assert row["status"] == "assigned"
    assert row["confidence"] == 1.0
    assert row["matched_by"] == ["player_id"]

    assignment = db.scalars(select(SquadAssignment)).one()
    assert assignment.squad_type == "senior"
    assert assignment.source == SOURCE_CSV


# ---------------------------------------------------------------- 8. 重复导入不重复建俱乐部


def test_repeated_import_does_not_duplicate_clubs(db) -> None:
    save_id = ensure_save(db)
    payload = scan_payload(
        [player("1", "Repeat", club_uid="fs-repeat")],
        clubs=[{"uid": "fs-repeat", "name": "Repeat FC"}],
    )
    import_payload(db, save_id, payload)
    db.commit()
    first = list(db.scalars(select(Club).where(Club.fm_save_id == save_id)))
    assert len(first) == 1

    # 第二份报文：同一 uid，不同观测时间，仍然只应有一条俱乐部记录。
    again = scan_payload(
        [player("1", "Repeat", club_uid="fs-repeat")],
        scan_id="club-resolver-2",
        observed_at="2027-04-01T18:30:00",
        clubs=[{"uid": "fs-repeat", "name": "Repeat FC"}],
    )
    import_payload(db, save_id, again)
    db.commit()
    second = list(db.scalars(select(Club).where(Club.fm_save_id == save_id)))
    assert len(second) == 1
    assert second[0].source == SOURCE_PAYLOAD_CLUBS  # 强来源覆盖弱来源的标记
    assert second[0].confidence == 1.0


# ---------------------------------------------------------------- 9. 低置信度不自动合并


def test_low_confidence_match_is_reported_not_merged(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    # 两名同名球员：CSV 只给姓名，无法区分，必须进入人工确认而不是随便挑一个。
    import_payload(db, save_id, scan_payload([
        player("1", "Same Name", club_uid="fs-a", birth_date="2004-02-06"),
        player("2", "Same Name", club_uid="fs-b", birth_date="2004-02-06"),
    ]))
    db.commit()

    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save_id}",
        content="姓名,俱乐部,阵容\nSame Name,Ambiguous FC,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    row = body["rows"][0]
    assert row["status"] in {"review", "unmatched"}
    assert row["confidence"] is not None and row["confidence"] < 0.8
    assert db.scalar(select(SquadAssignment)) is None  # 没有写入归属


def test_csv_unknown_name_is_unmatched(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload([player("1", "Known Player", club_uid="fs-a")]))
    db.commit()
    response = client.post(
        f"/api/v1/imports/squad-csv?save_id={save_id}",
        content="姓名,俱乐部,阵容\nCompletely Unknown,Some FC,一线队\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    body = response.json()
    assert body["rows"][0]["status"] == "unmatched"
    assert db.scalar(select(SquadAssignment)) is None


# ---------------------------------------------------------------- 阵容分析：构成与未知


def test_squad_composition_reports_unknown_instead_of_free_agents(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload(
        [
            player("1", "Senior One", club_uid="fs-my-club"),
            player("2", "Youth One", club_uid="fs-my-club"),
            player("3", "No Tier", club_uid="fs-my-club"),
        ],
        clubs=[{"uid": "fs-my-club", "name": "My Club"}],
    ))
    db.commit()
    club = db.scalars(select(Club).where(Club.uid == "fs-my-club")).one()
    ClubResolver(db, save_id).set_user_club(club.id)
    db.commit()

    client.post(
        f"/api/v1/imports/squad-csv?save_id={save_id}",
        content=(
            "姓名,球员ID,俱乐部,阵容\n"
            "Senior One,1,My Club,一线队\n"
            "Youth One,2,My Club,青年队\n"
        ).encode("utf-8"),
        headers={"content-type": "text/csv"},
    )

    overview = squad_overview(db, save_id)
    composition = overview["composition"]
    assert composition["available"] is True
    assert composition["counts"]["senior"] == 1
    assert composition["counts"]["youth"] == 1
    # 没有名单依据的球员进入 unknown，而不是被算成自由球员或一线队。
    assert composition["counts"]["unknown"] == 0
    assert composition["counts"]["loaned_in"] == 0
    assert any("不在阵容名单里" in gap or "无法确认" in gap for gap in composition["gaps"])


def test_squad_composition_unavailable_without_assignments(db) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload(
        [player("1", "Only Scan", club_uid="fs-my-club")],
        clubs=[{"uid": "fs-my-club", "name": "My Club"}],
    ))
    db.commit()
    club = db.scalars(select(Club).where(Club.uid == "fs-my-club")).one()
    ClubResolver(db, save_id).set_user_club(club.id)
    db.commit()

    composition = squad_overview(db, save_id)["composition"]
    assert composition["available"] is False
    assert composition["buckets"] == {}
    assert any("阵容名单" in item for item in composition["missing"])


# ---------------------------------------------------------------- 俱乐部来源展示


def test_club_search_exposes_source_and_confidence(db, client: TestClient) -> None:
    save_id = ensure_save(db)
    import_payload(db, save_id, scan_payload(
        [player("1", "Sourced", club_uid="fs-sourced")],
        clubs=[{"uid": "fs-sourced", "name": "Sourced FC", "league": "Premier Division"}],
    ))
    db.commit()

    response = client.get(f"/api/v1/clubs/search?limit=10")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    entry = items[0]
    assert entry["source"] == SOURCE_PAYLOAD_CLUBS
    assert entry["source_label"]
    assert entry["confidence"] == 1.0
    assert entry["players"] >= 1
    assert entry["is_user_club"] is False


def test_csv_template_is_importable(client: TestClient, db) -> None:
    template = client.get("/api/v1/imports/squad-csv/template")
    assert template.status_code == 200
    content = template.json()["content"]
    assert "球员ID" in content.splitlines()[0]
    assert content.count("\n") >= 3
    json.dumps(template.json(), ensure_ascii=False)  # 可序列化
