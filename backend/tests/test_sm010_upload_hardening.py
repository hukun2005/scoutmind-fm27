"""SM-010：上传安全与资源保护加固。"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.api import uploads
from app.main import BodySizeLimitMiddleware, create_app
from app.config import settings


async def _collect(app, scope, receive):
    """直接跑一次 ASGI 调用并收集响应。"""
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    return messages


def _scope(path: str = "/api/v1/imports/fmscout/preview", headers: list[tuple[bytes, bytes]] | None = None):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [(b"content-type", b"application/json")],
        "client": ("test", 1234),
        "server": ("test", 80),
    }


def test_asgi_middleware_rejects_chunked_body_before_full_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 Content-Length 的 chunked 请求：中间件在累计超限时立即 413，不再继续读。"""
    monkeypatch.setattr(settings, "max_request_bytes", 4096)
    app = create_app()

    consumed = 0
    chunk = b"x" * 1024

    async def receive():
        nonlocal consumed
        if consumed >= 100:  # 模拟无限长的上传
            return {"type": "http.disconnect"}
        consumed += 1
        return {"type": "http.request", "body": chunk, "more_body": True}

    messages = asyncio.run(_collect(app, _scope(headers=[(b"content-type", b"application/json")]), receive))
    statuses = [message["status"] for message in messages if message["type"] == "http.response.start"]
    assert statuses == [413], messages
    assert consumed <= 10, f"超限后仍在继续读取：consumed={consumed}"


def test_multipart_upload_over_limit_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """multipart 文件超过上限：413，且不需要 Content-Length。"""
    monkeypatch.setattr(settings, "max_request_bytes", 4096)
    monkeypatch.setattr(settings, "max_import_bytes", 4096)
    client = TestClient(create_app())
    big = b'{"x": "' + b"a" * 20000 + b'"}'
    response = client.post(
        "/api/v1/imports/fmscout/preview",
        files={"file": ("dump.json", big, "application/json")},
    )
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "payload_too_large"


def test_multipart_too_many_fields_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_multipart_fields", 2)
    data = {"a": "1", "b": "2", "c": "3"}
    response = client.post(
        "/api/v1/imports/fmscout/preview",
        data=data,
        files={"file": ("dump.json", b"{}", "application/json")},
    )
    assert response.status_code in {413, 422}, response.text


def test_multipart_field_too_large_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_multipart_field_bytes", 16)
    response = client.post(
        "/api/v1/imports/fmscout/preview",
        data={"note": "x" * 100},
        files={"file": ("dump.json", b"{}", "application/json")},
    )
    assert response.status_code in {413, 422}, response.text


def test_slow_upload_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """单块数据迟迟不到：返回 408，不无限占用工作进程。"""
    from starlette.requests import Request

    monkeypatch.setattr(settings, "max_upload_read_seconds", 1)
    scope = _scope(headers=[(b"content-type", b"multipart/form-data; boundary=b")])

    async def receive():
        await asyncio.sleep(5)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def run():
        request = Request(scope, receive)
        with pytest.raises(Exception) as excinfo:
            await uploads.read_request_payload(request, what="测试上传")
        return excinfo.value

    error = asyncio.run(run())
    assert getattr(error, "status_code", None) == 408, error


def test_client_disconnect_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """客户端断开：返回明确错误，不把半截报文当完整数据。"""
    from starlette.requests import Request

    scope = _scope(headers=[(b"content-type", b"application/json")])

    async def receive():
        return {"type": "http.disconnect"}

    async def run():
        request = Request(scope, receive)
        with pytest.raises(Exception) as excinfo:
            await uploads.read_request_payload(request)
        return excinfo.value

    error = asyncio.run(run())
    assert getattr(error, "status_code", None) == 400
    assert error.detail["code"] == "client_disconnected"


def test_upload_concurrency_is_bounded() -> None:
    """上传解析的并发信号量与配置一致。"""
    async def run():
        started = []
        release = asyncio.Event()

        async def worker(index: int):
            async with uploads.upload_slot():
                started.append(index)
                await release.wait()

        tasks = [asyncio.create_task(worker(i)) for i in range(settings.max_upload_concurrency + 3)]
        await asyncio.sleep(0.05)
        assert len(started) == settings.max_upload_concurrency
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(run())


def test_normal_upload_still_works(client: TestClient, save) -> None:
    """正常导入不受加固影响。"""
    document = {
        "schema_version": "1.0",
        "source": "manual",
        "game": {"version": "27.1", "build": "26620374", "app_id": "4530370"},
        "scan": {"scan_id": "sm010-normal", "observed_at": "2026-11-20T10:00:00"},
        "coverage": {"players": True},
        "clubs": [],
        "players": [
            {
                "save_local_uid": "SM10",
                "name": "Upload Guard",
                "birth_date": "2000-01-01",
                "nationality": "England",
                "position": "ST",
                "ca": 120,
                "pa": 150,
            }
        ],
        "transfers": [],
    }
    response = client.post(
        f"/api/v1/imports/scan?save_id={save.id}",
        content=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text
