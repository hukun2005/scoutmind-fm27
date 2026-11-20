"""球员职业轨迹（SM-014）。

数据来源全部是已存在的表：

* `player_instances`：同一 `Player` 在不同存档中的实例（全局身份 = `Player`，不是姓名）；
* `player_snapshots`：逐次观测（CA/PA/身价/工资/合同/位置/俱乐部/来源）；
* `transfer_history`：该实例的历史交易（含 agreed/pending，分开标注）；
* `identity_matches`：该身份是怎么匹配出来的（证据与置信度）。

原则：不做任何推断式合并。跨存档只有 `Player` 行相同才属于同一职业轨迹；姓名相同不足以合并，
职业轨迹里会明确写出"哪些存档有这个球员、哪些没有观测"。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Club,
    FmSave,
    IdentityMatch,
    ImportJob,
    Player,
    PlayerInstance,
    PlayerSnapshot,
    Transfer,
)


def _season(value: date | None) -> str | None:
    if value is None:
        return None
    start = value.year if value.month >= 7 else value.year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def player_career(
    session: Session,
    instance_id: int,
    *,
    allowed_save_ids: set[int],
) -> dict[str, Any]:
    """返回一个球员实例所属全局身份的职业轨迹。"""
    instance = session.get(PlayerInstance, instance_id)
    if instance is None or instance.fm_save_id not in allowed_save_ids:
        raise ValueError("player instance not found")
    player = session.get(Player, instance.player_id)
    if player is None:
        raise ValueError("player identity not found")

    instances = list(
        session.scalars(
            select(PlayerInstance).where(
                PlayerInstance.player_id == player.id,
                PlayerInstance.fm_save_id.in_(allowed_save_ids or {-1}),
            )
        )
    )
    save_names = {
        row.id: row.name
        for row in session.scalars(select(FmSave).where(FmSave.id.in_([item.fm_save_id for item in instances] or [-1])))
    }
    instance_ids = [item.id for item in instances]

    snapshots = list(
        session.scalars(
            select(PlayerSnapshot)
            .where(PlayerSnapshot.player_instance_id.in_(instance_ids or [-1]))
            .order_by(PlayerSnapshot.observed_at, PlayerSnapshot.id)
        )
    )
    clubs = {
        row.id: row.name
        for row in session.scalars(select(Club).where(Club.id.in_([item.club_id for item in snapshots if item.club_id] or [-1])))
    }
    jobs = {
        row.id: row
        for row in session.scalars(
            select(ImportJob).where(ImportJob.id.in_([item.import_job_id for item in snapshots if item.import_job_id] or [-1]))
        )
    }
    transfers = list(
        session.scalars(
            select(Transfer)
            .where(Transfer.player_instance_id.in_(instance_ids or [-1]))
            .order_by(Transfer.transfer_date, Transfer.id)
        )
    )
    matches = list(
        session.scalars(
            select(IdentityMatch)
            .where(IdentityMatch.player_id == player.id, IdentityMatch.fm_save_id.in_(allowed_save_ids or {-1}))
            .order_by(IdentityMatch.created_at)
        )
    )

    timeline: list[dict[str, Any]] = []
    for item in snapshots:
        timeline.append(
            {
                "type": "snapshot",
                "date": item.observed_at.date().isoformat(),
                "observed_at": item.observed_at.isoformat(),
                "save_id": next(
                    (instance.fm_save_id for instance in instances if instance.id == item.player_instance_id), None
                ),
                "save_name": save_names.get(
                    next(
                        (instance.fm_save_id for instance in instances if instance.id == item.player_instance_id),
                        -1,
                    )
                ),
                "club": clubs.get(item.club_id) if item.club_id else None,
                "position": item.position,
                "ca": item.ca,
                "pa": item.pa,
                "market_value": item.market_value,
                "wage": item.wage,
                "contract_end": item.contract_end.isoformat() if item.contract_end else None,
                "source": item.source,
                "reader_version": item.reader_version,
                "game_build": item.game_build,
                "import_job_id": item.import_job_id,
                "scan_id": jobs[item.import_job_id].scan_id if item.import_job_id in jobs else None,
                "season": _season(item.game_date or item.observed_at.date()),
            }
        )
    for transfer in transfers:
        timeline.append(
            {
                "type": "transfer",
                "date": transfer.transfer_date.isoformat(),
                "status": transfer.status,
                "transfer_type": transfer.transfer_type,
                "from_club": transfer.from_club_name,
                "to_club": transfer.to_club_name,
                "base_fee": transfer.base_fee,
                "effective_fee": transfer.effective_fee,
                "loan_fee": transfer.loan_fee,
                "currency": transfer.currency,
                "source": transfer.source,
                "season": transfer.season,
                "counts_as_history": transfer.status == "completed",
            }
        )
    timeline.sort(key=lambda entry: (entry["date"], entry["type"]))

    by_season: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in timeline:
        if entry["type"] == "snapshot" and entry.get("season"):
            by_season[entry["season"]].append(entry)

    seasons = []
    for season, rows in sorted(by_season.items()):
        with_ca = [row for row in rows if row.get("ca") is not None]
        best = max(with_ca, key=lambda row: row["ca"] or 0) if with_ca else rows[-1]
        seasons.append(
            {
                "season": season,
                "observations": len(rows),
                "ca_first": rows[0].get("ca"),
                "ca_last": rows[-1].get("ca"),
                "ca_best": best.get("ca") if with_ca else None,
                "pa": rows[-1].get("pa"),
                "market_value_last": rows[-1].get("market_value"),
                "club_last": rows[-1].get("club"),
                "position_last": rows[-1].get("position"),
                "gap": "ca" if not with_ca else None,
            }
        )

    observed_saves = {item.fm_save_id for item in instances}
    missing_saves = sorted(allowed_save_ids - observed_saves)
    return {
        "player_id": player.id,
        "full_name": player.full_name,
        "birth_date": player.birth_date.isoformat() if player.birth_date else None,
        "nationality": player.nationality,
        "identity": {
            "instances": [
                {
                    "instance_id": item.id,
                    "save_id": item.fm_save_id,
                    "save_name": save_names.get(item.fm_save_id),
                    "uid": item.save_local_uid,
                    "game_unique_id": item.game_unique_id,
                    "uid_occurrence": item.uid_occurrence,
                    "last_seen_at": item.last_seen_at.isoformat(),
                }
                for item in instances
            ],
            "matches": [
                {
                    "strategy": match.strategy,
                    "confidence": match.confidence,
                    "save_id": match.fm_save_id,
                    "created_at": match.created_at.isoformat(),
                }
                for match in matches
            ],
            "note": "跨存档轨迹只按全局 Player 身份合并；姓名相同不足以合并",
        },
        "timeline": timeline,
        "seasons": seasons,
        "coverage": {
            "saves_with_player": sorted(observed_saves),
            "saves_without_player": missing_saves,
            "snapshots": len(snapshots),
            "transfers": len(transfers),
            "completed_transfers": sum(1 for item in transfers if item.status == "completed"),
            "missing": [
                label
                for label, present in (
                    ("ca", any(item.ca is not None for item in snapshots)),
                    ("pa", any(item.pa is not None for item in snapshots)),
                    ("market_value", any(item.market_value is not None for item in snapshots)),
                    ("contract", any(item.contract_end is not None for item in snapshots)),
                    ("transfer_history", any(item.status == "completed" for item in transfers)),
                )
                if not present
            ],
        },
        "algorithm_version": "career-timeline-1",
    }
