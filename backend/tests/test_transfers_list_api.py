"""Regression tests for `GET /transfers` and `GET /transfers/stats` (V3.2.9.2 Phase 2).

The list endpoint used to reference an undefined ``all_rows`` variable, which made every list request fail
with a ``NameError``. It also ignored the documented ``sort`` parameter and computed "coverage" from the
current page. These tests pin the real contract: paging, filters, sorting, totals, coverage and the
boundary between the list (all statuses) and the statistics sample (completed permanent deals only).
"""

from __future__ import annotations

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave

from tests.helpers import RAW_DIR, import_document, player_row, scan_document, transfer_row


def _import_into(db, save_id: int, document: dict) -> None:
    """Import one payload into an explicit save (for the isolation test)."""
    ScanImporter(db, raw_dir=RAW_DIR).import_payload(save_id, ScanPayload.model_validate(document))
    db.commit()


def _seed(db, *, fees=(10_000_000, 20_000_000, 30_000_000, 40_000_000, 50_000_000)) -> None:
    players = [player_row(f"P{index}", f"Player {index}", ca=140 + index) for index in range(len(fees))]
    transfers = [
        transfer_row(f"T{index}", f"P{index}", f"Player {index}", fee=fee, when=f"2026-07-{index + 1:02d}")
        for index, fee in enumerate(fees)
    ]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_list_returns_rows_total_and_coverage(client, db, save):
    """A normal page returns the rows, the full total and field coverage."""
    _seed(db)
    response = client.get(f"/api/v1/transfers?save_id={save.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["coverage"]["effective_fee"] == 1.0
    assert body["coverage"]["transfer_date"] == 1.0
    assert body["coverage"]["ca_at_transfer"] == 1.0
    assert body["coverage"]["contract_remaining_months"] == 1.0


def test_empty_list_is_not_an_error(client, db, save):
    """No transfers yields an empty page, a zero total and zero coverage."""
    import_document(db, scan_document(players=[player_row("P1", "Solo")], transfers=[]))
    response = client.get(f"/api/v1/transfers?save_id={save.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["coverage"] == {
        "effective_fee": 0.0,
        "transfer_date": 0.0,
        "ca_at_transfer": 0.0,
        "contract_remaining_months": 0.0,
    }


def test_limit_one_pages_through_every_row(client, db, save):
    """limit=1 walks all rows without duplicates and keeps the total stable."""
    _seed(db)
    seen: list[int] = []
    for offset in range(5):
        body = client.get(f"/api/v1/transfers?save_id={save.id}&limit=1&offset={offset}").json()
        assert body["total"] == 5
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
    assert len(set(seen)) == 5


def test_offset_beyond_total_is_an_empty_page(client, db, save):
    """An offset past the end returns no rows but keeps the real total."""
    _seed(db)
    body = client.get(f"/api/v1/transfers?save_id={save.id}&offset=999").json()
    assert body["items"] == []
    assert body["total"] == 5


def test_status_filter_keeps_pending_out_of_default_list(client, db, save):
    """Default status is completed; pending deals only appear with an explicit filter."""
    players = [player_row("P1", "Done"), player_row("P2", "Pending")]
    transfers = [
        transfer_row("T1", "P1", "Done", fee=10_000_000),
        transfer_row("T2", "P2", "Pending", fee=15_000_000, status="pending"),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    completed = client.get(f"/api/v1/transfers?save_id={save.id}").json()
    assert completed["total"] == 1
    assert completed["items"][0]["status"] == "completed"

    pending = client.get(f"/api/v1/transfers?save_id={save.id}&status=pending").json()
    assert pending["total"] == 1
    assert pending["items"][0]["status"] == "pending"

    everything = client.get(f"/api/v1/transfers?save_id={save.id}&status=all").json()
    assert everything["total"] == 2


def test_transfer_type_filter_does_not_merge_loans(client, db, save):
    """Loans and permanent deals are filtered separately and never merged."""
    players = [player_row("P1", "Bought"), player_row("P2", "Loaned")]
    transfers = [
        transfer_row("T1", "P1", "Bought", fee=10_000_000),
        {**transfer_row("T2", "P2", "Loaned", fee=1_000_000), "transfer_type": "loan"},
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    loans = client.get(f"/api/v1/transfers?save_id={save.id}&transfer_type=loan").json()
    assert loans["total"] == 1
    assert loans["items"][0]["transfer_type"] == "loan"

    permanent = client.get(f"/api/v1/transfers?save_id={save.id}&transfer_type=permanent").json()
    assert permanent["total"] == 1
    assert permanent["items"][0]["transfer_type"] == "permanent"


def test_missing_fee_is_reported_not_zeroed(client, db, save):
    """A transfer without a fee keeps effective_fee=None and lowers coverage instead of becoming 0."""
    players = [player_row("P1", "Priced"), player_row("P2", "Unknown")]
    transfers = [
        transfer_row("T1", "P1", "Priced", fee=10_000_000),
        transfer_row("T2", "P2", "Unknown", fee=None),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    body = client.get(f"/api/v1/transfers?save_id={save.id}").json()
    assert body["total"] == 2
    by_name = {row["player_name"]: row for row in body["items"]}
    assert by_name["Unknown"]["effective_fee"] is None
    assert body["coverage"]["effective_fee"] == 0.5


def test_addon_components_are_potential_not_paid(client, db, save):
    """An untriggered add-on is reported as potential money and stays out of the effective fee."""
    components = [
        {"type": "base_fee", "amount": 5_000_000, "status": "paid"},
        {"type": "addon", "amount": 2_000_000, "status": "untriggered"},
    ]
    import_document(
        db,
        scan_document(
            players=[player_row("P1", "Addon Player")],
            transfers=[transfer_row("T1", "P1", "Addon Player", fee=5_000_000, components=components)],
        ),
    )
    body = client.get(f"/api/v1/transfers?save_id={save.id}").json()
    row = body["items"][0]
    assert row["effective_fee"] == 5_000_000
    assert row["potential_total"] == 2_000_000
    assert len(row["fee_components"]) == 2


def test_transfers_are_isolated_per_save(client, db, save):
    """A second save never leaks its transfers into the first save's list."""
    _seed(db, fees=(10_000_000, 20_000_000))
    other = FmSave(user_id=save.user_id, name="另一个存档", game_version="27.0", game_build="test", is_active=False)
    db.add(other)
    db.commit()
    _import_into(
        db,
        other.id,
        scan_document(
            scan_id="scan-2",
            players=[player_row("P9", "Other Save Player")],
            transfers=[transfer_row("T9", "P9", "Other Save Player", fee=99_000_000)],
            clubs=[],
        ),
    )

    first = client.get(f"/api/v1/transfers?save_id={save.id}").json()
    second = client.get(f"/api/v1/transfers?save_id={other.id}").json()
    assert first["total"] == 2
    assert second["total"] == 1
    assert second["items"][0]["player_name"] == "Other Save Player"


def test_list_and_stats_agree_on_completed_permanent_sample(client, db, save):
    """The list total and the statistics sample describe the same completed-permanent population."""
    players = [player_row(f"P{index}", f"Player {index}") for index in range(3)]
    transfers = [
        transfer_row("T1", "P0", "Player 0", fee=10_000_000),
        transfer_row("T2", "P1", "Player 1", fee=30_000_000),
        {**transfer_row("T3", "P2", "Player 2", fee=1_000_000), "transfer_type": "loan"},
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    listed = client.get(f"/api/v1/transfers?save_id={save.id}").json()
    stats = client.get(f"/api/v1/transfers/stats?save_id={save.id}").json()
    assert listed["total"] == 3
    assert stats["availability"]["completed_for_stats"] == 2
    assert stats["sample_size"] == 2
    assert stats["median"] == 20_000_000


def test_coverage_is_stable_across_pages(client, db, save):
    """Paging never changes coverage; coverage describes the filtered set, not the page."""
    players = [player_row(f"P{index}", f"Player {index}") for index in range(4)]
    transfers = [
        transfer_row("T1", "P0", "Player 0", fee=10_000_000),
        transfer_row("T2", "P1", "Player 1", fee=None),
        transfer_row("T3", "P2", "Player 2", fee=30_000_000),
        transfer_row("T4", "P3", "Player 3", fee=40_000_000),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    first = client.get(f"/api/v1/transfers?save_id={save.id}&limit=1&offset=0").json()
    last = client.get(f"/api/v1/transfers?save_id={save.id}&limit=1&offset=3").json()
    wide = client.get(f"/api/v1/transfers?save_id={save.id}&limit=100").json()
    assert first["coverage"] == last["coverage"] == wide["coverage"]
    assert first["coverage"]["effective_fee"] == 0.75
    assert first["total"] == last["total"] == wide["total"] == 4


def test_invalid_sort_is_rejected(client, db, save):
    """An unknown sort field is a 400 instead of silently keeping the default order."""
    _seed(db)
    response = client.get(f"/api/v1/transfers?save_id={save.id}&sort=drop_table")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_sort"


def test_sort_by_effective_fee_both_directions(client, db, save):
    """`effective_fee` sorts ascending and descending, with missing fees last."""
    players = [player_row(f"P{index}", f"Player {index}") for index in range(3)]
    transfers = [
        transfer_row("T1", "P0", "Player 0", fee=30_000_000),
        transfer_row("T2", "P1", "Player 1", fee=None),
        transfer_row("T3", "P2", "Player 2", fee=10_000_000),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))

    ascending = client.get(f"/api/v1/transfers?save_id={save.id}&sort=effective_fee").json()["items"]
    assert [row["effective_fee"] for row in ascending] == [10_000_000, 30_000_000, None]

    descending = client.get(f"/api/v1/transfers?save_id={save.id}&sort=-effective_fee").json()["items"]
    assert [row["effective_fee"] for row in descending] == [30_000_000, 10_000_000, None]
