"""FastAPI application factory and process entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    routes_adapters,
    routes_compat,
    routes_datahub,
    routes_identity,
    routes_identity_center,
    routes_save_identity,
    routes_unresolved,
    routes_capture,
    routes_field_evidence,
    routes_quality,
    routes_career,
    routes_decision,
    routes_transfer_intel,
    routes_transfer_events,
    routes_transfer_history,
    routes_transfer_director,
    routes_transfer_learning,
    routes_agent,
    routes_agent_tasks,
    routes_clubs,
    routes_core,
    routes_development,
    routes_ops,
    routes_performance,
    routes_players,
    routes_recruitment,
    routes_scouting,
    routes_search,
    routes_squad,
    routes_system,
    routes_transfers,
    routes_visualization,
)
from .api.deps import require_token
from .config import settings
from .db import SessionLocal, alembic_managed, get_db, schema_ready
from .ingestion.importer import recover_interrupted_imports
from .ingestion.protocol import ProtocolError
from .models import AlgorithmVersion, ReaderCompatibility
from .utils import iso, utcnow

logger = logging.getLogger("scoutmind")

API_PREFIX = "/api/v1"


class _BodyTooLarge(Exception):
    """请求体超过 ASGI 层上限。"""


class BodySizeLimitMiddleware:
    """在 ASGI receive 层限制真实请求体字节数。

    为什么不用 BaseHTTPMiddleware + request.body()：那已经在读完之后才判断。
    这里直接包装 receive，每一块 ``http.request`` 都累计；超限抛内部异常并返回 413，
    后续的解析器（JSON / multipart）不会再收到数据。
    """

    def __init__(self, app, max_bytes: int) -> None:  # noqa: ANN001 - ASGI app
        self.app = app
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN201 - ASGI 协议
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        total = 0

        async def limited_receive():  # noqa: ANN202
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"请求体超过 {self.max_bytes} 字节上限",
                    }
                },
            )
            await response(scope, receive, send)


def create_app() -> FastAPI:
    """Build the ASGI application; used by uvicorn and by the tests."""
    app = FastAPI(
        title="ScoutMind API",
        version=settings.version,
        description="FM27 球员成长、球探与转会决策后端。所有统计数字均由确定性算法产生。",
        docs_url="/docs",
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-ScoutMind-Token"],
    )
    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        """Reject oversized bodies before the application reads them into memory."""
        length = request.headers.get("content-length")
        if length is not None:
            try:
                declared = int(length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"error": {"code": "invalid_content_length", "message": "Content-Length 不是整数"}},
                )
            if declared > settings.max_request_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": f"请求体 {declared} 字节超过上限 {settings.max_request_bytes}",
                        }
                    },
                )
        return await call_next(request)

    for router in (
        routes_core.router,
        routes_datahub.router,
        routes_adapters.router,
        routes_clubs.router,
        routes_players.router,
        routes_scouting.router,
        routes_squad.router,
        routes_recruitment.router,
        routes_development.router,
        routes_performance.router,
        routes_transfers.router,
        routes_agent.router,
        routes_agent_tasks.router,
        routes_ops.router,
        routes_compat.router,
        routes_career.router,
        routes_decision.router,
        routes_transfer_intel.router,
        routes_transfer_events.router,
        routes_transfer_history.router,
        routes_transfer_director.router,
        routes_transfer_learning.router,
        routes_identity.router,
        routes_identity_center.router,
        routes_save_identity.router,
        routes_unresolved.router,
        routes_capture.router,
        routes_field_evidence.router,
        routes_quality.router,
        routes_search.router,
        routes_system.router,
        routes_visualization.router,
    ):
        app.include_router(router, prefix=API_PREFIX, dependencies=[Depends(require_token)])

    @app.get(f"{API_PREFIX}/health")
    def health(db=Depends(get_db)) -> dict[str, Any]:
        """Public liveness probe; it never exposes stored data beyond a demo flag."""
        from sqlalchemy import select

        from .models import DataSource

        dialect = db.bind.dialect.name if db.bind is not None else "unknown"
        demo = db.scalar(select(DataSource.id).where(DataSource.source == "synthetic_fixture")) is not None
        return {
            "status": "ok",
            "version": settings.version,
            "database": dialect,
            "demo_mode": bool(demo),
            "timestamp": iso(utcnow()),
        }

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail: Any = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content={"error": detail})
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(detail)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求体或查询参数不合法",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(ProtocolError)
    async def protocol_handler(_request: Request, exc: ProtocolError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_payload", "message": str(exc)}},
        )

    @app.on_event("startup")
    def _startup() -> None:
        settings.ensure_directories()
        if not schema_ready():
            raise RuntimeError("数据库尚未迁移：请先在 backend 目录执行 alembic upgrade head")
        if not alembic_managed():
            logger.warning("数据库缺少 Alembic 版本表：后续迁移可能失败，请用 alembic upgrade head 建库")
        _seed_reference_rows()
        recovered = recover_interrupted_imports(SessionLocal)
        if recovered:
            logger.warning("已把 %d 个中断的导入任务标记为失败（可重新上传同一 scan_id 重试）", recovered)
        # V3.3.2-05.2：后台扫描任务不会永久停留在 RUNNING；可恢复的续跑，其余安全标记。
        from .services import background_scan

        resumed = background_scan.recover(SessionLocal)
        if resumed:
            logger.warning("检测到 %d 个未完成的后台任务，已按检查点恢复或安全停止", resumed)
        # V3.3.3-01：重启后中断的 Agent 任务安全标记；等待确认的任务保留可恢复。
        try:
            from .agent_runtime import get_runtime

            interrupted = get_runtime().recover()
            if interrupted:
                logger.warning("检测到 %d 个中断的 Agent 任务，已标记为失败", interrupted)
        except Exception as exc:  # noqa: BLE001 - Runtime 不可用不能阻塞旧 Agent
            logger.warning("Agent Runtime 恢复跳过：%s", exc)
        if not settings.api_token:
            logger.warning("SCOUTMIND_API_TOKEN 未配置：本地 API 无鉴权，只能监听 127.0.0.1")

    @app.on_event("shutdown")
    def _shutdown() -> None:
        from .services import background_scan

        background_scan.shutdown_executor()

    @app.get("/")
    def root():
        """Landing payload; in a release package the built SPA is served here instead."""
        index = _frontend_index()
        if index is not None:
            return FileResponse(index)
        return {"product": settings.app_name, "docs": "/docs", "api": API_PREFIX, "health": f"{API_PREFIX}/health"}

    _install_frontend(app)
    return app


def _frontend_index() -> Path | None:
    """The built SPA entry point when the release package configured one."""
    configured = (settings.frontend_dist or "").strip()
    if not configured:
        return None
    index = Path(configured).expanduser() / "index.html"
    return index if index.is_file() else None


def _install_frontend(app: FastAPI) -> None:
    """Serve a prebuilt SPA from the API port, so the release package needs no Node runtime.

    只在显式配置 ``SCOUTMIND_FRONTEND_DIST`` 且目录内确有 ``index.html`` 时启用；开发与 CI 默认关闭。
    """
    index = _frontend_index()
    if index is None:
        if settings.frontend_dist:
            logger.warning("SCOUTMIND_FRONTEND_DIST 未包含 index.html，忽略：%s", settings.frontend_dist)
        return
    dist = index.parent
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        """Static file when it exists, otherwise the SPA entry so client-side routes survive a refresh."""
        if full_path in {"api", "docs", "redoc", "openapi.json"} or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "接口不存在"})
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


def _seed_reference_rows() -> None:
    session = SessionLocal()
    try:
        from .analytics.scoring import seed_role_templates

        seed_role_templates(session)
        if session.query(AlgorithmVersion).count() == 0:
            session.add_all(
                [
                    AlgorithmVersion(key="transfer_stats", version="1", description="成交价分位数统计"),
                    AlgorithmVersion(key="similar_transfers", version="1", description="加权距离相似交易"),
                    AlgorithmVersion(key="valuation", version="1", description="可比成交估值区间"),
                    AlgorithmVersion(key="role_score", version="1", description="战术角色评分"),
                    AlgorithmVersion(key="squad_score", version="1", description="阵容六维评分（C/D/A/T/W/P）"),
                    AlgorithmVersion(key="player_score", version="1", description="球员六维评分（A/P/T/F/V/R）"),
                    AlgorithmVersion(key="development", version="1", description="成长速率与潜力区间"),
                    AlgorithmVersion(key="performance", version="1", description="分位置表现百分位"),
                    AlgorithmVersion(key="deal_model", version="1", description="转会总成本与投资效率"),
                ]
            )
        if session.query(ReaderCompatibility).count() == 0:
            session.add_all(
                [
                    ReaderCompatibility(
                        app_id="4530370",
                        build_id="26577676",
                        plugin_version="27.0.1+2503222",
                        status="candidate",
                        notes="Windows Preview 候选组合，需本机 probe 验证",
                        verified_at=None,
                    ),
                    ReaderCompatibility(
                        app_id="4530370",
                        build_id="26620374",
                        plugin_version="27.1.0+2505117",
                        status="candidate",
                        notes="本机实测观测（2026-11-18），未配置扫描器、未 probe，读取器仍会拒绝",
                        verified_at=None,
                    ),
                ]
            )
        session.commit()
    finally:
        session.close()


app = create_app()


def main() -> None:
    """Run the development server bound to loopback."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()


