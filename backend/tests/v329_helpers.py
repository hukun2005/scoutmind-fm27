"""V3.2.9 测试用的最小身份构造器（不经过导入管线，便于精确控制边界）。"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import FmSave, Player, PlayerInstance
from app.utils import normalize_name


def make_instance(
    db: Session,
    save: FmSave,
    *,
    uid: str,
    name: str,
    birth: date | None = date(2000, 1, 1),
    occurrence: int = 0,
    club_id: int | None = None,
    position: str = "ST",
    player: Player | None = None,
) -> PlayerInstance:
    """创建（或复用）一个球员实体及其存档内实例。"""
    if player is None:
        player = Player(
            full_name=name,
            normalized_name=normalize_name(name),
            birth_date=birth,
        )
        db.add(player)
        db.flush()
    instance = PlayerInstance(
        player_id=player.id,
        fm_save_id=save.id,
        save_local_uid=uid,
        uid_occurrence=occurrence,
        game_unique_id=f"G-{uid}-{occurrence}",
        club_id=club_id,
        position=position,
    )
    db.add(instance)
    db.flush()
    return instance
