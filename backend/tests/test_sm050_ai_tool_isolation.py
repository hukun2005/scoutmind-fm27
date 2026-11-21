"""SM-050：AI 工具参数必须限定在当前存档内。"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.agents import llm_planner
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave, PlayerInstance, Transfer, User

from tests.helpers import player_row, scan_document


def _add_save(db, username: str, name: str) -> FmSave:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, display_name=username)
        db.add(user)
        db.commit()
    save = FmSave(user_id=user.id, name=name, game_version="27.1", game_build="x", is_active=False)
    db.add(save)
    db.commit()
    return save


def _import_player(db, save, name: str) -> PlayerInstance:
    payload = scan_document(
        scan_id=f"sm050-{name}",
        players=[player_row(name, name, age=23, ca=140, pa=160, value=10_000_000)],
    )
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(payload))
    db.commit()
    return db.scalar(select(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))


def test_own_and_second_save_are_allowed(db, save) -> None:
    second = _add_save(db, "local", "Second Save")
    own = _import_player(db, save, "OWN050")
    other = _import_player(db, second, "SECOND050")
    result = llm_planner.execute_plan(db, save.id, [("player_profile", {"instance_id": own.id})])
    assert result.calls and result.mode == "llm"
    result2 = llm_planner.execute_plan(db, second.id, [("player_profile", {"instance_id": other.id})])
    assert result2.calls


def test_foreign_instance_is_rejected_without_writes(db, save) -> None:
    foreign = _add_save(db, "intruder050", "Foreign")
    instance = _import_player(db, foreign, "FOREIGN050")
    before = db.query(PlayerInstance).count()
    with pytest.raises(llm_planner.PlannerError, match="当前存档之外"):
        llm_planner.execute_plan(db, save.id, [("player_profile", {"instance_id": instance.id})])
    db.expire_all()
    assert db.query(PlayerInstance).count() == before


def test_foreign_transfer_is_rejected(db, save) -> None:
    foreign = _add_save(db, "intruder050b", "Foreign B")
    instance = _import_player(db, foreign, "FOREIGN050B")
    transfer = Transfer(
        fm_save_id=foreign.id,
        source_record_id="T-FOREIGN-050",
        player_instance_id=instance.id,
        player_name="FOREIGN050B",
        transfer_type="permanent",
        status="completed",
        transfer_date=date(2026, 7, 1),
        currency="EUR",
        effective_fee=1_000_000,
        source="manual",
    )
    db.add(transfer)
    db.commit()
    with pytest.raises(llm_planner.PlannerError, match="当前存档之外"):
        llm_planner.execute_plan(db, save.id, [("transfer_roi", {"transfer_id": transfer.id})])


def test_model_cannot_set_save_id(db, save) -> None:
    spec = llm_planner.TOOL_SPECS["player_profile"]
    with pytest.raises(llm_planner.PlannerError, match="受限参数"):
        llm_planner._validate_arguments(spec, {"instance_id": 1, "save_id": save.id})


def test_forged_plan_from_llm_is_rejected_before_execution(db, save) -> None:
    foreign = _add_save(db, "intruder050c", "Foreign C")
    instance = _import_player(db, foreign, "FOREIGN050C")
    payload = {"tool_calls": [{"tool": "player_profile", "arguments": {"instance_id": instance.id}}]}
    plan = llm_planner.parse_plan(payload)
    with pytest.raises(llm_planner.PlannerError, match="当前存档之外"):
        llm_planner.execute_plan(db, save.id, plan)
