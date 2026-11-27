"""V3.3.2-05.2 分批扫描：结果一致性、幂等、增量、scan_token 下线与取消。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    Alert,
    Club,
    FmSave,
    Player,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    TransferOpportunity,
    TransferOpportunityEvent,
)
from app.services import transfer_radar
from app.utils import utcnow

_counter = {"n": 0}


def _club(db, save: FmSave, name: str = "Batch FC") -> Club:
    _counter["n"] += 1
    club = Club(fm_save_id=save.id, uid=f"batch-club-{_counter['n']}", name=name)
    db.add(club)
    db.commit()
    return club


def _seed(
    db,
    save: FmSave,
    club: Club,
    *,
    count: int,
    listed_every: int = 4,
    expiring_every: int = 3,
    prefix: str = "p",
    observed_at=None,
) -> list[PlayerInstance]:
    observed = observed_at or utcnow()
    instances = []
    for index in range(count):
        _counter["n"] += 1
        player = Player(full_name=f"{prefix}-{index}", normalized_name=f"{prefix}-{index}-{_counter['n']}")
        db.add(player)
        db.flush()
        instance = PlayerInstance(
            player_id=player.id,
            fm_save_id=save.id,
            save_local_uid=f"{prefix}-{index}",
            club_id=club.id,
        )
        db.add(instance)
        db.flush()
        snapshot = PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=observed,
            game_date=date(2026, 7, 1),
            age=24 + index % 6,
            ca=120 + index % 20,
            pa=160,
            market_value=8_000_000,
            wage=15_000,
            contract_end=date(2026, 12, 31) if expiring_every and index % expiring_every == 0 else None,
            club_id=club.id,
            club_uid=club.uid,
            position="ST",
            source="test",
        )
        db.add(snapshot)
        db.flush()
        instance.latest_snapshot_id = snapshot.id
        db.add(
            PlayerAvailability(
                player_instance_id=instance.id,
                observed_at=observed,
                listed=True if listed_every and index % listed_every == 0 else False,
                loan_listed=False,
                set_for_release=False,
                source="test",
            )
        )
        instances.append(instance)
    db.commit()
    return instances


def _rows(db, save: FmSave) -> list[TransferOpportunity]:
    return list(db.scalars(select(TransferOpportunity).where(TransferOpportunity.fm_save_id == save.id)))


def test_batched_scan_matches_expected_opportunities(db, save: FmSave) -> None:
    club = _club(db, save)
    instances = _seed(db, save, club, count=120)
    result = transfer_radar.scan_batched(db, save.id, batch_size=50)
    assert result["scanned_players"] == 120
    assert result["mode"] == "full"
    rows = _rows(db, save)
    per_instance = {}
    for row in rows:
        per_instance.setdefault(row.player_instance_id, set()).add(row.opportunity_type)
    for index, instance in enumerate(instances):
        types = per_instance.get(instance.id, set())
        if index % 4 == 0:
            assert "listed" in types
        if index % 3 == 0:
            assert "contract_expiring" in types
    assert result["created"] == len(rows)
    assert all(row.scan_token == result["checkpoint"]["token"] for row in rows)


def test_repeated_scan_is_idempotent(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=60)
    first = transfer_radar.scan_batched(db, save.id, batch_size=50)
    row_count = len(_rows(db, save))
    second = transfer_radar.scan_batched(db, save.id, batch_size=50)
    assert len(_rows(db, save)) == row_count
    assert second["created"] == 0
    assert second["events"] == 0
    assert second["alerts_created"] == 0
    assert second["updated"] == first["created"]
    assert first["created"] > 0


def test_incremental_scan_only_processes_changed_players(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=30)
    transfer_radar.scan_batched(db, save.id, batch_size=50)
    started = utcnow() - timedelta(microseconds=1)

    _seed(db, save, club, count=1, prefix="new")
    result = transfer_radar.scan_batched(db, save.id, mode="incremental", since_time=started, batch_size=50)
    assert result["incremental_available"] is True
    assert result["mode"] == "incremental"
    assert result["scanned_players"] == 1


def test_incremental_without_marker_falls_back_to_full(db, save: FmSave) -> None:
    club = _club(db, save)
    _seed(db, save, club, count=10)
    result = transfer_radar.scan_batched(db, save.id, mode="incremental", since_time=None, batch_size=50)
    assert result["incremental_available"] is False
    assert result["mode"] == "full"
    assert result["scanned_players"] == 10


def test_full_scan_withdraws_stale_opportunities(db, save: FmSave) -> None:
    club = _club(db, save)
    instances = _seed(db, save, club, count=4, listed_every=1, expiring_every=0)
    transfer_radar.scan_batched(db, save.id, batch_size=50)
    assert all(row.active for row in _rows(db, save))

    target = instances[0]
    later = utcnow() + timedelta(seconds=1)
    db.add(
        PlayerAvailability(
            player_instance_id=target.id,
            observed_at=later,
            listed=False,
            loan_listed=False,
            set_for_release=False,
            source="test",
        )
    )
    db.commit()
    result = transfer_radar.scan_batched(db, save.id, batch_size=50)
    assert result["deactivated"] == 1
    listed_row = db.scalar(
        select(TransferOpportunity).where(
            TransferOpportunity.fm_save_id == save.id,
            TransferOpportunity.player_instance_id == target.id,
            TransferOpportunity.opportunity_type == "listed",
        )
    )
    assert listed_row is not None and listed_row.active is False
    events = db.scalars(
        select(TransferOpportunityEvent).where(
            TransferOpportunityEvent.fm_save_id == save.id,
            TransferOpportunityEvent.player_instance_id == target.id,
            TransferOpportunityEvent.event_type == "withdrawn",
        )
    ).all()
    assert events
    assert db.scalar(select(Alert).where(Alert.fm_save_id == save.id, Alert.alert_type == "listed_withdrawn"))


def test_cancel_after_first_batch_keeps_partial_result_and_does_not_withdraw(db, save: FmSave) -> None:
    club = _club(db, save)
    instances = _seed(db, save, club, count=60, listed_every=1, expiring_every=0)
    stale = TransferOpportunity(
        fm_save_id=save.id,
        player_instance_id=instances[-1].id,
        opportunity_type="listed",
        verified_status="confirmed",
        confidence=1.0,
        source="player_availability",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
        active=True,
        is_primary=True,
        detail_json="{}",
        scan_token="previous-scan",
    )
    db.add(stale)
    db.commit()

    checks = {"n": 0}
    progress = []

    def cancel_cb() -> bool:
        checks["n"] += 1
        return checks["n"] > 1

    with pytest.raises(transfer_radar.ScanCancelled) as excinfo:
        transfer_radar.scan_batched(
            db,
            save.id,
            batch_size=50,
            cancel_cb=cancel_cb,
            progress_cb=lambda processed, total, matched, failed, last_id: progress.append(
                (processed, total, last_id)
            ),
        )
    checkpoint = excinfo.value.checkpoint
    assert checkpoint["last_instance_id"] == instances[49].id
    assert progress and progress[0][0] == 50 and progress[0][1] == 60
    processed_rows = [
        row
        for row in _rows(db, save)
        if row.player_instance_id in {instance.id for instance in instances[:50]}
    ]
    assert processed_rows, "第一批结果必须已提交"
    assert all(row.active for row in processed_rows)
    db.expire_all()
    assert db.get(TransferOpportunity, stale.id).active is True, "取消时不得下线旧机会"
