"""Player identity resolution: save-local UID first, then auditable fallbacks.

A numeric UID alone is not a durable identity: FM reuses IDs of deleted created people, and separate saves can
number the same person differently. Resolution therefore records which strategy matched and how confident it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import IdentityConflict, IdentityMatch, Player, PlayerInstance
from ..utils import normalize_name, utcnow
from .protocol import PlayerRecord


@dataclass(frozen=True)
class ResolvedInstance:
    """Result of matching one incoming player row to a save-local instance."""

    instance: PlayerInstance
    created_instance: bool
    created_player: bool
    strategy: str
    confidence: float
    note: str | None = None


def _new_player(record: PlayerRecord) -> Player:
    return Player(
        full_name=record.name.strip(),
        normalized_name=normalize_name(record.name),
        birth_date=record.birth_date,
        nationality=record.nationality,
    )


def _record_match(session: Session, save_id: int, player: Player, strategy: str, confidence: float, **evidence: object) -> None:
    session.add(
        IdentityMatch(
            player_id=player.id,
            fm_save_id=save_id,
            strategy=strategy,
            confidence=confidence,
            evidence_json=_dumps(evidence),
        )
    )


def _dumps(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def resolve_player_instance(
    session: Session,
    save_id: int,
    record: PlayerRecord,
    warnings: list[str],
) -> ResolvedInstance:
    """Find or create the instance for one player row and refresh its mutable links.

    UID reuse is detected by a birth-date mismatch on the same UID; the row then becomes a new instance with an
    incremented ``uid_occurrence`` instead of silently overwriting the previous identity.
    """
    base = session.scalar(
        select(PlayerInstance).where(
            PlayerInstance.fm_save_id == save_id,
            PlayerInstance.save_local_uid == record.save_local_uid,
            PlayerInstance.uid_occurrence == 0,
        )
    )
    if base is not None:
        player = base.player
        # 缺出生日期时不能"凭 UID 就合并"：同名才认为是同一人，异名则保留为冲突。
        if record.birth_date is None and normalize_name(record.name) != player.normalized_name:
            occurrence = (
                session.scalar(
                    select(func.max(PlayerInstance.uid_occurrence)).where(
                        PlayerInstance.fm_save_id == save_id,
                        PlayerInstance.save_local_uid == record.save_local_uid,
                    )
                )
                or 0
            ) + 1
            incoming = _new_player(record)
            session.add(incoming)
            session.flush()
            instance = PlayerInstance(
                player_id=incoming.id,
                fm_save_id=save_id,
                save_local_uid=record.save_local_uid,
                uid_occurrence=occurrence,
                game_unique_id=record.game_unique_id,
                club_id=None,
                position=record.position,
                last_seen_at=utcnow(),
            )
            session.add(instance)
            session.flush()
            warnings.append(
                f"球员 UID {record.save_local_uid} 缺少出生日期且姓名与既有身份不同（{player.full_name} ≠ {record.name}），"
                "已保留为两个身份并记录冲突，未做合并"
            )
            _record_conflict(
                session,
                save_id,
                record,
                existing=player,
                incoming=incoming,
                reason="missing_birth_date_name_mismatch",
                resolution="kept_both",
            )
            _record_match(
                session,
                save_id,
                incoming,
                "uid_reuse_missing_birthdate",
                0.4,
                uid=record.save_local_uid,
                occurrence=occurrence,
                name=record.name,
                existing_name=player.full_name,
            )
            return ResolvedInstance(instance, True, True, "uid_reuse_missing_birthdate", 0.4, "缺出生日期的 UID 复用")

        if record.birth_date and player.birth_date and record.birth_date != player.birth_date:
            occurrence = (
                session.scalar(
                    select(func.max(PlayerInstance.uid_occurrence)).where(
                        PlayerInstance.fm_save_id == save_id,
                        PlayerInstance.save_local_uid == record.save_local_uid,
                    )
                )
                or 0
            ) + 1
            player = _new_player(record)
            session.add(player)
            session.flush()
            instance = PlayerInstance(
                player_id=player.id,
                fm_save_id=save_id,
                save_local_uid=record.save_local_uid,
                uid_occurrence=occurrence,
                game_unique_id=record.game_unique_id,
                club_id=None,
                position=record.position,
                last_seen_at=utcnow(),
            )
            session.add(instance)
            session.flush()
            warnings.append(
                f"球员 UID {record.save_local_uid} 的出生日期与既有身份不一致，已按 ID 复用处理并新建实例"
            )
            _record_conflict(
                session,
                save_id,
                record,
                existing=base.player,
                incoming=player,
                reason="birth_date_mismatch",
                resolution="uid_occurrence",
            )
            _record_match(
                session,
                save_id,
                player,
                "uid_reuse_new_identity",
                0.9,
                uid=record.save_local_uid,
                occurrence=occurrence,
                birth_date=record.birth_date,
            )
            return ResolvedInstance(instance, True, True, "uid_reuse_new_identity", 0.9, "UID 复用")

        if player.birth_date is None and record.birth_date is not None:
            player.birth_date = record.birth_date
        if player.nationality is None and record.nationality is not None:
            player.nationality = record.nationality
        _refresh_instance(base, record)
        return ResolvedInstance(base, False, False, "save_local_uid", 1.0)

    player: Player | None = None
    if record.birth_date is not None:
        player = session.scalar(
            select(Player)
            .join(PlayerInstance, PlayerInstance.player_id == Player.id)
            .where(
                PlayerInstance.fm_save_id == save_id,
                Player.normalized_name == normalize_name(record.name),
                Player.birth_date == record.birth_date,
            )
            .limit(1)
        )

    if player is not None:
        instance = PlayerInstance(
            player_id=player.id,
            fm_save_id=save_id,
            save_local_uid=record.save_local_uid,
            uid_occurrence=0,
            game_unique_id=record.game_unique_id,
            club_id=None,
            position=record.position,
            last_seen_at=utcnow(),
        )
        session.add(instance)
        session.flush()
        _refresh_instance(instance, record)
        _record_match(
            session,
            save_id,
            player,
            "name_birthdate",
            0.8,
            name=record.name,
            birth_date=record.birth_date,
            uid=record.save_local_uid,
        )
        return ResolvedInstance(instance, True, False, "name_birthdate", 0.8)

    player = _new_player(record)
    session.add(player)
    session.flush()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save_id,
        save_local_uid=record.save_local_uid,
        uid_occurrence=0,
        game_unique_id=record.game_unique_id,
        club_id=None,
        position=record.position,
        last_seen_at=utcnow(),
    )
    session.add(instance)
    session.flush()
    confidence = 1.0 if record.birth_date is not None else 0.6
    _record_match(
        session,
        save_id,
        player,
        "new_identity",
        confidence,
        name=record.name,
        birth_date=record.birth_date,
        uid=record.save_local_uid,
    )
    return ResolvedInstance(instance, True, True, "new_identity", confidence)


def _record_conflict(
    session: Session,
    save_id: int,
    record: PlayerRecord,
    *,
    existing: Player,
    incoming: Player,
    reason: str,
    resolution: str,
) -> None:
    """Persist one identity conflict with both sides of the evidence."""
    session.add(
        IdentityConflict(
            fm_save_id=save_id,
            save_local_uid=record.save_local_uid,
            reason=reason,
            existing_player_id=existing.id,
            incoming_player_id=incoming.id,
            existing_name=existing.full_name,
            incoming_name=record.name,
            existing_birth_date=existing.birth_date,
            incoming_birth_date=record.birth_date,
            resolution=resolution,
            evidence_json=_dumps(
                {
                    "uid": record.save_local_uid,
                    "reason": reason,
                    "existing_player_id": existing.id,
                    "incoming_player_id": incoming.id,
                }
            ),
        )
    )


def _refresh_instance(instance: PlayerInstance, record: PlayerRecord) -> None:
    instance.last_seen_at = utcnow()
    if record.game_unique_id:
        instance.game_unique_id = record.game_unique_id
    if record.position:
        instance.position = record.position
