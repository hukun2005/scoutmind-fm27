"""V3.3.3-02 性能回归：转会影响筛选下推与 Agent 事件写入。

这些测试锁定两条性能约束，同时防止筛选语义变化：

* 位置 / 联赛筛选必须下推成 SQL（不再把整张转会表读进内存），且多位置字符串
  ``"AMR, MR"`` 仍不被视为任何单码分组；
* Agent 事件在同一会话内复用 seq 缓存，``commit=False`` 可把多条事件合并为一次提交。
"""

from __future__ import annotations

from sqlalchemy import select

from app.agent_runtime.events import TaskEventBus
from app.analytics.transfers import (
    TransferFilter,
    _with_relational_filters,
    count_transfers,
    fetch_transfers,
    transfer_list_coverage,
)
from app.models import AgentTask, AgentTaskEvent, User
from tests.helpers import club_row, import_document, player_row, scan_document, transfer_row
from tests.perf_support import query_counter


def _import_players_with_positions(db) -> None:
    players = [
        player_row("P-ST", "Striker", position="ST"),
        player_row("P-AMR", "Winger", position="AMR"),
        player_row("P-MR", "Midfielder", position="MR"),
        # 真实存档里的多位置写法：旧实现只看单码，因此不属于 FW / MF。
        player_row("P-MULTI", "Multi Role", position="AMR, MR"),
    ]
    transfers = [
        transfer_row("T-ST", "P-ST", "Striker", fee=10_000_000),
        transfer_row("T-AMR", "P-AMR", "Winger", fee=20_000_000),
        transfer_row("T-MR", "P-MR", "Midfielder", fee=30_000_000),
        transfer_row("T-MULTI", "P-MULTI", "Multi Role", fee=40_000_000),
    ]
    import_document(db, scan_document(players=players, transfers=transfers))


def test_position_filter_keeps_multi_code_semantics(client, db, save) -> None:
    """FW / MF 只匹配单码位置，多码字符串既不进 FW 也不进 MF。"""
    _import_players_with_positions(db)

    forwards = client.get(f"/api/v1/transfers?save_id={save.id}&position_group=FW").json()
    assert forwards["total"] == 2
    assert {item["player_name"] for item in forwards["items"]} == {"Striker", "Winger"}

    midfielders = client.get(f"/api/v1/transfers?save_id={save.id}&position_group=MF").json()
    assert midfielders["total"] == 1
    assert midfielders["items"][0]["player_name"] == "Midfielder"


def test_position_filter_pages_in_sql_and_coverage_is_stable(client, db, save) -> None:
    """位置筛选下推后，总数、分页与覆盖率仍然描述同一个筛选集合。"""
    _import_players_with_positions(db)

    first = client.get(f"/api/v1/transfers?save_id={save.id}&position_group=FW&limit=1&offset=0").json()
    last = client.get(f"/api/v1/transfers?save_id={save.id}&position_group=FW&limit=1&offset=1").json()
    assert first["total"] == last["total"] == 2
    assert len(first["items"]) == len(last["items"]) == 1
    assert first["items"][0]["id"] != last["items"][0]["id"]
    assert first["coverage"] == last["coverage"]
    assert first["coverage"]["effective_fee"] == 1.0

    filters = TransferFilter(status="completed", position_group="FW")
    assert count_transfers(db, save.id, filters) == 2
    assert len(fetch_transfers(db, save.id, filters, limit=1, offset=1)) == 1
    assert transfer_list_coverage(db, save.id, filters)["effective_fee"] == 1.0


def test_position_filter_compiles_to_subquery_not_id_list(db, save) -> None:
    """位置筛选用子查询而非全量实例 ID 列表，避免 SQLite 变量上限（旧实现 >32k 直接报错）。"""
    query = _with_relational_filters(save.id, TransferFilter(position_group="FW"))
    sql = " ".join(str(query.compile(compile_kwargs={"literal_binds": True})).split())
    assert "IN (SELECT player_instances.id" in sql
    assert "player_instances.position IN" not in sql


def test_league_filter_matches_either_side(client, db, save) -> None:
    """联赛筛选同时匹配转出与转入俱乐部，并可与位置筛选组合。"""
    clubs = [
        club_row("C1", "Alpha", league="League A", user_club=True),
        club_row("C2", "Beta", league="League B"),
        club_row("C3", "Gamma", league="League B"),
    ]
    players = [
        player_row("P1", "Alpha Player", position="ST", club_uid="C1"),
        player_row("P2", "Beta Player", position="DC", club_uid="C2"),
    ]
    transfers = [
        transfer_row("T1", "P1", "Alpha Player", fee=1_000_000, club_from="C2", club_to="C1"),
        transfer_row("T2", "P2", "Beta Player", fee=2_000_000, club_from="C2", club_to="C3"),
    ]
    import_document(db, scan_document(players=players, transfers=transfers, clubs=clubs))

    league_a = client.get(f"/api/v1/transfers?save_id={save.id}&league=League%20A").json()
    assert league_a["total"] == 1
    assert league_a["items"][0]["player_name"] == "Alpha Player"

    league_b = client.get(f"/api/v1/transfers?save_id={save.id}&league=League%20B").json()
    assert league_b["total"] == 2

    combined = client.get(
        f"/api/v1/transfers?save_id={save.id}&league=League%20B&position_group=DF"
    ).json()
    assert combined["total"] == 1
    assert combined["items"][0]["player_name"] == "Beta Player"


def test_event_append_reuses_seq_cache_and_batches_commit(db, save) -> None:
    """同一会话连续追加：只查一次 MAX(seq)，commit=False 的事件由下一次提交带走。"""
    user = db.scalar(select(User))
    task = AgentTask(
        id="perf-task",
        thread_id="perf-thread",
        user_id=user.id,
        fm_save_id=save.id,
        task_type="general",
        user_goal="benchmark",
        status="running",
    )
    db.add(task)
    db.commit()

    bus = TaskEventBus()
    with query_counter(db.get_bind()) as counter:
        bus.append(db, task.id, "step_started", {"index": 0}, commit=False)
        bus.append(db, task.id, "tool_started", {"index": 1}, commit=False)
        bus.append(db, task.id, "tool_completed", {"index": 2})

    # 1 次 MAX(seq) + 3 次 INSERT；旧实现是 3 次 MAX + 3 次 INSERT。
    assert counter["count"] == 4
    seqs = list(
        db.scalars(
            select(AgentTaskEvent.seq)
            .where(AgentTaskEvent.task_id == task.id)
            .order_by(AgentTaskEvent.seq)
        )
    )
    assert seqs == [1, 2, 3]

    with query_counter(db.get_bind()) as counter:
        bus.append(db, task.id, "analysis_updated", {"index": 3}, commit=False)
        bus.append(db, task.id, "task_completed", {"index": 4})
    # 上一次提交已让缓存失效：新事务首次追加重新查询 MAX(seq)，之后复用缓存。
    assert counter["count"] == 3
    assert list(
        db.scalars(
            select(AgentTaskEvent.seq)
            .where(AgentTaskEvent.task_id == task.id)
            .order_by(AgentTaskEvent.seq)
        )
    ) == [1, 2, 3, 4, 5]
