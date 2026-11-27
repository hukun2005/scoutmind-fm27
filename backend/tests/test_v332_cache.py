"""V3.3.2 查询缓存：按存档与数据版本失效，导入后不会返回旧结果。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.analytics.players import coverage_for_save
from app.models import PlayerInstance
from app.services import query_cache
from tests.helpers import import_document, player_row, scan_document


def test_cache_invalidates_after_import(db) -> None:
    import_document(
        db,
        scan_document(
            scan_id="cache-1",
            when=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
            players=[player_row("P1", "Mario Bianchi", ca=150, pa=170)],
        ),
    )
    save_id = db.scalar(select(PlayerInstance.fm_save_id))
    first = coverage_for_save(db, save_id)
    assert first["ca"] == 1.0

    import_document(
        db,
        scan_document(
            scan_id="cache-2",
            when=datetime(2026, 11, 1, 12, tzinfo=timezone.utc),
            players=[
                player_row("P1", "Mario Bianchi", ca=150, pa=170),
                player_row("P2", "No Data Player", ca=None, pa=None),
            ],
        ),
    )
    second = coverage_for_save(db, save_id)
    assert second["ca"] == 0.5, "导入新数据后缓存必须失效"
    assert second != first


def test_cached_value_is_reused_within_same_revision(db, save) -> None:
    calls = {"count": 0}

    def compute():
        calls["count"] += 1
        return {"value": calls["count"]}

    first = query_cache.cached(db, save.id, "unit", {"k": 1}, compute)
    second = query_cache.cached(db, save.id, "unit", {"k": 1}, compute)
    assert first == second == {"value": 1}
    assert calls["count"] == 1
    other_save = query_cache.cached(db, save.id + 1, "unit", {"k": 1}, compute)
    assert other_save["value"] == 2, "不同存档的缓存键必须隔离"
