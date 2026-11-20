"""SM-004：统一兼容性事实源。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import routes_compat


def test_compatibility_view_is_consistent(client: TestClient) -> None:
    """仓库里的三份配置当前一致，并暴露 Verified/Candidate 分层。"""
    response = client.get("/api/v1/compatibility/evidence")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consistent"] is True, body["issues"]
    builds = {item["build"]: item for item in body["builds"]}
    assert "26620374" in builds
    entry = builds["26620374"]
    assert entry["status"] == "verified"
    assert entry["layout"] == "FM27_1"
    assert entry["counts"]["verified"] >= 1, "verified 构建必须有已核对字段"
    assert entry["counts"]["candidate"] >= 0
    assert body["app_id"] == "4530370"


def test_field_policy_does_not_upgrade_everything(client: TestClient) -> None:
    """整体允许扫描 ≠ 所有字段 Verified：字段状态只来自证据列表。"""
    body = client.get("/api/v1/compatibility/evidence").json()
    for build in body["builds"]:
        all_fields = set(build["verified_fields"]) | set(build["candidate_fields"])
        assert len(all_fields) >= len(build["verified_fields"])
        assert build["counts"]["verified"] == len(build["verified_fields"])
        assert build["counts"]["candidate"] == len(build["candidate_fields"])


def test_layout_mismatch_between_gate_and_registry_is_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """闸门与注册表的布局 ID 不一致 → 报告冲突，不静默取其一。"""
    gate = {
        "layouts": [
            {"layout": "FM27_9", "app_id": "4530370", "build": "26620374",
             "plugin_version": "27.1.0+2505117", "status": "verified"}
        ]
    }
    registry = {
        "builds": [
            {"build": "26620374", "layout": "FM27_1", "status": "verified",
             "plugin_version": "27.1.0+2505117", "verified_fields": ["PLAO_NAME"], "evidence": [], "note": ""}
        ]
    }
    gate_path = tmp_path / "verified-versions.json"
    registry_path = tmp_path / "compatibility-registry.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    monkeypatch.setattr(routes_compat, "GATE_PATH", gate_path)
    monkeypatch.setattr(routes_compat, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(routes_compat, "PUBLISHED_PATH", tmp_path / "missing.json")

    body = routes_compat.build_compatibility_view()
    assert body["consistent"] is False
    assert any(issue["code"] == "layout_id_mismatch" for issue in body["issues"])


def test_registration_without_gate_is_reported(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = {"layouts": []}
    registry = {
        "builds": [
            {"build": "99999999", "layout": "FM27_1", "status": "candidate",
             "plugin_version": "27.1.0+1", "verified_fields": [], "evidence": [], "note": ""}
        ]
    }
    gate_path = tmp_path / "gate.json"
    registry_path = tmp_path / "registry.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(routes_compat, "GATE_PATH", gate_path)
    monkeypatch.setattr(routes_compat, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(routes_compat, "PUBLISHED_PATH", tmp_path / "missing.json")

    body = routes_compat.build_compatibility_view()
    assert any(issue["code"] == "registration_without_gate" for issue in body["issues"])


def test_missing_config_returns_503(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(routes_compat, "GATE_PATH", tmp_path / "nope.json")
    response = client.get("/api/v1/compatibility/evidence")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "config_missing"
