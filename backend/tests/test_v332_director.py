"""V3.3.2 AI 足球总监：上下文、意图、真实数据规则、存档隔离与参数校验。"""

from __future__ import annotations

from app.ingestion.importer import ScanImporter
from app.ingestion.protocol import ScanPayload
from app.models import FmSave
from tests.helpers import RAW_DIR, import_document, player_row, scan_document


def _squad(db) -> dict:
    players = [
        player_row("P1", "Mario Bianchi", ca=150, pa=165, position="ST", age=22, club_uid="C1"),
        player_row("P2", "Luca Verdi", ca=120, pa=170, position="CM", age=19, club_uid="C1"),
        player_row("P3", "Old Keeper", ca=110, pa=110, position="GK", age=31, club_uid="C1", contract_end="2026-12-31"),
        player_row("P4", "Marco Neri", ca=95, pa=160, position="ST", age=20, club_uid="C1"),
    ]
    return import_document(db, scan_document(players=players))


def test_context_returns_club_and_data_gaps(client, db, save) -> None:
    _squad(db)
    body = client.get("/api/v1/agent/director/context", params={"save_id": save.id}).json()
    assert body["club"]["name"] == "Northbridge United"
    assert body["counts"]["players"] == 4
    assert body["data_updated_at"] is not None
    assert "没有转会记录" in " ".join(body["data_gaps"]) or body["counts"]["transfers"] == 0


def test_context_without_club_reports_gap(client, db, save) -> None:
    body = client.get("/api/v1/agent/director/context", params={"save_id": save.id}).json()
    assert body["club"] is None
    assert any("我的俱乐部" in gap for gap in body["data_gaps"])


def test_squad_gap_question_uses_real_depth(client, db, save) -> None:
    _squad(db)
    body = client.post("/api/v1/agent/director/ask", json={"question": "我的球队最需要补强什么位置？"}).json()
    assert body["intent"] == "gaps"
    assert body["mode"] == "deterministic-rules"
    gaps_section = next(section for section in body["sections"] if section["key"] == "gaps")
    assert gaps_section["table"]["rows"], "必须基于真实阵容返回补强优先级"
    assert body["conclusion"]
    assert all("instance_id" in item for item in body["recommendations"])


def test_development_question_requires_age_ca_pa(client, db, save) -> None:
    _squad(db)
    body = client.post("/api/v1/agent/director/ask", json={"question": "哪些球员值得重点培养？"}).json()
    assert body["intent"] == "development"
    names = {card["name"] for card in body["player_cards"]}
    assert "Luca Verdi" in names, "U23 且 PA>CA 的球员应进入培养候选"


def test_sell_question_finds_contract_risk(client, db, save) -> None:
    _squad(db)
    body = client.post("/api/v1/agent/director/ask", json={"question": "哪些球员可以考虑出售？"}).json()
    assert body["intent"] == "sell"
    assert any(item["name"] == "Old Keeper" for item in body["recommendations"]), "31 岁且合同将到期应进入候选"
    assert any("缺少出场时间" in gap or "不会自动修改" in gap for gap in body["data_gaps"]) or body["sections"]


def test_watchlist_question_reads_followed_players(client, db, save) -> None:
    _squad(db)
    players = client.get("/api/v1/players", params={"query": "Mario", "save_id": save.id}).json()
    client.post(
        "/api/v1/watchlist/items",
        json={"instance_id": players["items"][0]["instance_id"], "note": "重点观察", "status": "preparing"},
    )
    body = client.post("/api/v1/agent/director/ask", json={"question": "帮我分析当前关注名单"}).json()
    assert body["intent"] == "watchlist"
    assert body["recommendations"][0]["name"] == "Mario Bianchi"


def test_director_rejects_save_id_in_body(client, db, save) -> None:
    response = client.post("/api/v1/agent/director/ask", json={"question": "球队阵容如何", "save_id": 2})
    assert response.status_code == 422


def test_short_question_is_rejected(client, db, save) -> None:
    assert client.post("/api/v1/agent/director/ask", json={"question": "?"}).status_code == 422


def test_director_is_isolated_between_saves(client, db, save) -> None:
    _squad(db)
    other = FmSave(user_id=save.user_id, name="另一个存档", is_active=False)
    db.add(other)
    db.commit()
    document = scan_document(
        scan_id="other",
        players=[player_row("X1", "Other Player", club_uid="C9")],
        clubs=[
            {
                "uid": "C9",
                "name": "Other Club",
                "nation": "Spain",
                "league": "La Liga",
                "reputation": 5000,
                "is_user_club": True,
            }
        ],
    )
    ScanImporter(db, raw_dir=RAW_DIR).import_payload(other.id, ScanPayload.model_validate(document))
    db.commit()
    context = client.get("/api/v1/agent/director/context", params={"save_id": save.id}).json()
    assert context["counts"]["players"] == 4
    assert context["club"]["name"] == "Northbridge United"
