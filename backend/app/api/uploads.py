"""统一的上传读取与资源保护。

所有会读取请求体的接口（扫描导入、FMSuperScout 预览 / 审查 / 导入）都必须经过这里，原因：

* ``await request.body()`` 和 ``upload.read()`` 会先把整个请求读进内存，超限判断发生在读完之后；
* multipart 的文件数量、普通字段数量和单个字段长度如果不限制，小的请求体也能制造大量对象；
* 并发上传需要限流，否则多个大文件同时解析会把内存打满；
* multipart 的临时文件必须显式关闭，否则异常路径会留下垃圾。

这里的实现只做三件事：分块读、累计计数、超限立刻抛 413。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import HTTPException, Request

from ..config import settings

CHUNK_SIZE = max(1024, int(settings.upload_chunk_size))

# 上传解析限流：预览/审查/导入都会解析整份报文，允许的并发比普通 API 更低。
_UPLOAD_SEMAPHORE = asyncio.Semaphore(max(1, int(settings.max_upload_concurrency)))


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


@asynccontextmanager
async def upload_slot() -> AsyncIterator[None]:
    """限制同一时刻解析上传报文的并发数。"""
    async with _UPLOAD_SEMAPHORE:
        yield


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

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
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


def _check_text_fields(form: Any) -> None:
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
        form = await request.form(
            max_files=settings.max_upload_files,
            max_fields=settings.max_multipart_fields,
        )
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
