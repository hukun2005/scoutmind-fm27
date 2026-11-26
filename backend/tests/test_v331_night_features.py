"""V3.3.1 夜间交付：AI 球探助手球员卡片、会话清空与引援推荐等级。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents import service as agent_service
from app.analytics.recruitment import GRADE_RULES, search_recruitment
from app.models import PlayerInstance
from tests.helpers import import_document, player_row, scan_document


def _seed(db, save) -> None:
    squad = [
        player_row("K1", "Keeper One", position="GK", ca=140, pa=150, age=27),
        player_row("D1", "Defender One", position="DC", ca=142, pa=150, age=29),
        player_row("M1", "Midfielder One", position="MC", ca=145, pa=160, age=25),
        player_row("F1", "Forward One", position="ST", ca=150, pa=172, age=21, attributes={"finishing": 17}),
    ]
    market = [
        player_row(
            f"X{index}",
            f"Market Forward {index}",
            position="ST",
            ca=140 + index,
            pa=165,
            age=19 + index,
            value=12_000_000 + index * 1_000_000,
            club_uid="C2",
            attributes={"finishing": 16, "pace": 15},
        )
        for index in range(6)
    ]
    import_document(db, scan_document(players=squad + market))


def test_scout_answer_exposes_only_real_player_cards(db, save) -> None:
    """球员卡片必须来自工具真实返回的 instance_id，且能对应到本存档实例。"""
    _seed(db, save)
    answer, _calls = agent_service.answer_question(db, save.id, "帮我寻找年轻前锋。")

    cards = answer["player_cards"]
    assert isinstance(cards, list)
    assert 1 <= len(cards) <= 8
    known = {
        instance.id: instance.player.full_name
        for instance in db.query(PlayerInstance).filter(PlayerInstance.fm_save_id == save.id).all()
    }
    for card in cards:
        assert card["instance_id"] in known, "卡片必须是本存档真实球员实例"
        assert card["name"] == known[card["instance_id"]], "卡片姓名必须来自数据库，不按输入猜测"


def test_deleting_conversation_removes_messages(client: TestClient, db, save) -> None:
    """清空对话会删除会话与消息，但保留已经保存的报告。"""
    _seed(db, save)
    created = client.post("/api/v1/agent/conversations", json={"title": "待清空"})
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]

    asked = client.post(
        f"/api/v1/agent/conversations/{conversation_id}/messages",
        json={"question": "哪个位置最需要补强？"},
    )
    assert asked.status_code == 201, asked.text
    assert client.get(f"/api/v1/agent/conversations/{conversation_id}/messages").json()["total"] == 2

    removed = client.delete(f"/api/v1/agent/conversations/{conversation_id}")
    assert removed.status_code == 204, removed.text
    assert client.get(f"/api/v1/agent/conversations/{conversation_id}/messages").status_code == 404

    reports = client.get("/api/v1/agent/reports").json()
    assert reports["total"] >= 1
    assert all(item["conversation_id"] is None for item in reports["items"])


def test_recruitment_grade_has_explicit_coverage_rule(db, save) -> None:
    """每个候选都有等级与覆盖度；覆盖不足时不得给出推荐等级。"""
    _seed(db, save)
    result = search_recruitment(db, save.id, slot="ST", limit=10, exclude_own_club=False)

    assert result["grade_rules"] == GRADE_RULES
    assert result["items"], "合成数据应至少命中一名前锋"
    for item in result["items"]:
        assert item["grade"] in {"S", "A", "B", "C", "D", "insufficient"}
        assert 0 <= float(item["score_coverage"]) <= 1
        if float(item["score_coverage"]) < 0.6:
            assert item["grade"] == "insufficient"
        if item["score"] is None:
            assert item["grade"] == "insufficient"
