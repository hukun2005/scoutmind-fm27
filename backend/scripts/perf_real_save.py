"""真实存档副本只读基准：用真实 FM27 数据复测球员/转会读取路径。

安全约束：

* ``--database`` 必须是**副本**；脚本以只读方式使用它，不会写入生产库；
* ``SCOUTMIND_DATA_DIR`` 被强制指向临时目录，避免上传/导出文件落到真实数据目录；
* 不执行扫描、导入、迁移或任何写接口。

用法（在两个代码版本下分别运行，对应不同的库副本）::

    python scripts/perf_real_save.py \\
        --backend C:\\path\\to\\backend --database C:\\tmp\\real-opt.db \\
        --label real-optimized --repeat 3 --out C:\\tmp\\real-optimized.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, default=BACKEND_DIR)
    parser.add_argument("--database", type=Path, required=True, help="真实存档的只读副本")
    parser.add_argument("--perf-support", type=Path, default=BACKEND_DIR / "tests")
    parser.add_argument("--label", default="real")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if not args.database.exists():
        raise SystemExit(f"数据库副本不存在：{args.database}")

    sys.path.insert(0, str(args.backend))
    sys.path.insert(0, str(args.perf_support))

    # 必须在导入 app 之前设置：配置在 import 时读取环境变量。
    os.environ["SCOUTMIND_DATABASE_URL"] = f"sqlite:///{args.database.as_posix()}"
    os.environ["SCOUTMIND_DATA_DIR"] = str(Path(tempfile.gettempdir()) / "sm-perf" / "real-data")
    Path(os.environ["SCOUTMIND_DATA_DIR"]).mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.db import engine
    from app.main import app
    from app.models import Club, FmSave, Player, PlayerInstance, Transfer
    from perf_support import measure

    client = TestClient(app)
    with engine.connect() as conn:
        save_id = conn.execute(
            select(FmSave.id).where(FmSave.is_active.is_(True)).order_by(FmSave.id.desc()).limit(1)
        ).scalar_one()
        total = conn.execute(
            select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save_id)
        ).scalar_one()
        club_id = conn.execute(
            select(PlayerInstance.club_id, func.count().label("n"))
            .where(PlayerInstance.fm_save_id == save_id, PlayerInstance.club_id.is_not(None))
            .group_by(PlayerInstance.club_id)
            .order_by(func.count().desc())
            .limit(1)
        ).first()[0]
        names = [
            row[0]
            for row in conn.execute(
                select(Player.full_name)
                .join(PlayerInstance, PlayerInstance.player_id == Player.id)
                .where(PlayerInstance.fm_save_id == save_id)
                .limit(2000)
            )
        ]
        instance_ids = [
            row[0]
            for row in conn.execute(
                select(PlayerInstance.id)
                .where(PlayerInstance.fm_save_id == save_id)
                .order_by(PlayerInstance.id)
                .offset(total // 5)
                .limit(5)
            )
        ]
        league = conn.execute(
            select(Club.league).where(Club.fm_save_id == save_id, Club.league.is_not(None)).limit(1)
        ).scalar()
        transfers = conn.execute(
            select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save_id)
        ).scalar_one()

    tokens = [name.split()[-1] for name in names if name and len(name.split()[-1]) >= 4]
    token = max(set(tokens), key=tokens.count) if tokens else "a"
    deep_offset = max(0, min(total - 51, 50000))

    def get(path: str):
        def run():
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        return run

    def detail_x5():
        return [
            client.get(f"/api/v1/players/{instance_id}?save_id={save_id}").json()
            for instance_id in instance_ids
        ]

    cases = [
        ("players_list_50", get(f"/api/v1/players?save_id={save_id}&limit=50")),
        ("players_search", get(f"/api/v1/players?save_id={save_id}&query={quote(token)}&limit=50")),
        (
            "players_filter_ca_age",
            get(f"/api/v1/players?save_id={save_id}&min_ca=150&max_age=23&sort=-ca&limit=50"),
        ),
        (
            "players_filter_position",
            get(f"/api/v1/players?save_id={save_id}&position_group=FW&limit=50"),
        ),
        (
            "players_filter_club",
            get(f"/api/v1/players?save_id={save_id}&club_id={club_id}&limit=50"),
        ),
        (
            "players_deep_offset",
            get(f"/api/v1/players?save_id={save_id}&limit=50&offset={deep_offset}"),
        ),
        ("player_detail_x5", detail_x5),
        ("transfers_list_50", get(f"/api/v1/transfers?save_id={save_id}&limit=50")),
    ]
    if league:
        cases.append(
            (
                "transfers_league",
                get(f"/api/v1/transfers?save_id={save_id}&league={quote(league)}&limit=50"),
            )
        )

    results = {
        "label": args.label,
        "database": str(args.database),
        "backend": str(args.backend),
        "save_id": save_id,
        "players": total,
        "clubs": None,
        "transfers": transfers,
        "search_token": token,
        "cases": [],
    }
    for label, fn in cases:
        results["cases"].append(measure(label, fn, repeat=args.repeat, engine=engine).summary())
        print(json.dumps(results["cases"][-1], ensure_ascii=False), flush=True)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
