"""V3.3.1 只读可视化：价值散点排除缺失身价，资金流向按状态与币种拆分。"""

from __future__ import annotations

from tests.helpers import import_document, player_row, scan_document, transfer_row


def _transfer(record_id: str, name: str, *, fee, status="completed", kind="permanent", from_uid="C2", to_uid="C1", currency="EUR", loan_fee=None):
    components = (
        [{"type": "loan_fee", "amount": loan_fee, "status": "paid"}] if loan_fee is not None else []
    )
    row = transfer_row(
        record_id,
        record_id,
        name,
        fee=fee,
        status=status,
        club_from=from_uid,
        club_to=to_uid,
        components=components,
    )
    row["transfer_type"] = kind
    row["currency"] = currency
    return row


def _seed(db) -> None:
    players = [
        player_row("P1", "Priced", ca=150, pa=170, value=30_000_000),
        player_row("P2", "NoValue", ca=120, pa=140, value=None),
    ]
    transfers = [
        _transfer("T1", "Buy", fee=30_000_000),
        _transfer("T2", "Sell", fee=10_000_000, from_uid="C1", to_uid="C2"),
        _transfer("T3", "LoanIn", fee=None, kind="loan", loan_fee=500_000),
        _transfer("T4", "Pending", fee=99_000_000, status="pending"),
        _transfer("T5", "Free", fee=None, kind="free"),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_value_scatter_excludes_missing_value(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/visualizations/value-scatter?save_id={save.id}").json()
    assert body["total"] == 2
    assert body["with_value"] == 1
    assert [point["name"] for point in body["points"]] == ["Priced"]


def test_value_scatter_respects_club_filter(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/visualizations/value-scatter?save_id={save.id}&club_id=99999").json()
    assert body["points"] == []
    assert body["total"] == 0


def test_transfer_flow_splits_loan_and_excludes_unfinished(client, db, save):
    _seed(db)
    body = client.get(f"/api/v1/visualizations/transfer-flow?save_id={save.id}").json()
    assert body["club"]["name"] == "Northbridge United"
    eur = body["currencies"][0]
    assert eur["currency"] == "EUR"
    assert eur["buy_total"] == 30_000_000
    assert eur["sell_total"] == 10_000_000
    assert eur["loan_in_fee"] == 500_000
    assert eur["net"] == 20_500_000
    assert eur["counts"]["free"] == 1
    assert body["excluded"]["pending"] == 1


def test_transfer_flow_never_merges_currencies(client, db, save):
    _seed(db)
    players = [player_row("P3", "Usd Deal")]
    transfers = [_transfer("T6", "Usd Deal", fee=5_000_000, currency="USD")]
    import_document(db, scan_document(scan_id="scan-usd", players=players, transfers=transfers))
    body = client.get(f"/api/v1/visualizations/transfer-flow?save_id={save.id}").json()
    currencies = {entry["currency"]: entry for entry in body["currencies"]}
    assert set(currencies) == {"EUR", "USD"}
    assert currencies["USD"]["buy_total"] == 5_000_000


def test_transfer_flow_without_user_club_returns_explanation(client, db, save):
    import_document(db, scan_document(players=[player_row("P4", "Solo")]))
    # 取消“我的俱乐部”标记，模拟没有指定球队的存档。
    save.user_club_id = None
    db.commit()
    from app.models import Club

    for club in db.query(Club).filter_by(fm_save_id=save.id):
        club.is_user_club = False
    db.commit()
    body = client.get(f"/api/v1/visualizations/transfer-flow?save_id={save.id}").json()
    assert body["club"] is None
    assert body["currencies"] == []
    assert "我的俱乐部" in body["note"]
