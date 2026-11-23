"""SM-122：脱敏导出必须去掉身份信息与主机地址，同时保留状态与计数。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

# scripts/ lives at the repository root, one level above backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.export_unresolved_redacted import export_redacted  # noqa: E402

from app.db import build_engine  # noqa: E402
from app.ingestion.importer import ScanImporter  # noqa: E402
from app.ingestion.protocol import ScanPayload  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    FmSave,
    IdentityMatch,
    PlayerInstance,
    UnresolvedPlayerCandidate,
    User,
)
from tests.helpers import player_row, scan_document  # noqa: E402
from tests.test_unresolved_persistence import unresolved_row  # noqa: E402

ADDRESS = "0x7ffe1234"
PID_TEXT = "pid=4321"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_database(path: Path) -> None:
    engine = build_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        user = User(username="local", display_name="本地用户")
        session.add(user)
        session.commit()
        save = FmSave(user_id=user.id, name="Private Save Name", game_version="27.1", is_active=True)
        session.add(save)
        session.commit()
        document = scan_document(
            scan_id="redact-scan",
            players=[
                player_row("R1", "Known Player"),
                unresolved_row(
                    "Sensitive Player",
                    ca=120,
                    pa=140,
                    evidence={
                        "source": "fmsuperscout_dump",
                        "row_index": 7,
                        "debug_pointer": ADDRESS,
                        "process": PID_TEXT,
                    },
                ),
                unresolved_row("Another Sensitive", ca=100, pa=120),
            ],
        )
        ScanImporter(session, raw_dir=path.parent / "raw").import_payload(
            save.id, ScanPayload.model_validate(document)
        )
        session.commit()
    finally:
        session.close()
        engine.dispose()


def test_redacted_export_removes_identity_and_host_details(tmp_path: Path) -> None:
    database = tmp_path / "redact.db"
    _build_database(database)
    before = _sha256(database)

    output = tmp_path / "out" / "unresolved-redacted.json"
    document = export_redacted(database, output)

    assert output.exists()
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert payload["schema"] == "scoutmind.unresolved.redacted.v1"
    assert payload["totals"]["candidates"] == 2
    assert payload["totals"]["observations"] == 2
    assert payload["totals"]["by_uid_status"] == {"sentinel": 2}
    assert payload["source"]["database"] == "[redacted-path]"

    for forbidden in ("Sensitive Player", "Another Sensitive", "Private Save Name", ADDRESS, PID_TEXT):
        assert forbidden not in text, f"导出中不应出现 {forbidden!r}"
    assert str(tmp_path) not in text, "不应包含本机路径"
    assert not re.search(r"0x[0-9a-fA-F]{4,}", text), "不应包含内存地址"

    candidate = payload["candidates"][0]
    assert candidate["display_name"] == "[name withheld]"
    assert candidate["identity"]["uid_status"] == "sentinel"
    assert "scan_id" in candidate["evidence_types"]
    assert "identity.source" in candidate["evidence_types"]
    assert "suggestions" in candidate["evidence_types"]
    assert candidate["birth_year"] == 2003

    observation = payload["observations"][0]
    assert observation["uid_status"] == "sentinel"
    assert observation["has_club"] in {True, False}

    assert payload["imports"][0]["status"] == "succeeded"
    assert payload["imports"][0]["rejected_codes"] == []
    assert all("save_id" not in save for save in payload["saves"])
    assert payload["saves"][0]["save_alias"] == "save-1"

    # The source database is opened read-only and left untouched.
    assert _sha256(database) == before


def test_include_names_is_explicit_and_local_only(tmp_path: Path) -> None:
    database = tmp_path / "names.db"
    _build_database(database)
    document = export_redacted(database, tmp_path / "named.json", include_names=True)
    assert document["candidates"][0]["display_name"] == "Sensitive Player"
    assert "Sensitive Player" in (tmp_path / "named.json").read_text(encoding="utf-8")


def test_missing_database_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        export_redacted(tmp_path / "absent.db", tmp_path / "out.json")


def test_export_keeps_status_but_not_raw_evidence_values(tmp_path: Path) -> None:
    database = tmp_path / "status.db"
    _build_database(database)

    engine = build_engine(f"sqlite:///{database.as_posix()}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        candidate = session.scalar(select(UnresolvedPlayerCandidate).limit(1))
        instance = session.scalar(select(PlayerInstance).limit(1))
        assert candidate is not None and instance is not None
        candidate.status = "resolved"
        candidate.resolution_method = "manual_attached"
        candidate.resolved_player_id = instance.player_id
        candidate.resolved_player_instance_id = instance.id
        candidate.resolved_at = datetime(2026, 11, 23, 12, 0, 0)
        session.add(
            IdentityMatch(
                player_id=instance.player_id,
                fm_save_id=candidate.fm_save_id,
                strategy="unresolved_manual_link",
                confidence=1.0,
                evidence_json="{}",
            )
        )
        session.commit()
    finally:
        session.close()
        engine.dispose()

    document = export_redacted(database, tmp_path / "status.json")
    statuses = {item["status"] for item in document["candidates"]}
    assert "resolved" in statuses
    assert document["totals"]["by_status"].get("resolved", 0) >= 1
