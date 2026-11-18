"""真实数据回归测试（P0-3）。

两类用例：

* **构造用例**：按真实 dump 的结构构造两份快照，覆盖规格要求的 8 条回归；不依赖真实数据，任何机器都能跑。
* **真实样本用例**：读取 `tests/fixtures/fmsuperscout/` 里脱敏后的真实导出。目录为空时跳过，并在跳过原因里说明
  需要把真实导出放进来。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ingestion.adapters import fmscout
from app.models import (
    Club,
    LoanRecord,
    PlayerAvailability,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
    TransferCandidate,
)

from .helpers import ensure_save

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fmsuperscout"


def dump(
    players: list[dict],
    *,
    generated: str = "2027-03-01T18:30:00+00:00",
    game_date: str = "2027-03-01",
    game: str = "FM27",
    my_club: str = "Northbridge United",
) -> bytes:
    """Build a dump in the shape FMSuperScout writes."""
    return json.dumps(
        {
            "meta": {"generated": generated, "game": game, "gameDate": game_date, "myClub": my_club},
            "players": players,
            "staff": [],
        },
        ensure_ascii=False,
    ).encode("utf-8")


def player(
    uid: int,
    name: str,
    *,
    ca: int = 140,
    pa: int = 160,
    club: str | None = "Northbridge United",
    age: int = 23,
    **extra: object,
) -> dict:
    """A minimal but realistic player row, with optional overrides."""
    row = {
        "id": uid,
        "name": name,
        "birthYear": 2027 - age,
        "birthDoy": 60,
        "age": age,
        "ca": ca,
        "pa": pa,
        "value": 20_000_000,
        "wage": 40_000,
        "expires": "2029-06-30",
        "club": club,
        "clubRep": 7400,
        "div": "Premier Division",
        "nat": "England",
        "posArr": ["MC"],
        "worldRep": 4000,
        "attrs": {"Passing": 15, "Tackling": 12, "Vision": 14},
    }
    row.update(extra)
    return row


def post_dump(client: TestClient, raw: bytes, *, save_id: int | None = None):
    """Import a dump through the adapter endpoint."""
    query = f"?save_id={save_id}" if save_id else ""
    return client.post(
        f"/api/v1/imports/fmscout{query}",
        content=raw,
        headers={"content-type": "application/json"},
    )


# ---------------------------------------------------------------- 1. 幂等


def test_same_dump_twice_creates_no_duplicate_rows(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    raw = dump([player(1, "Adam Wharton"), player(2, "Diego Silva")])

    assert post_dump(client, raw, save_id=save_id).status_code == 201
    second = post_dump(client, raw, save_id=save_id)
    assert second.status_code == 201
    assert second.json()["import"]["duplicate"] is True

    assert db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save_id).count() == 2
    assert db.query(PlayerSnapshot).count() == 2
    assert db.query(PlayerAvailability).count() == 2


# ---------------------------------------------------------------- 2. 两次扫描形成历史


def test_ca_change_between_scans_appends_a_second_snapshot(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Adam Wharton", ca=140)]), save_id=save_id)
    post_dump(
        client,
        dump(
            [player(1, "Adam Wharton", ca=148)],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )

    snaps = db.scalars(
        select(PlayerSnapshot).order_by(PlayerSnapshot.observed_at)
    ).all()
    assert [snap.ca for snap in snaps] == [140, 148]
    assert db.query(PlayerInstance).count() == 1
    assert db.query(PlayerSnapshot).count() == 2


# ---------------------------------------------------------------- 3. 挂牌状态变化


def test_listing_change_is_recorded_over_time(client: TestClient, db) -> None:
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

    rows = db.scalars(
        select(PlayerAvailability).order_by(PlayerAvailability.observed_at)
    ).all()
    assert [row.listed for row in rows] == [False, True]


def test_missing_listing_stays_null(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Adam Wharton")]), save_id=save_id)
    row = db.scalars(select(PlayerAvailability)).one()
    assert row.listed is None
    assert row.injured is None
    assert row.injury_start_date is None


# ---------------------------------------------------------------- 4. 租借不能变成自由球员


def test_loan_out_keeps_owner_and_is_not_a_free_agent(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    raw = dump(
        [
            player(
                1,
                "Loaned Kid",
                club="Kingsport City",
                ownerClub="Northbridge United",
                ownerTeamType="Senior",
            )
        ]
    )
    post_dump(client, raw, save_id=save_id)

    instance = db.scalars(select(PlayerInstance)).one()
    club = db.get(Club, instance.club_id)
    assert club is not None and club.name == "Kingsport City"

    loan = db.scalars(select(LoanRecord)).one()
    assert db.get(Club, loan.parent_club_id).name == "Northbridge United"
    assert db.get(Club, loan.loan_club_id).name == "Kingsport City"
    # The dump has no clause information: it must stay unknown, not "no option".
    assert loan.has_option is None
    assert loan.has_obligation is None

    availability = db.scalars(select(PlayerAvailability)).one()
    assert db.get(Club, availability.parent_club_id).name == "Northbridge United"


# ---------------------------------------------------------------- 5. 转会后身份复用


def test_transfer_reuses_identity_instead_of_creating_a_player(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    post_dump(client, dump([player(1, "Moving Man", club="Northbridge United")]), save_id=save_id)
    first_instance = db.scalars(select(PlayerInstance)).one()

    post_dump(
        client,
        dump(
            [player(1, "Moving Man", club="Kingsport City")],
            generated="2027-06-01T18:30:00+00:00",
            game_date="2027-06-01",
        ),
        save_id=save_id,
    )

    instances = db.scalars(select(PlayerInstance)).all()
    assert len(instances) == 1
    assert instances[0].id == first_instance.id
    assert len({snap.player_instance_id for snap in db.scalars(select(PlayerSnapshot))}) == 1


def test_club_change_becomes_a_candidate_not_a_transfer(client: TestClient, db) -> None:
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

    candidate = db.scalars(select(TransferCandidate)).one()
    assert candidate.status == "candidate"
    assert db.get(Club, candidate.to_club_id).name == "Kingsport City"
    # A snapshot diff never fabricates a completed transfer.
    assert db.query(Transfer).count() == 0


# ---------------------------------------------------------------- 6. 缺失值保持 NULL


def test_missing_values_stay_null_not_zero(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    raw = dump(
        [
            player(
                1,
                "No Data",
                ca=0,
                pa=0,
                value=0xFFFFFFFF,
                wage=0xFFFFFFFF,
                attrs={},
                expires=None,
            )
        ]
    )
    post_dump(client, raw, save_id=save_id)

    snap = db.scalars(select(PlayerSnapshot)).one()
    assert snap.ca is None
    assert snap.pa is None
    assert snap.market_value is None
    assert snap.wage is None
    assert snap.contract_end is None


# ---------------------------------------------------------------- 7. 上游新增字段


def test_unknown_upstream_field_is_reported(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    raw = dump([player(1, "Future Field", brandNewAttribute=7)])
    response = post_dump(client, raw, save_id=save_id)

    report = response.json()["report"]
    assert "brandNewAttribute" in report["unknown_fields"]
    assert any("新增" in warning for warning in report["warnings"])


def test_known_but_ignored_field_is_not_reported_as_unknown(client: TestClient) -> None:
    """A field we deliberately ignore (hidden personality) must not look like an upstream change."""
    payload, report = fmscout.convert_dump(dump([player(1, "X", professionalism=14)]))
    assert report.unknown_fields == []
    assert any(item["field"] == "professionalism" for item in report.payload()["ignored_fields"])


# ---------------------------------------------------------------- 8. 上游版本变化


def test_unsupported_game_version_is_flagged(client: TestClient, db) -> None:
    save_id = ensure_save(db)
    response = post_dump(client, dump([player(1, "X")], game="FM31"), save_id=save_id)

    report = response.json()["report"]
    assert report["compatibility"]["supported"] is False
    assert any("FM31" in warning for warning in report["warnings"])
    # The import still happens: a version mismatch is a risk to review, not a silent failure.
    assert response.json()["import"]["players_created"] == 1


# ---------------------------------------------------------------- 真实样本


def real_samples() -> list[tuple[Path, dict]]:
    """Load sanitised real dumps listed in the fixture manifest."""
    manifest_path = FIXTURE_DIR / "manifest.json"
    if not manifest_path.exists():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples: list[tuple[Path, dict]] = []
    for entry in manifest.get("samples", []):
        path = FIXTURE_DIR / entry["file"]
        if path.exists():
            samples.append((path, entry))
    return samples


SAMPLES = real_samples()


@pytest.mark.skipif(not SAMPLES, reason="还没有真实 FMSuperScout 导出样本：把脱敏后的 dump 放进 tests/fixtures/fmsuperscout")
@pytest.mark.parametrize("path,entry", SAMPLES, ids=[sample[0].name for sample in SAMPLES])
def test_real_sample_converts_cleanly(path: Path, entry: dict, client: TestClient, db) -> None:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == entry["sha256"], f"{path.name} 与 manifest 记录的 sha256 不一致"

    payload, report = fmscout.convert_dump(raw)
    assert report.players_converted > 0
    assert report.unknown_fields == [], f"上游新增字段未处理：{report.unknown_fields}"
    assert not [club for club in payload["clubs"] if not club["name"]]

    uids = [row["save_local_uid"] for row in payload["players"]]
    assert len(uids) == len(set(uids)), "真实样本里出现重复球员 ID"

    save_id = ensure_save(db)
    first = post_dump(client, raw, save_id=save_id)
    second = post_dump(client, raw, save_id=save_id)
    assert first.status_code == 201, first.text
    assert second.json()["import"]["duplicate"] is True
    assert db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save_id).count() == len(uids)
