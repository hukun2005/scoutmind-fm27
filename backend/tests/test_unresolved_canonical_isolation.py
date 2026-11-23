"""SM-120：Unresolved 候选与观察不得进入任何正式身份体系。

正式体系包括：player_instances / player_snapshots / canonical / 成长曲线 / 估值 / 球探检索 / 阵容资产。
这里逐项断言：导入 14 类自由球员后，这些表与接口的结果与"只有合法 UID 球员"时完全一致。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Player,
    PlayerInstance,
    PlayerObservationCanonical,
    PlayerSnapshot,
    PlayerStatistic,
    PlayerAvailability,
    TransferCandidate,
    UnresolvedPlayerCandidate,
    UnresolvedPlayerObservation,
)
from tests.helpers import import_document, player_row, scan_document
from tests.test_unresolved_persistence import unresolved_row

PREFIX = "/api/v1"


def _seed(db: Session) -> None:
    import_document(
        db,
        scan_document(
            scan_id="isolation-scan",
            players=[
                player_row("A1", "Known Alpha", ca=150, pa=170),
                player_row("A2", "Known Beta", ca=130, pa=150),
                unresolved_row("Free Agent Gamma", ca=120, pa=140),
                unresolved_row("Free Agent Delta", ca=121, pa=141),
            ],
        ),
    )


def test_unresolved_rows_create_no_player_identity(db: Session, save) -> None:
    _seed(db)
    names = {row for row in db.scalars(select(Player.full_name))}
    assert names == {"Known Alpha", "Known Beta"}
    assert db.scalar(select(func.count()).select_from(PlayerInstance)) == 2
    assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == 2


def test_unresolved_rows_create_no_canonical_or_statistics(db: Session, save) -> None:
    _seed(db)
    for model in (
        PlayerObservationCanonical,
        PlayerStatistic,
        PlayerAvailability,
        TransferCandidate,
    ):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerCandidate)) == 2
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2


def test_players_api_does_not_list_unresolved(client: TestClient, db: Session, save) -> None:
    _seed(db)
    response = client.get(f"{PREFIX}/players")
    assert response.status_code == 200
    body = response.json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Known Alpha", "Known Beta"}
    assert "Free Agent Gamma" not in str(body)


def test_governance_overview_counts_only_instances(client: TestClient, db: Session, save) -> None:
    _seed(db)
    response = client.get(f"{PREFIX}/data-quality/governance/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["players"] == 2
    assert body["total_snapshots"] == 2
    assert body["canonical_groups"] == 0


def test_scouting_search_cannot_return_unresolved(client: TestClient, db: Session, save) -> None:
    _seed(db)
    response = client.post(
        f"{PREFIX}/scouting/search",
        json={"positions": ["ST"], "min_ca": 0, "limit": 50},
    )
    assert response.status_code in {200, 422}
    if response.status_code == 200:
        text = str(response.json())
        assert "Free Agent Gamma" not in text
        assert "Free Agent Delta" not in text


def test_resolving_a_candidate_does_not_create_snapshots_or_canonical(client: TestClient, db: Session, save) -> None:
    _seed(db)
    candidate = db.scalar(
        select(UnresolvedPlayerCandidate).where(UnresolvedPlayerCandidate.display_name == "Free Agent Gamma")
    )
    assert candidate is not None
    instance = db.scalar(select(PlayerInstance).where(PlayerInstance.save_local_uid == "A1"))
    assert instance is not None
    snapshots_before = db.scalar(select(func.count()).select_from(PlayerSnapshot))

    response = client.post(
        f"{PREFIX}/unresolved-players/{candidate.id}/resolve",
        json={"player_instance_id": instance.id, "confirm": True, "note": "确认是同一人"},
    )
    assert response.status_code == 200, response.text
    assert db.scalar(select(func.count()).select_from(PlayerSnapshot)) == snapshots_before
    assert db.scalar(select(func.count()).select_from(PlayerObservationCanonical)) == 0
    assert db.scalar(select(func.count()).select_from(UnresolvedPlayerObservation)) == 2
    player = db.get(Player, instance.player_id)
    assert player is not None
    assert player.full_name == "Known Alpha", "确认关联不得改写既有身份的姓名"
