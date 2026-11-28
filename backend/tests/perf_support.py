"""V3.3.3-02 可重复性能数据集与计时工具（只用于基准测试，不进入业务代码）。

数据集完全由固定种子生成，写入独立的临时 SQLite 数据库：
* 不读取、不写入用户真实存档或安装目录；
* 每个规模的数据内容与顺序可复现，便于优化前后对比；
* 位置字段包含真实存档中出现的多码字符串（如 ``AMR, MR``），用于验证筛选语义不变。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from sqlalchemy import event, insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

POSITIONS: tuple[str, ...] = (
    "GK",
    "DC",
    "DL",
    "DR",
    "WBL",
    "WBR",
    "DM",
    "MC",
    "ML",
    "MR",
    "AMC",
    "AML",
    "AMR",
    "ST",
    "STC",
    # 真实 FM27 存档里的多位置写法：现有 position_group 只识别单码，保持该行为不变。
    "AMR, MR",
)
LEAGUES: tuple[str, ...] = tuple(f"League {index}" for index in range(1, 11))
TRANSFER_TYPES: tuple[str, ...] = ("permanent", "loan", "free")


def digest(value: Any) -> str:
    """结果指纹：用于证明优化前后返回内容一致。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(ratio * len(ordered)) - 1))
    return ordered[index]


@dataclass
class Timing:
    label: str
    samples: list[float] = field(default_factory=list)
    cpu_samples: list[float] = field(default_factory=list)
    queries: int = 0
    result_digest: str = ""
    error: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "runs": len(self.samples),
            "p50_ms": round(percentile(self.samples, 0.50) * 1000, 2),
            "p95_ms": round(percentile(self.samples, 0.95) * 1000, 2),
            "p99_ms": round(percentile(self.samples, 0.99) * 1000, 2),
            "min_ms": round(min(self.samples, default=0.0) * 1000, 2),
            "max_ms": round(max(self.samples, default=0.0) * 1000, 2),
            "mean_ms": round(statistics.fmean(self.samples) * 1000, 2) if self.samples else 0.0,
            "cpu_ms": round(statistics.fmean(self.cpu_samples) * 1000, 2) if self.cpu_samples else 0.0,
            "queries": self.queries,
            "result_digest": self.result_digest,
            "error": self.error,
        }


@contextmanager
def query_counter(engine: Engine) -> Iterator[dict[str, int]]:
    """统计区间内的 SQL 语句条数（每次 execute 记一条）。"""
    state = {"count": 0}

    def _before(*_args: Any, **_kwargs: Any) -> None:
        state["count"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield state
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def measure(label: str, fn: Callable[[], Any], *, repeat: int = 5, engine: Engine | None = None) -> Timing:
    """重复执行并记录耗时、SQL 条数与结果指纹。"""
    timing = Timing(label=label)
    for index in range(max(1, repeat)):
        try:
            if engine is not None:
                with query_counter(engine) as counter:
                    cpu_started = time.process_time()
                    started = time.perf_counter()
                    value = fn()
                    elapsed = time.perf_counter() - started
                    cpu_elapsed = time.process_time() - cpu_started
                if index == 0:
                    timing.queries = counter["count"]
            else:
                cpu_started = time.process_time()
                started = time.perf_counter()
                value = fn()
                elapsed = time.perf_counter() - started
                cpu_elapsed = time.process_time() - cpu_started
        except Exception as exc:  # noqa: BLE001 - 基准记录失败而不是中断整轮
            timing.error = f"{type(exc).__name__}: {exc}"[:500]
            break
        if index == 0:
            timing.result_digest = digest(value)
        timing.samples.append(elapsed)
        timing.cpu_samples.append(cpu_elapsed)
    return timing


def _chunks(rows: list[dict[str, Any]], size: int = 1000) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


@dataclass
class DatasetInfo:
    save_id: int
    user_id: int
    players: int
    transfers: int
    clubs: int
    instance_ids: list[int]
    club_ids: list[int]
    db_path: str


def seed_dataset(engine: Engine, players: int, transfers: int = 0) -> DatasetInfo:
    """按固定分布写入球员 / 快照 / 俱乐部 / 转会；可重复且与真实存档隔离。"""
    from app.models import Club, FmSave, Player, PlayerInstance, PlayerSnapshot, Transfer, User

    club_count = max(20, min(4000, players // 25 or 20))
    base_day = date(2026, 1, 1)
    now = datetime(2026, 11, 1, 12, 0, 0)

    with engine.begin() as conn:
        user_id = conn.execute(
            insert(User).values(username="local", display_name="基准用户", created_at=now, updated_at=now)
        ).lastrowid
        save_id = conn.execute(
            insert(FmSave).values(
                user_id=user_id,
                name="性能基准存档",
                game_version="27.0",
                game_build="bench",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        ).lastrowid

        club_rows = [
            {
                "id": index + 1,
                "fm_save_id": save_id,
                "uid": f"C{index + 1}",
                "name": f"Club {index + 1:05d}",
                "nation": "England",
                "league": LEAGUES[index % len(LEAGUES)],
                "reputation": 3000 + (index * 37) % 6000,
                "is_user_club": index == 0,
                "normalized_name": f"club {index + 1:05d}",
                "source": "bench",
                "confidence": 1.0,
                "external_ids_json": "{}",
                "created_at": now,
                "updated_at": now,
            }
            for index in range(club_count)
        ]
        for chunk in _chunks(club_rows):
            conn.execute(insert(Club), chunk)

        club_ids = [row["id"] for row in club_rows]
        player_rows: list[dict[str, Any]] = []
        instance_rows: list[dict[str, Any]] = []
        snapshot_rows: list[dict[str, Any]] = []
        for index in range(players):
            player_id = index + 1
            name = f"Player {index + 1:06d}"
            position = POSITIONS[index % len(POSITIONS)]
            club_id = club_ids[index % club_count]
            observed = now - timedelta(days=index % 365, minutes=index % 60)
            age = 16 + index % 22
            player_rows.append(
                {
                    "id": player_id,
                    "full_name": name,
                    "normalized_name": name.lower(),
                    "birth_date": date(2026 - age, 1 + index % 12, 1 + index % 27),
                    "nationality": "England",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            instance_rows.append(
                {
                    "id": player_id,
                    "player_id": player_id,
                    "fm_save_id": save_id,
                    "save_local_uid": f"U{player_id}",
                    "uid_occurrence": 0,
                    "game_unique_id": f"G{player_id}",
                    "club_id": club_id,
                    "position": position,
                    "last_seen_at": observed,
                    "latest_snapshot_id": player_id,
                    "club_link_source": "player_club_field",
                    "club_linked_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            snapshot_rows.append(
                {
                    "id": player_id,
                    "player_instance_id": player_id,
                    "observed_at": observed,
                    "game_date": observed.date(),
                    "imported_at": now,
                    "age": age,
                    "ca": 80 + index % 120,
                    "pa": 100 + index % 100,
                    "market_value": 100_000 + (index % 500) * 50_000,
                    "wage": 5_000 + (index % 200) * 500,
                    "contract_end": base_day + timedelta(days=365 * (1 + index % 5)),
                    "club_id": club_id,
                    "club_uid": f"C{club_id}",
                    "position": position,
                    "minutes_played": (index * 13) % 3000,
                    "appearances": (index * 7) % 40,
                    "goals": (index * 3) % 25,
                    "assists": (index * 5) % 20,
                    "data_completeness": 0.9,
                    "source": "bench",
                }
            )
            if len(player_rows) >= 1000:
                conn.execute(insert(Player), player_rows)
                conn.execute(insert(PlayerInstance), instance_rows)
                conn.execute(insert(PlayerSnapshot), snapshot_rows)
                player_rows, instance_rows, snapshot_rows = [], [], []

        if player_rows:
            conn.execute(insert(Player), player_rows)
            conn.execute(insert(PlayerInstance), instance_rows)
            conn.execute(insert(PlayerSnapshot), snapshot_rows)

        transfer_rows: list[dict[str, Any]] = []
        for index in range(transfers):
            instance_id = (index % players) + 1
            when = base_day + timedelta(days=index % 1500)
            transfer_rows.append(
                {
                    "fm_save_id": save_id,
                    "source_record_id": f"T{index + 1}",
                    "player_instance_id": instance_id,
                    "player_name": f"Player {instance_id:06d}",
                    "from_club_id": club_ids[index % club_count],
                    "to_club_id": club_ids[(index + 7) % club_count],
                    "transfer_type": TRANSFER_TYPES[index % len(TRANSFER_TYPES)],
                    "status": "completed" if index % 10 else "cancelled",
                    "transfer_date": when,
                    "season": f"{when.year}/{(when.year + 1) % 100:02d}",
                    "currency": "EUR",
                    "base_fee": float(500_000 + (index % 400) * 25_000),
                    "fee_paid": float(500_000 + (index % 400) * 25_000),
                    "effective_fee": float(500_000 + (index % 400) * 25_000),
                    "player_age_at_transfer": 16 + index % 22,
                    "player_ca_at_transfer": 80 + index % 120,
                    "player_pa_at_transfer": 100 + index % 100,
                    "contract_remaining_months": index % 48,
                    "source": "bench",
                    "confidence": 1.0,
                    "created_at": now,
                    "updated_at": now,
                }
            )
            if len(transfer_rows) >= 1000:
                conn.execute(insert(Transfer), transfer_rows)
                transfer_rows = []
        if transfer_rows:
            conn.execute(insert(Transfer), transfer_rows)

    return DatasetInfo(
        save_id=int(save_id),
        user_id=int(user_id),
        players=players,
        transfers=transfers,
        clubs=club_count,
        instance_ids=[index + 1 for index in range(players)],
        club_ids=club_ids,
        db_path=str(engine.url.database or ""),
    )


def fresh_database_path(prefix: str = "scoutmind-perf-") -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    return root / "perf.db"


def apply_migrations(db_path: Path, backend_root: Path) -> None:
    """用真实 Alembic 迁移建库，确保基准包含生产索引。"""
    from alembic import command
    from alembic.config import Config

    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    command.upgrade(config, "head")


def configure_environment(db_path: Path) -> None:
    """必须在导入 app 之前调用：把全局 engine 指向临时库。"""
    os.environ["SCOUTMIND_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["SCOUTMIND_DATA_DIR"] = str(db_path.parent / "data")
    os.environ["SCOUTMIND_AGENT_LLM_ENABLED"] = "false"
    os.environ["SCOUTMIND_AGENT_LLM_API_KEY"] = ""
    os.environ["SCOUTMIND_LEARNING_AUTO_START"] = "0"
    os.environ.pop("SCOUTMIND_API_TOKEN", None)


def session_factory() -> Callable[[], Session]:
    from sqlalchemy.orm import sessionmaker

    from app.db import engine

    return sessionmaker(bind=engine, expire_on_commit=False)
