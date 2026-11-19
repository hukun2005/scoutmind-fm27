"""FastAPI application factory and process entry point."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    routes_adapters,
    routes_agent,
    routes_clubs,
    routes_core,
    routes_development,
    routes_ops,
    routes_performance,
    routes_players,
    routes_recruitment,
    routes_scouting,
    routes_squad,
    routes_transfers,
)
from .api.deps import require_token
from .config import settings
from .db import SessionLocal, alembic_managed, get_db, schema_ready
from .ingestion.protocol import ProtocolError
from .models import AlgorithmVersion, ReaderCompatibility
from .utils import iso, utcnow

logger = logging.getLogger("scoutmind")

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    """Build the ASGI application; used by uvicorn and by the tests."""
    app = FastAPI(
        title="ScoutMind API",
        version=settings.version,
        description="FM27 球员成长、球探与转会决策后端。所有统计数字均由确定性算法产生。",
        docs_url="/docs",
    )
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
        routes_ops.router,
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
        if not settings.api_token:
            logger.warning("SCOUTMIND_API_TOKEN 未配置：本地 API 无鉴权，只能监听 127.0.0.1")

    @app.get("/")
    def root() -> dict[str, str]:
        """Minimal landing payload so a browser hitting the host root sees something useful."""
        return {"product": settings.app_name, "docs": "/docs", "api": API_PREFIX, "health": f"{API_PREFIX}/health"}

    return app


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


