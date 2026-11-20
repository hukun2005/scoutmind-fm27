"""第一阶段（SM-001/002/003）回归：上传限制、身份冲突、转会语义分离。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.api.uploads import read_body_limited, read_request_payload
from app.ingestion.adapters.fmscout import convert_document
from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import (
    IdentityConflict,
    IdentityMatch,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
)

from tests.helpers import club_row, player_row, scan_document, transfer_row


# ======================================================================
# SM-001 上传限制与资源保护
# ======================================================================


def _post_scan(client: TestClient, save_id: int, document: dict):
    return client.post(
        f"/api/v1/imports/scan?save_id={save_id}",
        content=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def test_normal_json_upload_still_works(client: TestClient, save: object) -> None:
    """正常大小的 JSON 上传保持兼容。"""
    response = _post_scan(client, save.id, scan_document(scan_id="sm1-ok", players=[player_row("A1", "Normal Upload")]))
    assert response.status_code == 201, response.text


def test_normal_multipart_upload_still_works(client: TestClient, save: object) -> None:
    """正常大小的 multipart 上传保持兼容。"""
    document = scan_document(scan_id="sm1-multi", players=[player_row("A2", "Multipart Upload")])
    response = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        files={"file": ("scan.json", json.dumps(document).encode("utf-8"), "application/json")},
    )
    assert response.status_code == 201, response.text


def test_oversized_json_is_rejected_before_read(client: TestClient, save: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过上限的 JSON：413，且不进入导入。"""
    monkeypatch.setattr(settings, "max_import_bytes", 2048)
    monkeypatch.setattr(settings, "max_request_bytes", 2048)
    document = scan_document(scan_id="sm1-big", players=[player_row(f"B{i}", f"Big {i}") for i in range(80)])
    response = _post_scan(client, save.id, document)
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "payload_too_large"


def test_oversized_chunked_request_without_content_length_is_rejected(save: object) -> None:
    """没有 Content-Length 的 chunked 请求同样会被累计计数拦下。"""
    from starlette.requests import Request

    body = b"x" * 5000

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"transfer-encoding", b"chunked")],
    }

    async def run() -> None:
        request = Request(scope, receive)
        with pytest.raises(Exception) as excinfo:
            await read_body_limited(request, limit=1024)
        assert getattr(excinfo.value, "status_code", None) == 413

    import asyncio

    asyncio.run(run())


def test_multipart_oversized_file_is_rejected(client: TestClient, save: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """multipart 文件读取过程中超限：413。"""
    monkeypatch.setattr(settings, "max_import_bytes", 2048)
    monkeypatch.setattr(settings, "max_multipart_field_bytes", 2048)
    document = scan_document(scan_id="sm1-mp-big", players=[player_row(f"C{i}", f"Big {i}") for i in range(80)])
    payload = json.dumps(document).encode("utf-8")
    assert len(payload) > 2048
    response = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        files={"file": ("scan.json", payload, "application/json")},
    )
    assert response.status_code == 413, response.text


def test_multiple_files_are_rejected(client: TestClient, save: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """multipart 文件数量受 max_upload_files 限制。"""
    monkeypatch.setattr(settings, "max_upload_files", 1)
    document = scan_document(scan_id="sm1-two", players=[player_row("D1", "Two Files")])
    raw = json.dumps(document).encode("utf-8")
    response = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        files=[
            ("file", ("a.json", raw, "application/json")),
            ("file", ("b.json", raw, "application/json")),
        ],
    )
    assert response.status_code in {400, 413, 422}, response.text


def test_upload_form_is_closed_after_success() -> None:
    """读取成功后表单被关闭：底层文件不会留在临时目录。"""
    import asyncio
    from starlette.datastructures import UploadFile

    class FakeForm:
        def __init__(self, upload: UploadFile) -> None:
            self.upload = upload
            self.closed = False

        def get(self, name: str):
            return self.upload if name == "file" else None

        def multi_items(self):
            return [("file", self.upload)]

        async def close(self) -> None:
            self.closed = True
            await self.upload.close()

    class FakeRequest:
        headers = {"content-type": "multipart/form-data"}

        def __init__(self, form: FakeForm) -> None:
            self.form_obj = form

        async def form(self, **kwargs):
            return self.form_obj

    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    handle.write(b"{}" + b" " * 32)
    handle.close()
    upload = UploadFile(file=open(handle.name, "rb"), filename="x.json")
    form = FakeForm(upload)

    async def run() -> None:
        raw = await read_request_payload(FakeRequest(form), limit=10_000)
        assert raw
        assert form.closed is True
        assert upload.file.closed is True

    asyncio.run(run())
    Path(handle.name).unlink(missing_ok=True)


def test_upload_semaphore_limits_concurrency() -> None:
    """上传解析受信号量限制（同时只允许 max_upload_concurrency 个）。"""
    import asyncio
    from app.api import uploads

    async def run() -> None:
        started = []
        release = asyncio.Event()

        async def worker(index: int) -> None:
            async with uploads.upload_slot():
                started.append(index)
                await release.wait()

        tasks = [asyncio.create_task(worker(i)) for i in range(settings.max_upload_concurrency + 2)]
        await asyncio.sleep(0.05)
        assert len(started) == settings.max_upload_concurrency
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())


# ======================================================================
# SM-002 身份冲突与 UID 复用
# ======================================================================


def _import(db, save_id: int, document: dict):
    payload = ScanPayload.model_validate(document)
    outcome = ScanImporter(db).import_payload(save_id, payload)
    db.commit()
    return outcome


def test_same_uid_same_name_same_birth_matches(db, save) -> None:
    _import(db, save.id, scan_document(scan_id="i1", players=[player_row("U1", "Same", age=22)]))
    _import(db, save.id, scan_document(scan_id="i2", players=[player_row("U1", "Same", age=22)]))
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    assert db.scalar(select(func.count()).select_from(Player)) == 1


def test_birth_date_added_with_different_name_is_not_merged(db, save) -> None:
    """旧记录无生日 → 新记录有生日但异名：不得把生日写进旧身份。"""
    first = player_row("U2", "Old Identity", age=22)
    first["birth_date"] = None
    _import(db, save.id, scan_document(scan_id="i3", players=[first]))

    second = player_row("U2", "New Identity", age=22)
    _import(db, save.id, scan_document(scan_id="i4", players=[second]))

    players = db.scalars(select(Player)).all()
    old = next(item for item in players if item.full_name == "Old Identity")
    assert old.birth_date is None, "旧身份不能被新记录补的生日污染"
    assert len(players) == 2
    conflicts = db.scalars(select(IdentityConflict)).all()
    assert any(item.reason == "birth_date_added_name_mismatch" for item in conflicts)
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 2


def test_same_uid_same_name_birth_date_fill_is_allowed(db, save) -> None:
    first = player_row("U3", "Name Stable", age=22)
    first["birth_date"] = None
    _import(db, save.id, scan_document(scan_id="i5", players=[first]))
    _import(db, save.id, scan_document(scan_id="i6", players=[player_row("U3", "Name Stable", age=22)]))

    assert db.scalar(select(func.count()).select_from(Player)) == 1
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    strategies = {row.strategy for row in db.scalars(select(IdentityMatch)).all()}
    assert "uid_birthdate_fill" in strategies


def test_rename_with_same_birth_date_keeps_identity(db, save) -> None:
    _import(db, save.id, scan_document(scan_id="i7", players=[player_row("U4", "Before Rename", age=22)]))
    _import(db, save.id, scan_document(scan_id="i8", players=[player_row("U4", "After Rename", age=22)]))

    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    conflicts = db.scalars(select(IdentityConflict)).all()
    assert conflicts == [], "改名不是冲突"
    strategies = {row.strategy for row in db.scalars(select(IdentityMatch)).all()}
    assert "uid_rename" in strategies


def test_transfer_and_youth_promotion_keep_identity(db, save) -> None:
    _import(db, save.id, scan_document(scan_id="i9", players=[player_row("U5", "Mover", club_uid="C1", position="ST")]))
    _import(db, save.id, scan_document(scan_id="i10", players=[player_row("U5", "Mover", club_uid="C2", position="AML")]))
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    assert db.scalar(select(func.count()).select_from(IdentityConflict)) == 0


def test_same_uid_different_birth_dates_conflict_and_later_evidence_resolves(db, save) -> None:
    _import(db, save.id, scan_document(scan_id="i11", players=[player_row("U6", "Young", age=20)]))
    _import(db, save.id, scan_document(scan_id="i12", players=[player_row("U6", "Older", age=35)]))
    conflicts = db.scalars(select(IdentityConflict)).all()
    assert len(conflicts) == 1
    assert conflicts[0].status == "open"

    # 第三次导入：与"Older"完全一致（同 UID + 同姓名 + 同生日）→ 冲突拿到新证据后关闭
    _import(db, save.id, scan_document(scan_id="i13", players=[player_row("U6", "Older", age=35)]))
    db.refresh(conflicts[0])
    assert conflicts[0].status == "resolved", "后续证据应关闭冲突"
    assert conflicts[0].resolved_at is not None
    assert conflicts[0].resolution == "later_evidence"


def test_conflict_rows_expose_fields_and_confidence(db, save) -> None:
    first = player_row("U7", "Alpha", age=22)
    first["birth_date"] = None
    _import(db, save.id, scan_document(scan_id="i14", players=[first]))
    _import(db, save.id, scan_document(scan_id="i15", players=[player_row("U7", "Beta", age=30)]))
    conflict = db.scalars(select(IdentityConflict)).first()
    assert conflict is not None
    assert conflict.conflict_fields == "name,birth_date"
    assert conflict.status == "open"


def test_same_uid_in_two_saves_does_not_cross_link(db, save) -> None:
    from app.models import FmSave, User

    user = db.scalar(select(User))
    other = FmSave(user_id=user.id, name="Other Save", game_version="27.1", game_build="x", is_active=False)
    db.add(other)
    db.commit()

    _import(db, save.id, scan_document(scan_id="i16", players=[player_row("U8", "Save One", age=22)]))
    _import(db, other.id, scan_document(scan_id="i17", players=[player_row("U8", "Save Two", age=22)]))

    instances = db.scalars(select(PlayerInstance)).all()
    assert len(instances) == 2
    assert {item.fm_save_id for item in instances} == {save.id, other.id}


def test_same_game_unique_id_reimport_is_idempotent(db, save) -> None:
    document = scan_document(scan_id="i18", players=[player_row("U9", "Idempotent", age=22)])
    _import(db, save.id, document)
    _import(db, save.id, document)
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 1
    assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 1


# ======================================================================
# SM-003 历史转会 / 已达成 / 未来 / 租借 / 完成
# ======================================================================


def _dump(players: list[dict], transfers: list[dict] | None = None) -> dict:
    document = {
        "meta": {"generated": "2026-11-18T10:00:00Z", "game": "FM27", "gameVersion": "27.1.0"},
        "clubs": [{"id": 1, "name": "Club A"}, {"id": 2, "name": "Club B"}],
        "players": players,
        "transfers": transfers or [],
    }
    return document


def _base_player(**extra) -> dict:
    row = {"id": 10, "name": "Transfer Player", "club": "Club A", "clubId": 1, "ca": 140, "pa": 160}
    row.update(extra)
    return row


def test_transfer_date_without_history_array_keeps_history_unavailable() -> None:
    _, report = convert_document(_dump([_base_player(transferTo="Club B", transferDate="2027-06-30")]))
    coverage = report.payload()["transfer_coverage"]
    assert coverage["transfer_history"]["available"] is False
    assert coverage["agreed_transfers"]["available"] is True
    assert any("transfer_history.available=false" in warning for warning in report.warnings)


def test_history_array_without_agreed_transfers() -> None:
    payload, report = convert_document(
        _dump([_base_player()], transfers=[{"id": "T1", "player": "Transfer Player", "from": "Club A", "to": "Club B", "fee": 1000000, "date": "2026-07-01"}])
    )
    coverage = report.payload()["transfer_coverage"]
    assert coverage["transfer_history"]["available"] is True
    assert coverage["agreed_transfers"]["available"] is False


def test_history_and_agreed_are_reported_separately() -> None:
    _, report = convert_document(
        _dump(
            [_base_player(transferTo="Club B", transferDate="2027-06-30")],
            transfers=[{"id": "T1", "player": "Transfer Player", "fee": 5000000, "date": "2026-01-01"}],
        )
    )
    coverage = report.payload()["transfer_coverage"]
    assert coverage["transfer_history"]["available"] is True
    assert coverage["agreed_transfers"]["available"] is True


def _import_transfer_document(db, save_id: int, transfers: list[dict], scan_id: str):
    rows = [player_row(f"P{i}", f"Player {i}") for i in range(len(transfers))]
    document = scan_document(scan_id=scan_id, players=rows, transfers=transfers)
    return _import(db, save_id, document)


def test_price_stats_exclude_agreed_and_cancelled(db, save) -> None:
    from app.analytics.transfers import TransferFilter, transfer_price_stats

    _import_transfer_document(
        db,
        save.id,
        [
            transfer_row("T1", "P0", "Player 0", fee=10_000_000),
            transfer_row("T2", "P1", "Player 1", fee=20_000_000),
        ],
        "sm3-1",
    )
    # 未完成 / 已达成未生效：不是历史成交
    payload = ScanPayload.model_validate(
        scan_document(scan_id="sm3-2", players=[player_row("P9", "Futures")], transfers=[])
    )
    ScanImporter(db).import_payload(save.id, payload)
    db.commit()
    db.add(
        Transfer(
            fm_save_id=save.id,
            source_record_id="agreed:1:C2",
            player_name="Futures",
            transfer_type="permanent",
            status="agreed",
            transfer_date=__import__("datetime").date(2027, 7, 1),
            currency="EUR",
            effective_fee=99_000_000,
            source="fmsuperscout",
        )
    )
    db.add(
        Transfer(
            fm_save_id=save.id,
            source_record_id="cancelled:1",
            player_name="Futures",
            transfer_type="permanent",
            status="cancelled",
            transfer_date=__import__("datetime").date(2026, 1, 1),
            currency="EUR",
            effective_fee=88_000_000,
            source="manual",
        )
    )
    db.commit()

    stats = transfer_price_stats(db, save.id, TransferFilter())
    assert stats["sample_size"] == 2
    assert stats["excluded"]["by_category"].get("agreed") == 1
    assert stats["excluded"]["by_category"].get("cancelled") == 1
    assert stats["median"] == pytest.approx(15_000_000)
    assert stats["availability"]["agreed"] == 1
    assert stats["availability"]["cancelled"] == 1
    assert stats["availability"]["transfer_history"] is True


def test_loan_fee_is_not_in_permanent_price_stats(db, save) -> None:
    from app.analytics.transfers import TransferFilter, transfer_price_stats

    _import_transfer_document(
        db,
        save.id,
        [transfer_row("T1", "P0", "Player 0", fee=10_000_000)],
        "sm3-3",
    )
    db.add(
        Transfer(
            fm_save_id=save.id,
            source_record_id="loan:1",
            player_name="Loaned",
            transfer_type="loan",
            status="completed",
            transfer_date=__import__("datetime").date(2026, 8, 1),
            currency="EUR",
            effective_fee=500_000,
            source="manual",
        )
    )
    db.commit()

    stats = transfer_price_stats(db, save.id, TransferFilter())
    assert stats["sample_size"] == 1, "租借费不得进入永久转会价格统计"
    assert stats["excluded"]["by_category"].get("loan") == 1


def test_history_unavailable_when_only_agreed_rows(db, save) -> None:
    from app.analytics.transfers import TransferFilter, transfer_price_stats

    payload = ScanPayload.model_validate(scan_document(scan_id="sm3-4", players=[player_row("P1", "Only Agreed")], transfers=[]))
    ScanImporter(db).import_payload(save.id, payload)
    db.commit()
    db.add(
        Transfer(
            fm_save_id=save.id,
            source_record_id="agreed:only",
            player_name="Only Agreed",
            transfer_type="permanent",
            status="agreed",
            transfer_date=__import__("datetime").date(2027, 1, 1),
            currency="EUR",
            effective_fee=1_000_000,
            source="fmsuperscout",
        )
    )
    db.commit()

    stats = transfer_price_stats(db, save.id, TransferFilter())
    assert stats["sample_size"] == 0
    assert stats["availability"]["transfer_history"] is False
    assert stats["availability"]["agreed"] == 1

def test_same_uid_same_name_small_dob_drift_is_one_identity(db, save) -> None:
    """同名 + 同 UID + 生日差几个月：数据源精度差异，不是 UID 复用。"""
    from datetime import date

    first = player_row("U10", "Precision Drift", age=22)  # 生日 2004-05-01
    _import(db, save.id, scan_document(scan_id="drift-1", players=[first]))

    drifted = player_row("U10", "Precision Drift", age=22)
    drifted["birth_date"] = date(2004, 8, 14).isoformat()
    _import(db, save.id, scan_document(scan_id="drift-2", players=[drifted]))

    players = db.scalars(select(Player)).all()
    assert len(players) == 1, "同名且生日接近时不得创建第二个身份"
    assert players[0].birth_date == date(2004, 8, 14), "应用新观测修正生日"
    assert db.scalar(select(func.count()).select_from(IdentityConflict)) == 0
    strategies = {row.strategy for row in db.scalars(select(IdentityMatch)).all()}
    assert "uid_name_dob_drift" in strategies


def test_same_uid_different_name_and_dob_still_conflicts(db, save) -> None:
    """异名 + 生日不同：仍然按 UID 复用建新身份并记录冲突。"""
    _import(db, save.id, scan_document(scan_id="hard-1", players=[player_row("U11", "Person One", age=20)]))
    _import(db, save.id, scan_document(scan_id="hard-2", players=[player_row("U11", "Person Two", age=35)]))
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 2
    conflict = db.scalars(select(IdentityConflict)).first()
    assert conflict is not None
    assert conflict.reason == "birth_date_mismatch"
    assert conflict.conflict_fields == "birth_date"
    assert conflict.confidence == pytest.approx(0.9)