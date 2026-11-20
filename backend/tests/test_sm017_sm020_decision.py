"""SM-017 / SM-019 / SM-020 / SM-018：模拟器、成长预测、自动引援、AI 工具扩展。"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import llm_planner, service
from app.config import settings
from app.models import PlayerInstance, PlayerSnapshot
from app.utils import utcnow

from tests.helpers import player_row, scan_document


def _seed(client: TestClient, save, players: list[dict], scan_id: str = "v3-1") -> None:
    response = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        content=json.dumps(scan_document(scan_id=scan_id, players=players)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text


def _instance(db) -> PlayerInstance:
    return db.scalar(select(PlayerInstance).order_by(PlayerInstance.id.desc()))


# ---------------------------- SM-017 ----------------------------


def test_simulator_is_deterministic_and_explains(client: TestClient, db, save) -> None:
    _seed(client, save, [player_row("SIM1", "Sim Target", age=23, ca=150, pa=175, value=30_000_000, wage=60_000)])
    instance = _instance(db)
    body = {
        "instance_id": instance.id,
        "fee": 25_000_000,
        "wage": 60_000,
        "contract_years": 4,
        "budget": 80_000_000,
        "target_position": "ST",
    }
    first = client.post("/api/v1/transfers/simulate", json=body)
    second = client.post("/api/v1/transfers/simulate", json=body)
    assert first.status_code == 200, first.text
    assert first.json() == second.json(), "相同输入必须得到相同结果"
    payload = first.json()
    assert payload["cost"]["wage_cost"] == pytest.approx(60_000 * 52 * 4)
    assert payload["cost"]["total"] == pytest.approx(25_000_000 + 60_000 * 52 * 4)
    assert payload["budget"]["within_budget"] is True
    assert payload["scenarios"]["optimistic"]["ca_year3"] >= payload["scenarios"]["base"]["ca_year3"] >= payload["scenarios"]["pessimistic"]["ca_year3"]
    assert payload["recommendation"]["verdict"] in {"consider", "caution", "not_recommended", "insufficient_data"}
    assert payload["assumptions"] and "data_gaps" in payload


def test_simulator_budget_overrun(client: TestClient, db, save) -> None:
    _seed(client, save, [player_row("SIM2", "Expensive", age=25, ca=160, pa=170, value=90_000_000, wage=200_000)])
    instance = _instance(db)
    response = client.post(
        "/api/v1/transfers/simulate",
        json={"instance_id": instance.id, "fee": 90_000_000, "wage": 200_000, "contract_years": 4, "budget": 50_000_000},
    )
    body = response.json()
    assert body["budget"]["within_budget"] is False
    assert body["recommendation"]["verdict"] in {"not_recommended", "caution"}


def test_simulator_rejects_missing_player(client: TestClient, save) -> None:
    response = client.post("/api/v1/transfers/simulate", json={"instance_id": 999999})
    assert response.status_code == 404


# ---------------------------- SM-019 ----------------------------


def _add_snapshot(db, instance: PlayerInstance, *, when: date, ca: int, pa: int = 180, age: int = 20) -> None:
    db.add(
        PlayerSnapshot(
            player_instance_id=instance.id,
            observed_at=datetime.combine(when, time(12, 0)),
            game_date=when,
            age=age,
            ca=ca,
            pa=pa,
            market_value=10_000_000,
            wage=20_000,
            source="manual",
        )
    )


def test_forecast_uses_observed_rate_and_caps_at_pa(client: TestClient, db, save) -> None:
    _seed(client, save, [player_row("FC1", "Forecast Kid", age=19, ca=112, pa=140)])
    instance = _instance(db)
    # 三个快照：每 6 个月 +4 CA（约 8/年）
    for index, ca in enumerate((100, 104, 108)):
        _add_snapshot(db, instance, when=date(2024, 1, 1) + timedelta(days=182 * index), ca=ca, pa=140, age=19 + index // 2)
    db.commit()

    response = client.get(f"/api/v1/players/{instance.id}/forecast")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["basis"]["method"] == "历史快照最小二乘斜率"
    assert body["basis"]["rate_per_year"] > 0
    assert body["forecast"]["one_year"]["high"] <= 140, "预测不得超过 PA"
    assert body["ceiling"]["note"].startswith("PA 是上限参考")


def test_forecast_with_one_snapshot_is_low_confidence(client: TestClient, db, save) -> None:
    _seed(client, save, [player_row("FC2", "One Snapshot", age=24, ca=120, pa=150)])
    instance = _instance(db)
    body = client.get(f"/api/v1/players/{instance.id}/forecast").json()
    assert body["basis"]["confidence"] == "low"
    assert body["forecast"]["three_years"] is None
    assert any("不足以" in gap for gap in body["gaps"])


def test_forecast_backtest_reports_metrics(client: TestClient, db, save) -> None:
    _seed(client, save, [player_row("FC3", "Backtest Kid", age=18, ca=90, pa=150)])
    instance = _instance(db)
    for index, ca in enumerate((90, 94, 99, 105)):
        _add_snapshot(db, instance, when=date(2024, 1, 1) + timedelta(days=120 * index), ca=ca, pa=150, age=18)
    db.commit()
    body = client.get(f"/api/v1/development/forecast-backtest?min_snapshots=3").json()
    assert body["available"] is True
    assert body["evaluated"] >= 1
    assert body["mae"] is not None and body["rmse"] >= body["mae"]


# ---------------------------- SM-020 ----------------------------


def test_recommendation_respects_budget_and_weights(client: TestClient, db, save) -> None:
    _seed(
        client,
        save,
        [
            player_row("REC1", "Ready Star", age=27, ca=170, pa=175, value=60_000_000, position="ST"),
            player_row("REC2", "Young Talent", age=19, ca=120, pa=185, value=15_000_000, position="ST"),
            player_row("REC3", "Too Pricey", age=25, ca=165, pa=170, value=200_000_000, position="ST"),
        ],
        scan_id="v3-rec",
    )
    response = client.post(
        "/api/v1/recruitment/recommend",
        json={"slot": "ST", "budget": 70_000_000, "prefer": "potential", "page_size": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    names = [item["name"] for item in body["items"]]
    assert "Too Pricey" not in names, "超预算的球员必须被过滤"
    assert body["total"] >= 2
    assert all(item["score"] is not None for item in body["items"])
    assert body["coverage_note"]

    weighted = client.post(
        "/api/v1/recruitment/recommend",
        json={"slot": "ST", "budget": 70_000_000, "weights": {"potential": 0.9}},
    ).json()
    assert weighted["items"][0]["name"] == "Young Talent", "提高潜力权重后年轻高潜应排第一"


def test_recommendation_rejects_unknown_weight(client: TestClient, save) -> None:
    response = client.post("/api/v1/recruitment/recommend", json={"weights": {"magic": 1.0}})
    assert response.status_code == 422


# ---------------------------- SM-018 ----------------------------


def test_tool_whitelist_includes_phase_three_tools() -> None:
    for name in (
        "simulate_transfer",
        "player_forecast",
        "club_transfer_intelligence",
        "transfer_roi",
        "recruitment_recommend",
        "career_timeline",
    ):
        assert name in llm_planner.TOOL_SPECS


def test_simulator_tool_rejects_save_id_injection() -> None:
    with pytest.raises(llm_planner.PlannerError):
        llm_planner.parse_plan(
            {"tool_calls": [{"tool": "simulate_transfer", "arguments": {"instance_id": 1, "save_id": 2}}]}
        )


def test_llm_plan_can_call_simulator(db, save, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion.importer import ScanImporter
    from app.ingestion.protocol import ScanPayload

    document = scan_document(
        scan_id="v3-tool",
        players=[player_row("TOOL1", "Tool Target", age=22, ca=140, pa=170, value=20_000_000, wage=40_000)],
    )
    ScanImporter(db).import_payload(save.id, ScanPayload.model_validate(document))
    db.commit()
    instance = _instance(db)

    monkeypatch.setattr(settings, "agent_llm_enabled", True)
    monkeypatch.setattr(settings, "agent_llm_api_key", "test-key")

    from app.agents import llm_planner as module

    def fake_client(messages):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "tool_calls": [
                                    {
                                        "tool": "simulate_transfer",
                                        "arguments": {"instance_id": instance.id, "fee": 21_000_000},
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(module, "chat_completion", fake_client)
    answer, calls = service.answer_question(db, save.id, "这个球员值不值得买")
    assert calls[0].name == "simulate_transfer"
    assert answer["mode"] == "llm-planned"
    assert answer["reliability"]["calls"] == 1
