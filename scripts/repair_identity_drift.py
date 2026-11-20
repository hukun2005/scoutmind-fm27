"""擦除/合并"同名同 UID、生日只差不到一年"的重复身份（默认只报告，不写库）。

背景：FMSuperScout 导出的生日是按 年龄 + 年积日 推导的，native 读取器读的是精确生日。
跨数据源导入时同一个球员会出现两个身份（生日相差几个月）。新版 identity 规则已按"生日精度差异"
处理，不再制造新重复；这个脚本只用于清理已经产生的重复。

用法：
    python scripts/repair_identity_drift.py --save 2            # 只报告
    python scripts/repair_identity_drift.py --save 2 --apply    # 真正合并（默认不执行）

合并规则（保守）：
1. 同一存档、同一 save_local_uid、uid_occurrence > 0；
2. 与 occurrence 0 的 Player 同名（normalize_name 相同）；
3. 生日差 <= 366 天；
4. 只有 occurrence>0 的实例没有任何其他引用（快照会迁移到 base 实例）时才删除身份。

不会删除任何快照：快照的 player_instance_id 改为 base 实例。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import IdentityConflict, ImportJob, PlayerInstance, PlayerSnapshot
from app.utils import normalize_name


def _engine():
    return create_engine(settings.database_url, future=True)


def find_candidates(session: Session, save_id: int) -> list[dict[str, object]]:
    bases = {
        (row.save_local_uid): row
        for row in session.scalars(
            select(PlayerInstance).where(
                PlayerInstance.fm_save_id == save_id,
                PlayerInstance.uid_occurrence == 0,
            )
        )
    }
    extras = session.scalars(
        select(PlayerInstance).where(
            PlayerInstance.fm_save_id == save_id,
            PlayerInstance.uid_occurrence > 0,
        )
    ).all()

    found: list[dict[str, object]] = []
    for extra in extras:
        base = bases.get(extra.save_local_uid)
        if base is None:
            continue
        base_player = base.player
        extra_player = extra.player
        if base_player is None or extra_player is None:
            continue
        if normalize_name(base_player.full_name) != normalize_name(extra_player.full_name):
            continue
        if not base_player.birth_date or not extra_player.birth_date:
            continue
        days = abs((base_player.birth_date - extra_player.birth_date).days)
        if days > 366:
            continue
        snapshots = session.scalar(
            select(PlayerSnapshot).where(PlayerSnapshot.player_instance_id == extra.id).limit(1)
        )
        found.append(
            {
                "save_id": save_id,
                "uid": extra.save_local_uid,
                "base_instance": base.id,
                "extra_instance": extra.id,
                "base_player": base_player.id,
                "extra_player": extra_player.id,
                "name": base_player.full_name,
                "base_birth_date": base_player.birth_date,
                "extra_birth_date": extra_player.birth_date,
                "days": days,
                "has_snapshots": snapshots is not None,
            }
        )
    return found


def apply_repair(session: Session, candidates: list[dict[str, object]], *, keep_newer_birth_date: bool = True) -> int:
    merged = 0
    for item in candidates:
        base = session.get(PlayerInstance, int(item["base_instance"]))
        extra = session.get(PlayerInstance, int(item["extra_instance"]))
        if base is None or extra is None:
            continue
        # 快照迁移到 base 实例，保留所有历史观测
        session.query(PlayerSnapshot).filter(PlayerSnapshot.player_instance_id == extra.id).update(
            {PlayerSnapshot.player_instance_id: base.id}, synchronize_session=False
        )
        base.last_seen_at = max(base.last_seen_at, extra.last_seen_at)
        if keep_newer_birth_date and extra.player and extra.player.birth_date:
            if base.player and (not base.player.birth_date or extra.player.birth_date > base.player.birth_date):
                base.player.birth_date = extra.player.birth_date
        session.query(IdentityConflict).filter(
            IdentityConflict.fm_save_id == base.fm_save_id,
            IdentityConflict.save_local_uid == base.save_local_uid,
            IdentityConflict.status == "open",
        ).update(
            {
                IdentityConflict.status: "resolved",
                IdentityConflict.resolution: "birth_date_precision_repair",
                IdentityConflict.resolved_at: __import__("datetime").datetime.utcnow(),
            },
            synchronize_session=False,
        )
        session.delete(extra)
        merged += 1
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", type=int, required=True, help="存档 id")
    parser.add_argument("--apply", action="store_true", help="真正执行合并（默认只报告）")
    args = parser.parse_args(argv)

    engine = _engine()
    with Session(engine) as session:
        candidates = find_candidates(session, args.save)
        print(f"save {args.save}: 可合并的重复身份 {len(candidates)} 个")
        for item in candidates[:10]:
            print(
                f"  uid={item['uid']} name={item['name']} "
                f"{item['base_birth_date']} vs {item['extra_birth_date']} ({item['days']} 天)"
            )
        if not args.apply:
            print("dry-run：没有写库。确认后加 --apply 执行。")
            return 0
        merged = apply_repair(session, candidates)
        session.commit()
        print(f"已合并 {merged} 个重复身份，快照已迁移，冲突标记为 resolved。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
