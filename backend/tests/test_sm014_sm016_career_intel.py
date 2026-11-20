"""SM-014 / SM-015 / SM-016：职业轨迹、俱乐部转会情报、投资回报。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Club,
    FmSave,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferFeeComponent,
    User,
)
from app.utils import utcnow

from tests.helpers import player_row, scan_document


def _seed_scan(db, save, players: list[dict], scan_id: str = "career-1"):
    from app.ingestion.importer import ScanImporter
    from app.ingestion.protocol import ScanPayload

    payload = ScanPayload.model_validate(scan_document(scan_id=scan_id, players=players))
    ScanImporter(db).import_payload(save.id, payload)
    db.commit()


def test_career_timeline_orders_snapshots_and_transfers(client: TestClient, db, save) -> None:
    _seed_scan(db, save, [player_row("C1", "Career Player", age=22, ca=140, pa=170)])
    instance = db.scalar(select(PlayerInstance))
    db.add(
        Transfer(
            fm_save_id=save.id,
            source_record_id="CAREER-T1",
            player_instance_id=instance.id,
            player_name="Career Player",
            transfer_type="permanent",
            status="completed",
            transfer_date=date(2026, 7, 1),
            currency="EUR",
            effective_fee=10_000_000,
            source="manual",
        )
    )
    db.commit()

    response = client.get(f"/api/v1/players/{instance.id}/career")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["player_id"] == instance.player_id
    timeline = body["timeline"]
    assert timeline and all("date" in item for item in timeline)
    assert [item["date"] for item in timeline] == sorted(item["date"] for item in timeline)
    assert any(item["type"] == "transfer" for item in timeline)
    assert body["coverage"]["saves_with_player"] == [save.id]
    assert "identity" in body and body["identity"]["note"]


def test_career_is_limited_to_owned_saves(client: TestClient, db, save) -> None:
    _seed_scan(db, save, [player_row("C2", "Private Player")], scan_id="career-2")
    instance = db.scalar(select(PlayerInstance))
    other_user = User(username="stranger2", display_name="别人")
    db.add(other_user)
    db.commit()
    foreign = FmSave(user_id=other_user.id, name="别人存档", game_version="27.1", game_build="x")
    db.add(foreign)
    db.commit()
    # 把实例挂到别人的存档下：当前用户不应看到
    instance.fm_save_id = foreign.id
    db.commit()
    response = client.get(f"/api/v1/players/{instance.id}/career")
    assert response.status_code == 404


def _club(db, save, name: str) -> Club:
    uid = "club-" + name.lower().replace(" ", "-")
    club = Club(fm_save_id=save.id, uid=uid, name=name)
    db.add(club)
    db.commit()
    return club


def _transfer(
    db,
    save,
    *,
    record: str,
    player: str,
    from_club: Club | None,
    to_club: Club | None,
    fee: float | None,
    status: str = "completed",
    transfer_type: str = "permanent",
    when: date = date(2026, 7, 1),
    age: int | None = 24,
    loan_fee: float | None = None,
) -> Transfer:
    row = Transfer(
        fm_save_id=save.id,
        source_record_id=record,
        player_name=player,
        from_club_id=from_club.id if from_club else None,
        to_club_id=to_club.id if to_club else None,
        from_club_name=from_club.name if from_club else None,
        to_club_name=to_club.name if to_club else None,
        transfer_type=transfer_type,
        status=status,
        transfer_date=when,
        currency="EUR",
        base_fee=fee,
        effective_fee=fee,
        loan_fee=loan_fee,
        player_age_at_transfer=age,
        source="manual",
    )
    db.add(row)
    db.commit()
    return row


def test_club_intelligence_counts_only_completed(client: TestClient, db, save) -> None:
    a = _club(db, save, "Alpha FC")
    b = _club(db, save, "Beta FC")
    _transfer(db, save, record="A1", player="Bought One", from_club=b, to_club=a, fee=20_000_000)
    _transfer(db, save, record="A2", player="Bought Two", from_club=b, to_club=a, fee=5_000_000, transfer_type="loan", loan_fee=500_000)
    _transfer(db, save, record="A3", player="Sold One", from_club=a, to_club=b, fee=30_000_000)
    _transfer(db, save, record="A4", player="Agreed One", from_club=b, to_club=a, fee=99_000_000, status="agreed")
    _transfer(db, save, record="A5", player="Cancelled One", from_club=b, to_club=a, fee=88_000_000, status="cancelled")
    _transfer(db, save, record="A6", player="Free One", from_club=b, to_club=a, fee=0.0, transfer_type="free_transfer")

    response = client.get(f"/api/v1/clubs/{a.id}/transfer-intelligence")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completed"]["buy"]["count"] == 3, "两笔永久 + 一笔租借"
    assert body["completed"]["buy"]["cash"] == 20_000_000, "租借不并入永久转会现金"
    assert body["completed"]["sell"]["cash"] == 30_000_000
    assert body["completed"]["net_cash"] == -10_000_000
    assert body["agreed"]["count"] == 1
    assert body["cancelled"]["count"] == 1
    assert body["coverage"]["fee_unknown"] == 0
    assert body["by_type"]["free_transfer"]["count"] == 1
    assert "工资" in " ".join(body["data_notes"]) or body["coverage"]["fee_ratio"] == 1.0


def test_club_intelligence_reports_unknown_fees(client: TestClient, db, save) -> None:
    a = _club(db, save, "Gamma FC")
    b = _club(db, save, "Delta FC")
    _transfer(db, save, record="G1", player="Unknown Fee", from_club=b, to_club=a, fee=None)
    body = client.get(f"/api/v1/clubs/{a.id}/transfer-intelligence").json()
    assert body["coverage"]["fee_unknown"] == 1
    assert body["completed"]["buy"]["unknown_fee_count"] == 1
    assert body["completed"]["buy"]["cash"] == 0.0, "未知金额不累加，但计数明确"


def test_roi_distinguishes_cash_accounting_and_valuation(client: TestClient, db, save) -> None:
    a = _club(db, save, "Roi FC")
    b = _club(db, save, "Seller FC")
    buy = _transfer(db, save, record="R1", player="Roi Player", from_club=b, to_club=a, fee=10_000_000)
    db.add(
        TransferFeeComponent(
            transfer_id=buy.id, component_type="addon", amount=2_000_000, status="paid"
        )
    )
    db.add(
        TransferFeeComponent(
            transfer_id=buy.id, component_type="addon", amount=3_000_000, status="pending"
        )
    )
    player = Player(full_name="Roi Player", normalized_name="roi-player")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid="ROI1")
    db.add(instance)
    db.commit()
    buy.player_instance_id = instance.id
    snapshot = PlayerSnapshot(
        player_instance_id=instance.id,
        observed_at=utcnow(),
        game_date=date(2026, 11, 1),
        ca=150,
        pa=170,
        market_value=18_000_000,
        wage=50_000,
        contract_end=date(2031, 6, 30),
        source="manual",
    )
    db.add(snapshot)
    db.commit()

    body = client.get(f"/api/v1/transfers/{buy.id}/roi").json()
    assert body["buy"]["cash_cost"] == 12_000_000, "买入价 + 已支付附加条款，未触发的不计入"
    assert body["buy"]["potential_addons"] == 3_000_000
    assert body["sale"]["available"] is False
    assert body["cash"]["realized_profit"] is None
    assert body["valuation"]["delta"] == 6_000_000
    assert "不是现金利润" in body["valuation"]["note"]
    assert body["accounting"]["total"] is not None


def test_roi_realized_profit_after_sale(client: TestClient, db, save) -> None:
    a = _club(db, save, "Buyer FC")
    b = _club(db, save, "Seller Two")
    buy = _transfer(db, save, record="P1", player="Resale Player", from_club=b, to_club=a, fee=10_000_000)
    sell = _transfer(
        db, save, record="P2", player="Resale Player", from_club=a, to_club=b, fee=25_000_000,
        when=date(2027, 1, 1),
    )
    player = Player(full_name="Resale Player", normalized_name="resale-player")
    db.add(player)
    db.commit()
    instance = PlayerInstance(player_id=player.id, fm_save_id=save.id, save_local_uid="P1")
    db.add(instance)
    db.commit()
    buy.player_instance_id = instance.id
    sell.player_instance_id = instance.id
    db.commit()

    body = client.get(f"/api/v1/transfers/{buy.id}/roi").json()
    assert body["sale"]["available"] is True
    assert body["cash"]["realized_profit"] == 15_000_000
    assert body["valuation"] is None or "market_value" in body["valuation"]


def test_roi_missing_fee_is_unknown_not_zero(client: TestClient, db, save) -> None:
    a = _club(db, save, "No Fee FC")
    b = _club(db, save, "Other FC")
    buy = _transfer(db, save, record="N1", player="No Fee Player", from_club=b, to_club=a, fee=None)
    body = client.get(f"/api/v1/transfers/{buy.id}/roi").json()
    assert body["buy"]["cash_cost"] is None
    assert body["cash"]["realized_profit"] is None
    assert any("未知" in item or "没有找到" in item for item in body["missing"]) or body["cash"]["realized_note"]
