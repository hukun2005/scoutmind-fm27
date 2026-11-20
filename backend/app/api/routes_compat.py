"""统一兼容性事实源（SM-004）。

三份配置各自回答不同问题，但必须互相一致：

* `live-reader/ScoutMind.FMReader/Versioning/verified-versions.json` — 哪个 Build 允许扫描（闸门）
* `live-reader/ScoutMind.FMReader/Versioning/compatibility-registry.json` — 哪些字段是 Verified / Candidate 及证据
* `config/compatibility.json` — 已发布的兼容性清单（桌面端读取）

这个接口把它们合并成一份只读视图，并报告互相矛盾的地方。字段状态只按证据来源分层：
`verified_fields` → Verified，`upstream_agreement_fields` → Candidate；不会因为"构建允许扫描"
就把全部字段提升为 Verified。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ROOT = BACKEND_DIR.parent
GATE_PATH = ROOT / "live-reader" / "ScoutMind.FMReader" / "Versioning" / "verified-versions.json"
REGISTRY_PATH = ROOT / "live-reader" / "ScoutMind.FMReader" / "Versioning" / "compatibility-registry.json"
PUBLISHED_PATH = ROOT / "config" / "compatibility.json"

FM27_APP_ID = "4530370"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=503, detail={"code": "config_missing", "message": f"缺少配置文件：{path.name}"})
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "config_invalid", "message": f"{path.name} 不是合法 JSON：{exc}"}
        ) from exc


def _major_minor(version: str | None) -> str | None:
    if not version:
        return None
    core = version.split("+")[0]
    parts = core.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else core


def _display_path(path: Path) -> str:
    """配置文件的展示路径：在仓库内用相对路径，测试注入的临时路径原样显示。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build_compatibility_view() -> dict[str, Any]:
    """读取三份配置并返回统一视图（含冲突列表）。"""
    gate = _load(GATE_PATH)
    registry = _load(REGISTRY_PATH)
    published = _load(PUBLISHED_PATH) if PUBLISHED_PATH.exists() else {"layouts": []}

    gate_entries = {entry["build"]: entry for entry in gate.get("layouts", [])}
    registry_entries = {entry["build"]: entry for entry in registry.get("builds", [])}
    issues: list[dict[str, str]] = []

    builds: list[dict[str, Any]] = []
    for build, entry in sorted(gate_entries.items(), key=lambda item: item[0]):
        registered = registry_entries.get(build)
        plugin = entry.get("plugin_version")
        if registered is None:
            issues.append({"code": "missing_registration", "build": build, "message": "闸门里有、注册表里没有"})
        else:
            if registered.get("layout") != entry.get("layout"):
                issues.append(
                    {
                        "code": "layout_id_mismatch",
                        "build": build,
                        "message": f"闸门 {entry.get('layout')} ≠ 注册表 {registered.get('layout')}",
                    }
                )
            if _major_minor(plugin) != _major_minor(registered.get("plugin_version")):
                issues.append(
                    {
                        "code": "plugin_version_mismatch",
                        "build": build,
                        "message": f"插件版本 {plugin} ≠ {registered.get('plugin_version')}",
                    }
                )
        if entry.get("app_id") != FM27_APP_ID:
            issues.append(
                {"code": "wrong_app_id", "build": build, "message": f"app_id={entry.get('app_id')} 不是 FM27"}
            )

        verified_fields = list((registered or {}).get("verified_fields", []))
        candidate_fields = list((registered or {}).get("upstream_agreement_fields", []))
        builds.append(
            {
                "build": build,
                "layout": entry.get("layout"),
                "status": entry.get("status"),
                "plugin_version": plugin,
                "app_id": entry.get("app_id"),
                "verified_fields": verified_fields,
                "candidate_fields": candidate_fields,
                "evidence": list((registered or {}).get("evidence", [])),
                "note": (registered or {}).get("note"),
                "counts": {
                    "verified": len(verified_fields),
                    "candidate": len(candidate_fields),
                },
            }
        )

    for build in registry_entries:
        if build not in gate_entries:
            issues.append({"code": "registration_without_gate", "build": build, "message": "注册表里有、闸门里没有"})

    verified_builds = [item for item in builds if item["status"] == "verified"]
    if verified_builds and not any(item["counts"]["verified"] for item in verified_builds):
        issues.append(
            {"code": "verified_without_fields", "build": verified_builds[0]["build"], "message": "verified 构建没有已核对字段"}
        )

    return {
        "app_id": FM27_APP_ID,
        "sources": {
            "gate": _display_path(GATE_PATH),
            "registry": _display_path(REGISTRY_PATH),
            "published": _display_path(PUBLISHED_PATH) if PUBLISHED_PATH.exists() else None,
        },
        "builds": builds,
        "published_layouts": published.get("layouts", []),
        "issues": issues,
        "consistent": not issues,
        "field_policy": {
            "verified": "verified_fields：真实 UI/扫描核对的字段",
            "candidate": "upstream_agreement_fields：与上游证据一致但未单独核对",
            "pending": "布局里有、但没有证据的字段，不参与闸门",
            "failed": "核对失败的字段，必须保留在报告里",
            "note": "整体允许扫描不代表所有字段都是 Verified",
        },
    }


@router.get("/compatibility/evidence", summary="统一兼容性事实源（三份配置合并 + 冲突检查）")
def compatibility() -> dict[str, Any]:
    """返回构建 / 字段证据 / 配置冲突，供前端与验收脚本共用。"""
    return build_compatibility_view()
