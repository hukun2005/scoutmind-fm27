"""真实样本 fixture 与 manifest 的完整性校验（V3.2.8.1）。

背景：V3.2.8 的 ``real_sample_01.json`` 曾与 manifest 记录的 SHA-256 不一致。
根因是登记脚本对内存里的字符串算哈希，再用文本模式写盘（Windows 上会把 ``\\n``
翻译成 ``\\r\\n``），于是"被哈希的字节"和"提交/检出的字节"不是同一份。

这里把"读磁盘字节 → 算 SHA-256 → 与 manifest 比对"固定成独立、可测试的函数：
登记脚本与回归测试共用同一套判定，避免两边口径再次分叉。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: 一条 manifest 记录必须具备的字段。
REQUIRED_ENTRY_KEYS = ("file", "sha256")


class FixtureIntegrityError(RuntimeError):
    """fixture 与 manifest 不一致；``reason`` 是可追踪的错误码。"""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def sha256_bytes(payload: bytes) -> str:
    """对**磁盘上的原始字节**计算 SHA-256（不做换行符/编码归一化）。"""
    return hashlib.sha256(payload).hexdigest()


def load_manifest(directory: Path) -> dict:
    """读取并校验 manifest 结构；缺失或损坏都抛 :class:`FixtureIntegrityError`。"""
    path = Path(directory) / "manifest.json"
    if not path.is_file():
        raise FixtureIntegrityError("manifest_missing", str(path))
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureIntegrityError("manifest_invalid", str(exc)) from exc
    if not isinstance(document, dict) or not isinstance(document.get("samples"), list):
        raise FixtureIntegrityError("manifest_invalid", "samples 缺失或不是数组")
    return document


def verify_entry(directory: Path, entry: object) -> dict:
    """校验单条记录：字段齐全、文件存在、字节哈希一致。"""
    if not isinstance(entry, dict) or any(not entry.get(key) for key in REQUIRED_ENTRY_KEYS):
        raise FixtureIntegrityError("entry_invalid", json.dumps(entry, ensure_ascii=False))

    name = str(entry["file"])
    if Path(name).name != name:
        raise FixtureIntegrityError("entry_invalid", f"file 必须是文件名而不是路径：{name}")

    path = Path(directory) / name
    if not path.is_file():
        raise FixtureIntegrityError("fixture_missing", name)

    digest = sha256_bytes(path.read_bytes())
    recorded = str(entry["sha256"]).strip().lower()
    if digest != recorded:
        raise FixtureIntegrityError(
            "hash_mismatch",
            f"{name}: manifest={recorded} actual={digest}",
        )
    return {"file": name, "sha256": digest, "bytes": path.stat().st_size}


def verify_directory(directory: Path) -> list[dict]:
    """校验目录内所有记录；返回通过校验的条目摘要。"""
    document = load_manifest(directory)
    samples = document["samples"]
    if not samples:
        raise FixtureIntegrityError("no_samples", "manifest.samples 为空")
    return [verify_entry(directory, entry) for entry in samples]
