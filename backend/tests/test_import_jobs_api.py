"""SM-126B（后端部分）：导入任务查询、失败证据与重启恢复。"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.importer import recover_interrupted_imports
from app.main import create_app
from app.models import ImportJob, ImportRow
from tests.helpers import import_document, player_row, scan_document

PREFIX = "/api/v1"


def _seed(db: Session, save) -> None:
    import_document(db, scan_document(scan_id="jobs-scan-1", players=[player_row("J1", "Job Player")]))


def test_list_filters_by_scan_id_and_status(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    by_scan = client.get(f"{PREFIX}/imports", params={"scan_id": "jobs-scan-1"})
    assert by_scan.status_code == 200
    body = by_scan.json()
    assert body["total"] == 1
    assert body["items"][0]["scan_id"] == "jobs-scan-1"
    assert body["items"][0]["status"] == "succeeded"

    missing = client.get(f"{PREFIX}/imports", params={"scan_id": "no-such-scan"})
    assert missing.json()["total"] == 0

    succeeded = client.get(f"{PREFIX}/imports", params={"status": "succeeded"})
    assert succeeded.json()["total"] == 1
    failed = client.get(f"{PREFIX}/imports", params={"status": "failed"})
    assert failed.json()["total"] == 0


def test_detail_reports_rejected_rows_and_status(client: TestClient, db: Session, save) -> None:
    _seed(db, save)
    # A rejected row makes the job partial and leaves evidence in import_rows.
    import_document(
        db,
        scan_document(
            scan_id="jobs-scan-2",
            players=[player_row("J2", "Fine"), {"name": "No Identity"}],
        ),
    )
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "jobs-scan-2"))
    assert job is not None
    response = client.get(f"{PREFIX}/imports/{job.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["rejected_rows"] == 1
    assert body["rejected_codes"][0]["code"] == "missing_uid"
    assert body["retryable"] is True


def test_detail_of_same_user_other_save_and_foreign_save(client: TestClient, db: Session, save) -> None:
    from app.models import FmSave, User

    own = FmSave(user_id=save.user_id, name="同一用户的另一个存档", is_active=False)
    stranger = User(username="stranger", display_name="Stranger")
    db.add_all([own, stranger])
    db.commit()
    foreign_save = FmSave(user_id=stranger.id, name="别人的存档", is_active=False)
    db.add(foreign_save)
    db.commit()
    own_job = ImportJob(
        fm_save_id=own.id, scan_id="own-other-save", source="fm27_live_reader",
        schema_version="1.1", status="succeeded", received_at=datetime.utcnow(),
    )
    foreign_job = ImportJob(
        fm_save_id=foreign_save.id, scan_id="foreign-scan", source="fm27_live_reader",
        schema_version="1.1", status="succeeded", received_at=datetime.utcnow(),
    )
    db.add_all([own_job, foreign_job])
    db.commit()

    # 同一用户的另一个存档：按 save_id 查询是合法的（多存档）。
    listed = client.get(f"{PREFIX}/imports", params={"save_id": own.id})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert client.get(f"{PREFIX}/imports/{own_job.id}").status_code == 200

    # 别人的存档：404，不能泄露任务是否存在。
    denied = client.get(f"{PREFIX}/imports", params={"save_id": foreign_save.id})
    assert denied.status_code == 404
    assert client.get(f"{PREFIX}/imports/{foreign_job.id}").status_code == 404


def test_recovery_marks_running_jobs_failed_with_evidence(db: Session, save) -> None:
    db.add(
        ImportJob(
            fm_save_id=save.id,
            scan_id="interrupted-scan",
            source="fm27_live_reader",
            schema_version="1.1",
            status="running",
            received_at=datetime.utcnow() - timedelta(minutes=30),
        )
    )
    db.commit()

    from app.db import SessionLocal

    recovered = recover_interrupted_imports(SessionLocal)
    assert recovered >= 1
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "interrupted-scan"))
    assert job is not None
    assert job.status == "failed"
    assert job.finished_at is not None
    rows = list(db.scalars(select(ImportRow).where(ImportRow.import_job_id == job.id)))
    assert [row.code for row in rows] == ["interrupted"]


def test_upload_while_same_scan_is_running_returns_409(client: TestClient, db: Session, save) -> None:
    """A live import must not be restarted by a duplicate upload; the Agent treats 409 as "still running"."""
    import json as jsonlib

    db.add(
        ImportJob(
            fm_save_id=save.id,
            scan_id="busy-scan",
            source="fm27_live_reader",
            schema_version="1.1",
            status="running",
            received_at=datetime.utcnow(),
        )
    )
    db.commit()
    document = scan_document(scan_id="busy-scan", players=[player_row("B1", "Busy")])
    response = client.post(
        f"{PREFIX}/imports/scan",
        content=jsonlib.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "import_in_progress"
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "busy-scan"))
    assert job is not None
    assert job.status == "running", "重复上传不得改写正在进行的任务"


def test_startup_recovers_stale_running_job(db: Session, save) -> None:
    db.add(
        ImportJob(
            fm_save_id=save.id,
            scan_id="startup-partial",
            source="fm27_live_reader",
            schema_version="1.1",
            status="running",
            received_at=datetime.utcnow(),
        )
    )
    db.commit()

    app = create_app()
    with TestClient(app):
        pass

    db.expire_all()
    job = db.scalar(select(ImportJob).where(ImportJob.scan_id == "startup-partial"))
    assert job is not None
    assert job.status == "failed"
    assert db.scalar(
        select(func.count()).select_from(ImportRow).where(ImportRow.import_job_id == job.id)
    ) == 1
