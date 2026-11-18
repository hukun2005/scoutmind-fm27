"""Scan-payload builders shared by the ingestion, analytics and API tests."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ingestion.importer import ImportOutcome, ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, User

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "test-raw"


def club_row(uid: str, name: str, league: str = "Premier Division", reputation: int = 7000, user_club: bool = False) -> dict:
    """One club row for a scan."""
    return {
        "uid": uid,
        "name": name,
        "nation": "England",
        "league": league,
        "reputation": reputation,
        "is_user_club": user_club,
    }


def player_row(
    uid: str,
    name: str,
    ca: int = 140,
    pa: int = 160,
    value: int | None = 20_000_000,
    position: str = "ST",
    age: int = 22,
    club_uid: str | None = "C1",
    contract_end: str | None = "2029-06-30",
    attributes: dict[str, float] | None = None,
    statistics: list[dict] | None = None,
    wage: int = 40_000,
) -> dict:
    """One player row for a scan."""
    birth = date(2026 - age, 5, 1)
    return {
        "record_id": uid,
        "save_local_uid": uid,
        "game_unique_id": f"G-{uid}",
        "name": name,
        "birth_date": birth.isoformat(),
        "nationality": "England",
        "position": position,
        "club_uid": club_uid,
        "ca": ca,
        "pa": pa,
        "market_value": value,
        "wage": wage,
        "contract_end": contract_end,
        "minutes_played": 1200,
        "appearances": 20,
        "goals": 3,
        "assists": 4,
        "attributes": attributes or {},
        "statistics": statistics or [],
    }


def season_stats(
    period: str = "2026/27",
    minutes: int = 1800,
    appearances: int = 22,
    goals: int = 8,
    assists: int = 4,
    shots: int = 40,
    shots_on_target: int = 18,
    xg: float = 7.5,
    key_passes: int = 24,
    tackles: int = 30,
    interceptions: int = 20,
    clearances: int = 10,
    aerials_won: int = 12,
    saves: int | None = None,
    conceded: int | None = None,
    clean_sheets: int | None = None,
) -> dict:
    """One season statistics block for a scan player row."""
    block: dict = {
        "period": period,
        "competition": "Premier Division",
        "appearances": appearances,
        "minutes_played": minutes,
        "goals": goals,
        "assists": assists,
        "shots": shots,
        "shots_on_target": shots_on_target,
        "xg": xg,
        "key_passes": key_passes,
        "tackles": tackles,
        "interceptions": interceptions,
        "clearances": clearances,
        "aerials_won": aerials_won,
    }
    if saves is not None:
        block["saves"] = saves
    if conceded is not None:
        block["conceded"] = conceded
    if clean_sheets is not None:
        block["clean_sheets"] = clean_sheets
    return block


def transfer_row(
    record_id: str,
    player_uid: str,
    name: str,
    fee: float | None,
    when: str = "2026-07-01",
    status: str = "completed",
    age: int = 22,
    ca: int = 140,
    pa: int = 160,
    club_from: str = "C2",
    club_to: str = "C1",
    components: list[dict] | None = None,
) -> dict:
    """One transfer row for a scan."""
    return {
        "record_id": record_id,
        "player_record_id": player_uid,
        "player_name": name,
        "transfer_type": "permanent",
        "status": status,
        "transfer_date": when,
        "season": "2026/27",
        "from_club_uid": club_from,
        "from_club_name": f"Club {club_from}",
        "to_club_uid": club_to,
        "to_club_name": f"Club {club_to}",
        "currency": "EUR",
        "base_fee": fee,
        "fee_paid": fee if status == "completed" else None,
        "addons_potential": None,
        "player_age_at_transfer": age,
        "player_ca_at_transfer": ca,
        "player_pa_at_transfer": pa,
        "contract_remaining_months": 24,
        "confidence": 1.0,
        "fee_components": components or [],
    }


def scan_document(
    scan_id: str = "scan-1",
    when: datetime | None = None,
    players: list[dict] | None = None,
    transfers: list[dict] | None = None,
    clubs: list[dict] | None = None,
    source: str = "fm27_live_reader",
) -> dict:
    """Build a complete scan document."""
    observed = when or datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    return {
        "schema_version": "1.0",
        "source": source,
        "reader_version": "0.1.0",
        "game": {"version": "27.0.1", "build": "26577676", "app_id": "4530370"},
        "scan": {
            "scan_id": scan_id,
            "observed_at": observed.isoformat(),
            "game_date": observed.date().isoformat(),
            "user_club_uid": "C1",
        },
        "coverage": {"players": True},
        "warnings": [],
        "clubs": clubs
        if clubs is not None
        else [club_row("C1", "Northbridge United", user_club=True), club_row("C2", "Kingsport City")],
        "players": players or [],
        "transfers": transfers or [],
    }


def ensure_save(db: Session) -> int:
    """Return the first save id, creating a user and save when none exists."""
    save = db.query(FmSave).order_by(FmSave.id).first()
    if save is not None:
        return save.id
    user = User(username="local", display_name="测试用户")
    db.add(user)
    db.commit()
    save = FmSave(user_id=user.id, name="测试存档", game_version="27.0", game_build="test", is_active=True)
    db.add(save)
    db.commit()
    return save.id


def import_document(db: Session, document: dict) -> ImportOutcome:
    """Validate and import one document into the first save."""
    payload = ScanPayload.model_validate(document)
    outcome = ScanImporter(db, raw_dir=RAW_DIR).import_payload(ensure_save(db), payload)
    db.commit()
    return outcome
