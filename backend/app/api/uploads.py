"""统一的上传读取与资源保护。

所有会读取请求体的接口（扫描导入、FMSuperScout 预览 / 审查 / 导入、转会导入、阵容 CSV）都必须经过这里：

* ``await request.body()`` 和 ``upload.read()`` 会先把整个请求读进内存，超限判断发生在读完之后；
* multipart 的解析发生在 ``request.form()`` 内部，解析器会先把文件 spool 到临时目录，
  因此只在解析后检查大小已经太晚——这里用"受限 receive"在解析过程中就中断；
* 并发上传需要限流，否则多个大文件同时解析会把内存打满；
* multipart 临时文件必须显式关闭，异常路径也要关闭；
* 慢速上传 / 客户端断开不能拖住工作进程，必须有单块读取超时。
"""

from __future__ import annotations

import asyncio
import weakref
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import HTTPException, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import ClientDisconnect

from ..config import settings

CHUNK_SIZE = max(1024, int(settings.upload_chunk_size))

# 信号量按"当前事件循环"惰性创建：模块级 asyncio.Semaphore 在第一次使用时会绑定事件循环，
# 之后在另一个循环（测试里的多个 TestClient / 应用重载）里使用会抛 "bound to a different event loop"。
_SEMAPHORES: "weakref.WeakKeyDictionary[object, dict[str, asyncio.Semaphore]]" = weakref.WeakKeyDictionary()


def _semaphore(name: str, limit: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    per_loop = _SEMAPHORES.setdefault(loop, {})
    semaphore = per_loop.get(name)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, int(limit)))
        per_loop[name] = semaphore
    return semaphore

ReceiveCallable = Callable[[], Awaitable[dict[str, Any]]]


def payload_too_large(limit: int, what: str = "请求体") -> HTTPException:
    """统一的 413 响应，消息里写清是哪一类限制。"""
    return HTTPException(
        status_code=413,
        detail={"code": "payload_too_large", "message": f"{what}超过 {limit} 字节上限"},
    )


def invalid_content_length() -> HTTPException:
    """Content-Length 不是整数：这是客户端错误，不是超限。"""
    return HTTPException(
        status_code=400,
        detail={"code": "invalid_content_length", "message": "Content-Length 不是整数"},
    )


def client_gone() -> HTTPException:
    """客户端在上传过程中断开：没有完整报文，不能继续导入。"""
    return HTTPException(
        status_code=400,
        detail={"code": "client_disconnected", "message": "上传过程中连接已断开"},
    )


@asynccontextmanager
async def upload_slot() -> AsyncIterator[None]:
    """限制同一时刻解析上传报文的并发数。"""
    async with _semaphore("upload", settings.max_upload_concurrency):
        yield


@asynccontextmanager
async def import_slot() -> AsyncIterator[None]:
    """限制同一时刻写库的导入数量（SQLite 并发写会锁表）。"""
    async with _semaphore("import", settings.max_import_concurrency):
        yield


def limited_receive(
    request: Request,
    *,
    limit: int | None = None,
    what: str = "请求体",
    stall_timeout: float | None = None,
) -> ReceiveCallable:
    """包装 ASGI receive：累计真实字节数，超限立即 413；单块等待过久返回 408。

    这是"在解析过程中"生效的限制：``request.form()`` 内部每读一块都会经过这里，
    所以超大 multipart 不会先被完整 spool 到磁盘。
    """
    cap = settings.max_request_bytes if limit is None else limit
    timeout = settings.max_upload_read_seconds if stall_timeout is None else stall_timeout
    total = 0

    async def receive() -> dict[str, Any]:
        nonlocal total
        try:
            message = await asyncio.wait_for(request.receive(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=408,
                detail={"code": "upload_stalled", "message": f"上传超过 {timeout:g} 秒没有新数据，已终止"},
            ) from exc
        if message.get("type") == "http.disconnect":
            raise client_gone()
        if message.get("type") == "http.request":
            total += len(message.get("body", b""))
            if total > cap:
                raise payload_too_large(cap, what)
        return message

    return receive


class UploadForm:
    """带上限的表单解析结果；保留 ``close`` 语义。

    不直接用 ``request.form()``，因为它在解析完成后才返回；这里先用受限 receive 构造一个新的
    ``Request``，让解析器在超限时中途抛错，随后统一关闭任何已经打开的临时文件。
    """

    def __init__(self, form: Any) -> None:
        self._form = form

    def get(self, name: str) -> Any:
        return self._form.get(name)

    def multi_items(self) -> list[tuple[str, Any]]:
        return list(self._form.multi_items())

    async def close(self) -> None:
        await self._form.close()


async def open_upload_form(request: Request, *, limit: int | None = None, what: str = "上传报文") -> UploadForm:
    """解析 multipart 表单，文件数与字段数受限，解析过程中即限制总字节。"""
    receive = limited_receive(request, limit=limit, what=what)
    limited_request = Request(request.scope, receive)
    try:
        form = await limited_request.form(
            max_files=settings.max_upload_files,
            max_fields=settings.max_multipart_fields,
            # 单块/单字段上限在解析器内部生效，避免超大分片先 spool 到磁盘。
            max_part_size=settings.max_multipart_field_bytes,
        )
    except ClientDisconnect as exc:
        raise client_gone() from exc
    except (HTTPException, StarletteHTTPException, MultiPartException) as exc:
        detail = getattr(exc, "detail", None)
        # 我们自己抛出的 408/413（detail 是带 code 的字典）原样保留，不要二次包装。
        if isinstance(detail, dict) and "code" in detail:
            raise
        # Starlette 会把上限错误包装成 400 HTTPException 或 MultiPartException；
        # 统一改成语义明确的 413，调用方只需要判断一种状态码。
        raw = detail or str(exc)
        message = str(raw)
        if "Too many files" in message:
            raise HTTPException(
                status_code=413,
                detail={"code": "too_many_files", "message": f"multipart 文件数量超过 {settings.max_upload_files}"},
            ) from exc
        if "Too many fields" in message:
            raise HTTPException(
                status_code=413,
                detail={"code": "too_many_fields", "message": f"multipart 字段数量超过 {settings.max_multipart_fields}"},
            ) from exc
        if "maximum size" in message.lower() or "exceeded maximum" in message.lower():
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "field_too_large",
                    "message": f"multipart 分片超过 {settings.max_multipart_field_bytes} 字节",
                },
            ) from exc
        raise HTTPException(status_code=400, detail={"code": "invalid_multipart", "message": message}) from exc

    return UploadForm(form)


async def read_body_limited(request: Request, *, limit: int | None = None, what: str = "请求体") -> bytes:
    """分块读取请求体；超过上限立即 413，不把剩余内容读进内存。

    Content-Length 只作为"快速失败"的提示，不能作为唯一依据：chunked 请求没有这个头。
    """
    max_bytes = settings.max_import_bytes if limit is None else limit
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError as exc:
            raise invalid_content_length() from exc
        if declared_bytes > max_bytes:
            raise payload_too_large(max_bytes, what)

    limited = Request(request.scope, limited_receive(request, limit=max_bytes, what=what))
    chunks: list[bytes] = []
    total = 0
    async for chunk in limited.stream():
        total += len(chunk)
        if total > max_bytes:
            raise payload_too_large(max_bytes, what)
        chunks.append(chunk)
    return b"".join(chunks)


async def read_upload_limited(upload: Any, *, limit: int | None = None, what: str = "上传文件") -> bytes:
    """分块读取 multipart 文件；超限立即 413。"""
    max_bytes = min(settings.max_import_bytes, settings.max_multipart_field_bytes) if limit is None else limit
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise payload_too_large(max_bytes, what)
        chunks.append(chunk)
    return b"".join(chunks)


def _check_text_fields(form: UploadForm) -> None:
    """普通字段同样限制数量与长度：multipart 的文本字段也会进内存。"""
    count = 0
    for key, value in form.multi_items():
        if hasattr(value, "read"):
            continue
        count += 1
        if count > settings.max_multipart_fields:
            raise HTTPException(
                status_code=413,
                detail={"code": "too_many_fields", "message": f"multipart 字段数量超过 {settings.max_multipart_fields}"},
            )
        if isinstance(value, str) and len(value.encode("utf-8")) > settings.max_multipart_field_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "field_too_large",
                    "message": f"multipart 字段 {key} 超过 {settings.max_multipart_field_bytes} 字节",
                },
            )


async def read_request_payload(
    request: Request,
    *,
    limit: int | None = None,
    what: str = "文件内容",
    field_name: str = "file",
) -> bytes:
    """读取一个上传接口的原始字节：multipart 取 ``field_name``，其他取请求体。

    无论成功还是失败都会关闭 multipart 表单，避免临时文件泄漏。
    """
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await open_upload_form(request, limit=limit, what=what)
        try:
            _check_text_fields(form)
            upload = form.get(field_name)
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "missing_file", "message": f"缺少 {field_name} 字段"},
                )
            return await read_upload_limited(upload, limit=limit, what=what)
        finally:
            # Starlette 的表单持有 UploadFile；close() 会关闭底层文件并触发临时文件清理。
            await form.close()

    return await read_body_limited(request, limit=limit, what=what)
