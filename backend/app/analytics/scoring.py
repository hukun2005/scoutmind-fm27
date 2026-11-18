"""Role scoring templates and the explainable role score.

A score is only meaningful inside one template version, so templates are versioned rows and every response names
the version it used. Weights are role-specific: the product spec explicitly rejects a single generic player score.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PlayerAttribute, PlayerAttributeValue, PlayerInstance, PlayerScore, PlayerSnapshot, ScoreTemplateVersion
from ..utils import iso, utcnow

SCORE_ALGORITHM_VERSION = "role-score-1"
TEMPLATE_VERSION = 1

ROLE_TEMPLATES: tuple[dict[str, object], ...] = (
    {
        "key": "gk_goalkeeper",
        "name": "门将（GK）",
        "position_group": "GK",
        "weights": {
            "reflexes": 0.18,
            "handling": 0.16,
            "one_on_ones": 0.14,
            "aerial_reach": 0.12,
            "command_of_area": 0.10,
            "communication": 0.08,
            "kicking": 0.08,
            "rushing_out": 0.07,
            "positioning": 0.07,
        },
    },
    {
        "key": "cb_ball_playing",
        "name": "出球中卫（BPD）",
        "position_group": "DF",
        "weights": {
            "tackling": 0.16,
            "marking": 0.14,
            "positioning": 0.14,
            "heading": 0.10,
            "strength": 0.10,
            "composure": 0.10,
            "passing": 0.10,
            "anticipation": 0.09,
            "pace": 0.07,
        },
    },
    {
        "key": "fb_wing_back",
        "name": "边翼卫（WB）",
        "position_group": "DF",
        "weights": {
            "crossing": 0.15,
            "stamina": 0.14,
            "pace": 0.13,
            "tackling": 0.12,
            "positioning": 0.10,
            "teamwork": 0.10,
            "work_rate": 0.10,
            "acceleration": 0.09,
            "passing": 0.07,
        },
    },
    {
        "key": "dm_anchor",
        "name": "防守后腰（DM）",
        "position_group": "MF",
        "weights": {
            "tackling": 0.17,
            "positioning": 0.15,
            "passing": 0.15,
            "anticipation": 0.12,
            "teamwork": 0.10,
            "stamina": 0.10,
            "composure": 0.09,
            "strength": 0.06,
            "vision": 0.06,
        },
    },
    {
        "key": "cm_playmaker",
        "name": "组织核心（CM）",
        "position_group": "MF",
        "weights": {
            "passing": 0.20,
            "vision": 0.18,
            "technique": 0.14,
            "decisions": 0.12,
            "composure": 0.10,
            "teamwork": 0.08,
            "first_touch": 0.08,
            "stamina": 0.06,
            "off_the_ball": 0.04,
        },
    },
    {
        "key": "w_inside_forward",
        "name": "内锋（IF）",
        "position_group": "FW",
        "weights": {
            "dribbling": 0.18,
            "acceleration": 0.14,
            "pace": 0.14,
            "finishing": 0.12,
            "technique": 0.10,
            "off_the_ball": 0.10,
            "agility": 0.08,
            "crossing": 0.08,
            "composure": 0.06,
        },
    },
    {
        "key": "st_advanced_forward",
        "name": "突前前锋（AF）",
        "position_group": "FW",
        "weights": {
            "finishing": 0.20,
            "off_the_ball": 0.15,
            "composure": 0.13,
            "heading": 0.10,
            "anticipation": 0.10,
            "acceleration": 0.10,
            "strength": 0.08,
            "technique": 0.07,
            "dribbling": 0.07,
        },
    },
    {
        "key": "am_attacking_mid",
        "name": "前腰（AM）",
        "position_group": "MF",
        "weights": {
            "vision": 0.16,
            "passing": 0.15,
            "technique": 0.14,
            "dribbling": 0.12,
            "flair": 0.10,
            "decisions": 0.10,
            "off_the_ball": 0.09,
            "first_touch": 0.08,
            "long_shots": 0.06,
        },
    },
)


def _weights_json(template: dict[str, object]) -> str:
    import json

    return json.dumps(template["weights"], ensure_ascii=False, sort_keys=True)


def seed_role_templates(session: Session) -> None:
    """Insert missing role templates; existing versions are never overwritten."""
    existing = {
        (row.key, row.version)
        for row in session.scalars(select(ScoreTemplateVersion))
    }
    for template in ROLE_TEMPLATES:
        key = str(template["key"])
        if (key, TEMPLATE_VERSION) in existing:
            continue
        session.add(
            ScoreTemplateVersion(
                key=key,
                name=str(template["name"]),
                position_group=str(template["position_group"]),
                version=TEMPLATE_VERSION,
                weights_json=_weights_json(template),
                algorithm_version=SCORE_ALGORITHM_VERSION,
            )
        )
    session.flush()


def list_roles(session: Session) -> list[dict[str, object]]:
    """All role templates with their weights, newest version first."""
    seed_role_templates(session)
    rows = list(session.scalars(select(ScoreTemplateVersion).order_by(ScoreTemplateVersion.key)))
    import json

    return [
        {
            "key": row.key,
            "name": row.name,
            "position_group": row.position_group,
            "version": row.version,
            "algorithm_version": row.algorithm_version,
            "weights": json.loads(row.weights_json),
        }
        for row in rows
    ]


def evaluate_player(session: Session, instance_id: int, role_key: str) -> dict[str, object]:
    """Score one player against one role template and return the component breakdown."""
    seed_role_templates(session)
    template = session.scalar(
        select(ScoreTemplateVersion)
        .where(ScoreTemplateVersion.key == role_key)
        .order_by(ScoreTemplateVersion.version.desc())
        .limit(1)
    )
    if template is None:
        raise ValueError(f"unknown role template {role_key!r}")
    instance = session.get(PlayerInstance, instance_id)
    if instance is None:
        raise ValueError("player instance not found")
    snapshot = session.scalar(
        select(PlayerSnapshot)
        .where(PlayerSnapshot.player_instance_id == instance_id)
        .order_by(PlayerSnapshot.observed_at.desc())
        .limit(1)
    )
    attributes = _attribute_values(session, snapshot.id) if snapshot is not None else {}
    names = _attribute_names(session)
    import json

    weights: dict[str, float] = json.loads(template.weights_json)
    components: list[dict[str, object]] = []
    available_weight = 0.0
    total_weight = sum(weights.values()) or 1.0
    weighted_score = 0.0
    for key, weight in weights.items():
        value = attributes.get(key)
        present = value is not None
        normalized = (float(value) / 20.0) if present else None
        if present and normalized is not None:
            available_weight += weight
            weighted_score += weight * normalized
        components.append(
            {
                "key": key,
                "name": names.get(key, key),
                "weight": round(weight, 4),
                "value": value,
                "contribution": round(weight * normalized * 100, 2) if present and normalized is not None else None,
            }
        )
    coverage = available_weight / total_weight
    score = round(weighted_score / available_weight * 100, 2) if available_weight > 0 else 0.0
    scorable = [item for item in components if item["value"] is not None]
    scorable.sort(key=lambda item: float(item["value"] or 0), reverse=True)
    strengths = [f"{item['name']} {item['value']:.0f}/20" for item in scorable[:2]]
    weaknesses = [f"{item['name']} {item['value']:.0f}/20" for item in scorable[-2:] if item not in scorable[:2]]
    if coverage < 0.7:
        weaknesses.append("属性覆盖率不足 70%，评分参考价值有限")
    session.add(
        PlayerScore(
            player_instance_id=instance_id,
            role_key=role_key,
            template_version=template.version,
            score=score,
            coverage=round(coverage, 4),
            components_json=json.dumps(components, ensure_ascii=False),
        )
    )
    return {
        "instance_id": instance_id,
        "role_key": role_key,
        "role_name": template.name,
        "score": score,
        "components": components,
        "template_version": template.version,
        "algorithm_version": template.algorithm_version,
        "coverage": round(coverage, 4),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "computed_at": iso(utcnow()),
    }


def _attribute_values(session: Session, snapshot_id: int) -> dict[str, float]:
    rows = session.execute(
        select(PlayerAttribute.key, PlayerAttributeValue.value)
        .join(PlayerAttribute, PlayerAttribute.id == PlayerAttributeValue.attribute_id)
        .where(PlayerAttributeValue.player_snapshot_id == snapshot_id)
    ).all()
    return {key: float(value) for key, value in rows}


def _attribute_names(session: Session) -> dict[str, str]:
    return {row.key: row.name_zh for row in session.scalars(select(PlayerAttribute))}

