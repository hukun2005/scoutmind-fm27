"""P0-4 / P0-1 接口测试：状态时间线、候选转会与真实数据审查报告。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.models import PlayerInstance, Transfer, TransferCandidate

from .helpers import ensure_save
from .test_fmscout_real_data import dump, player, post_dump


def _first_instance(db) -> PlayerInstance:
    return db.query(PlayerInstance).first()


def test_player_status_exposes_flags_and_gaps(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(
        client,
        dump([player(1, "Adam Wharton", listed=True, attrs={"Passing": 15, "InjuryProneness": 13})]),
        save_id=save_id,
    )
    instance = _first_instance(db)

    body = client.get(f"/api/v1/players/{instance.id}/status").json()
    assert body["current"]["flags"]["listed"] is True
    assert body["current"]["injury"]["proneness"] == 13
    # The dump has no current-injury field: it must stay unknown, with an explicit gap.
    assert body["current"]["injury"]["injured"] is None
    assert any("伤病" in gap for gap in body["data_gaps"])
    assert body["loans"] == []
    assert body["algorithm_version"] == "player-status-1"


def test_status_changes_and_first_seen_are_tracked(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Adam Wharton", listed=False)]), save_id=save_id)
    post_dump(
        client,
        dump(
            [player(1, "Adam Wharton", listed=True)],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )
    instance = _first_instance(db)

    body = client.get(f"/api/v1/players/{instance.id}/status").json()
    assert body["current"]["flags"]["listed"] is True
    change = next(item for item in body["changes"] if item["field"] == "listed")
    assert change["from"] is False and change["to"] is True
    assert body["first_seen"]["listed"]["first_seen_at"].startswith("2027-06-01")
    assert len(body["history"]) == 2


def test_loan_option_unknown_is_not_false(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(
        client,
        dump(
            [
                player(
                    1,
                    "Loaned Kid",
                    club="Kingsport City",
                    ownerClub="Northbridge United",
                )
            ]
        ),
        save_id=save_id,
    )
    instance = _first_instance(db)

    body = client.get(f"/api/v1/players/{instance.id}/status").json()
    loan = body["loans"][0]
    assert loan["parent_club"] == "Northbridge United"
    assert loan["loan_club"] == "Kingsport City"
    assert loan["has_option"] is None
    assert any("买断条款未提供" in gap for gap in body["data_gaps"])


def test_candidate_can_be_confirmed_into_a_transfer(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Moving Man", club="Northbridge United")]), save_id=save_id)
    post_dump(
        client,
        dump(
            [player(1, "Moving Man", club="Kingsport City")],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )
    candidate = db.query(TransferCandidate).one()

    listed = client.get(f"/api/v1/transfers/candidates?save_id={save_id}").json()
    assert listed["total"] == 1
    assert listed["items"][0]["kind"] == "unknown"

    confirmed = client.post(
        f"/api/v1/transfers/candidates/{candidate.id}/confirm",
        json={"transfer_date": "2027-07-01"},
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["candidate"]["status"] == "confirmed"

    transfer = db.query(Transfer).one()
    assert transfer.status == "completed"
    assert transfer.fee_paid is None  # no fee was stated: it stays unknown rather than 0
    assert transfer.transfer_date.isoformat() == "2027-07-01"

    again = client.post(f"/api/v1/transfers/candidates/{candidate.id}/confirm", json={})
    assert again.status_code == 409


def test_candidate_can_be_dismissed(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Moving Man", club="Northbridge United")]), save_id=save_id)
    post_dump(
        client,
        dump(
            [player(1, "Moving Man", club="Kingsport City")],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )
    candidate = db.query(TransferCandidate).one()
    dismissed = client.post(
        f"/api/v1/transfers/candidates/{candidate.id}/dismiss",
        json={"reason": "租借结束回归，不是转会"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["candidate"]["status"] == "dismissed"
    assert dismissed.json()["candidate"]["evidence"]["dismiss_reason"] == "租借结束回归，不是转会"
    assert db.query(Transfer).count() == 0


def test_validate_report_has_the_expected_sections(client: TestClient, db) -> None:
    ensure_save(db)
    response = client.post(
        "/api/v1/imports/fmscout/validate",
        content=dump([player(1, "Adam Wharton"), player(2, "Diego Silva")]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    ids = [section["id"] for section in body["sections"]]
    assert ids == ["file", "dataset", "coverage", "identity", "risks"]
    assert body["sections"][0]["rows"][0] == {"label": "JSON valid", "value": "PASS"}
    assert body["sections"][1]["rows"][2]["value"] == 2  # unique ids
    assert body["verdict"]["ready_to_import"] is True
    # Injury is not in the dump, so the verdict must call it out instead of pretending the data is complete.
    assert any("伤病" in item for item in body["verdict"]["review"])


def test_validate_flags_unknown_fields_for_review(client: TestClient, db) -> None:
    ensure_save(db)
    response = client.post(
        "/api/v1/imports/fmscout/validate",
        content=dump([player(1, "Ada", brandNewThing=1)]),
        headers={"content-type": "application/json"},
    )
    body = response.json()
    risks = next(section for section in body["sections"] if section["id"] == "risks")
    unknown = next(row for row in risks["rows"] if row["label"] == "未知字段")
    assert unknown["value"] == 1
    assert body["verdict"]["status"] == "review"


def test_transfer_only_channel_imports_history(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    payload = {
        "schema_version": "1.0",
        "source": "manual",
        "scan": {"scan_id": "manual-transfers-1", "observed_at": "2027-07-01T00:00:00"},
        "clubs": [
            {"uid": "c-a", "name": "Northbridge United"},
            {"uid": "c-b", "name": "Kingsport City"},
        ],
        "players": [],
        "transfers": [
            {
                "record_id": "t-1",
                "player_name": "History Guy",
                "transfer_type": "permanent",
                "status": "completed",
                "transfer_date": "2026-07-01",
                "from_club_uid": "c-b",
                "to_club_uid": "c-a",
                "base_fee": 12_000_000,
                "fee_paid": 12_000_000,
            },
            {
                "record_id": "t-2",
                "player_name": "Rejected Guy",
                "transfer_type": "permanent",
                "status": "bid_rejected",
                "transfer_date": "2026-08-01",
                "from_club_uid": "c-b",
                "to_club_uid": "c-a",
                "base_fee": 30_000_000,
            },
        ],
    }
    first = client.post(f"/api/v1/imports/transfers?save_id={save_id}", json=payload)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["transfers_created"] == 2
    assert body["snapshots_created"] == 0

    second = client.post(f"/api/v1/imports/transfers?save_id={save_id}", json=payload)
    assert second.json()["duplicate"] is True

    rejected = db.query(Transfer).filter(Transfer.source_record_id == "t-2").one()
    assert rejected.status == "bid_rejected"


def test_transfer_only_channel_rejects_player_scan(client: TestClient, db) -> None:
    ensure_save(db)
    payload = {
        "schema_version": "1.0",
        "source": "manual",
        "scan": {"scan_id": "x", "observed_at": "2027-07-01T00:00:00"},
        "players": [{"save_local_uid": "1", "name": "No Transfers"}],
    }
    response = client.post("/api/v1/imports/transfers", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_transfers"


def test_transaction_summary_includes_agreed_and_rejected(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    payload = {
        "schema_version": "1.0",
        "source": "manual",
        "scan": {"scan_id": "manual-transfers-2", "observed_at": "2027-07-02T00:00:00"},
        "clubs": [{"uid": "c-a", "name": "Northbridge United"}, {"uid": "c-b", "name": "Kingsport City"}],
        "transfers": [
            {
                "record_id": "a-1",
                "player_name": "Agreed Guy",
                "transfer_type": "permanent",
                "status": "agreed",
                "transfer_date": "2027-09-01",
                "from_club_uid": "c-b",
                "to_club_uid": "c-a",
                "base_fee": 5_000_000,
            }
        ],
    }
    client.post(f"/api/v1/imports/transfers?save_id={save_id}", json=payload)
    summary = client.get(f"/api/v1/transfers/categories?save_id={save_id}").json()
    labels = {item["key"]: item for item in summary["categories"]}
    assert labels["agreed"]["count"] == 1
    # An agreed deal is not money spent.
    assert labels["agreed"]["known_amount"] == 0.0
    assert labels["agreed"]["counts_in_stats"] is False


def test_status_endpoint_404_for_unknown_player(client: TestClient, db) -> None:
    ensure_save(db)
    response = client.get("/api/v1/players/99999/status")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "player_not_found"


def test_candidate_payload_documents_its_rule(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Moving Man", club="Northbridge United")]), save_id=save_id)
    post_dump(
        client,
        dump(
            [player(1, "Moving Man", club="Kingsport City")],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )
    listed = client.get(f"/api/v1/transfers/candidates?save_id={save_id}").json()
    evidence = listed["items"][0]["evidence"]
    assert json.loads(json.dumps(evidence))["rule"].startswith("快照对比只能作为候选事件")
