"""SM-061D：完整属性签名与冲突分类。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import PlayerInstance, PlayerSnapshot
from app.quality.dedup import build_canonicals

from tests.helpers import player_row, scan_document


def _import(db, save, scan_id: str, players: list[dict], *, source: str = "fm27_live_reader", reader: str = "0.1.0"):
    when = datetime(2026, 7, 1, 12, 0, ord(scan_id[-1]) % 60, tzinfo=timezone.utc)
    payload = scan_document(scan_id=scan_id, when=when, players=players, source=source)
    payload["reader_version"] = reader
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()


def _conflict(db, save) -> dict:
    return build_canonicals(db, save.id, dry_run=True)


def test_only_ca_and_only_pa(db, save) -> None:
    _import(db, save, "d-ca-a", [player_row("A1", "CA", ca=100, pa=150)])
    _import(db, save, "d-ca-b", [player_row("A1", "CA", ca=105, pa=150)])
    result = _conflict(db, save)
    assert result["sample_conflicts"][0]["conflict_types"] == ["ability_changed"]
    assert "ca" in result["sample_conflicts"][0]["changed_fields"]
    assert "pa" not in result["sample_conflicts"][0]["changed_fields"]


def test_one_and_many_attributes(db, save) -> None:
    _import(db, save, "d-attr-a", [player_row("A2", "Attr", attributes={"pace": 14, "passing": 12})])
    _import(db, save, "d-attr-b", [player_row("A2", "Attr", attributes={"pace": 15, "passing": 12})])
    result = _conflict(db, save)
    sample = result["sample_conflicts"][0]
    assert "attributes" in sample["changed_fields"]
    assert "ability_changed" in sample["conflict_types"]

    _import(db, save, "d-attr-c", [player_row("A3", "Attr More", attributes={"pace": 14, "passing": 12})])
    _import(db, save, "d-attr-d", [player_row("A3", "Attr More", attributes={"pace": 15, "passing": 13, "vision": 10})])
    assert any("ability_changed" in item["conflict_types"] for item in _conflict(db, save)["sample_conflicts"])


def test_attribute_missing_vs_zero_and_dict_order(db, save) -> None:
    _import(db, save, "d-zero-a", [player_row("A4", "Zero", attributes={"pace": 0})])
    _import(db, save, "d-zero-b", [player_row("A4", "Zero", attributes={"pace": 0})])
    assert _conflict(db, save)["needs_review"] == 0

    _import(db, save, "d-miss-a", [player_row("A5", "Missing", attributes={"pace": 10})])
    _import(db, save, "d-miss-b", [player_row("A5", "Missing", attributes={"pace": 0})])
    result = _conflict(db, save)
    # same key present in both, 0 is a real value -> ability_changed, not missing
    assert any("ability_changed" in item["conflict_types"] for item in result["sample_conflicts"])

    _import(db, save, "d-none-a", [player_row("A10", "None Attr", attributes={})])
    _import(db, save, "d-none-b", [player_row("A10", "None Attr", attributes={"pace": 0})])
    result = _conflict(db, save)
    assert any("missing_vs_present" in item["conflict_types"] for item in result["sample_conflicts"])
    assert any("attributes:missing" in item["changed_fields"] for item in result["sample_conflicts"])

    _import(db, save, "d-order-a", [player_row("A11", "Order", attributes={"pace": 14, "passing": 12})])
    _import(db, save, "d-order-b", [player_row("A11", "Order", attributes={"passing": 12, "pace": 14})])
    ids = {item["player_instance_id"] for item in result["sample_conflicts"]}
    order_conflicts = [item for item in _conflict(db, save)["sample_conflicts"] if "attributes" in item["changed_fields"]]
    assert order_conflicts, "order-only change must not hide real attribute conflicts"


def test_contract_valuation_club_position_physical(db, save) -> None:
    _import(db, save, "d-multi-a", [player_row("A6", "Multi", wage=1000, value=1_000, contract_end="2029-06-30", club_uid="C1", position="ST")])
    _import(db, save, "d-multi-b", [player_row("A6", "Multi", wage=2000, value=2_000, contract_end="2030-06-30", club_uid="C2", position="AMC")])
    sample = _conflict(db, save)["sample_conflicts"][0]
    assert {"contract_changed", "valuation_changed", "club_changed", "position_changed", "mixed_changes"} <= set(sample["conflict_types"])
    for field in ("wage", "market_value", "contract_end", "club_id", "position"):
        assert field in sample["changed_fields"]


def test_source_and_reader_version_change(db, save) -> None:
    _import(db, save, "d-source-a", [player_row("A7", "Source", ca=100)], source="fm27_live_reader")
    _import(db, save, "d-source-b", [player_row("A7", "Source", ca=100)], source="fmsuperscout")
    sample = _conflict(db, save)["sample_conflicts"][0]
    assert "source_changed" in sample["conflict_types"]

    _import(db, save, "d-reader-a", [player_row("A8", "Reader", ca=100)], reader="0.1.0")
    _import(db, save, "d-reader-b", [player_row("A8", "Reader", ca=100)], reader="0.2.0")
    assert any("source_changed" in item["conflict_types"] for item in _conflict(db, save)["sample_conflicts"])
    assert any("source" in item["changed_fields"] for item in _conflict(db, save)["sample_conflicts"])


def test_duplicate_import_idempotent(db, save) -> None:
    _import(db, save, "d-idem", [player_row("A9", "Idem", ca=100)])
    before = db.query(PlayerSnapshot).count()
    _import(db, save, "d-idem", [player_row("A9", "Idem", ca=100)])
    assert db.query(PlayerSnapshot).count() == before
    result = build_canonicals(db, save.id, dry_run=False)
    assert result["groups"] >= 1
