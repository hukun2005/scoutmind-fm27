"""真实样本 fixture 完整性回归（V3.2.8.1 Phase 2）。

固定检查 6 类情况：原始样本哈希正确、样本被改动、manifest 缺失、
manifest 损坏、样本缺失、样本被替换。任何一种都必须让校验失败，
不允许降级为警告或跳过。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from .fixture_integrity import FixtureIntegrityError, sha256_bytes, verify_directory

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fmsuperscout"


def _entry(document: dict, name: str) -> dict:
    return next(item for item in document["samples"] if item["file"] == name)


def _copy_sample(tmp_path: Path) -> Path:
    """把仓库样本与 manifest 复制到临时目录，供篡改测试使用。"""
    directory = tmp_path / "fmsuperscout"
    directory.mkdir()
    for name in ("manifest.json", "real_sample_01.json"):
        shutil.copy2(FIXTURE_DIR / name, directory / name)
    return directory


def test_committed_fixture_matches_manifest() -> None:
    """仓库里的真实样本必须与 manifest 记录逐字节一致。"""
    verified = verify_directory(FIXTURE_DIR)

    assert verified
    assert any(item["file"] == "real_sample_01.json" for item in verified)


def test_modified_fixture_is_rejected(tmp_path: Path) -> None:
    directory = _copy_sample(tmp_path)
    sample = directory / "real_sample_01.json"
    sample.write_bytes(sample.read_bytes() + b"\n")

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "hash_mismatch"


def test_missing_manifest_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "fmsuperscout"
    directory.mkdir()

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "manifest_missing"


def test_malformed_manifest_is_rejected(tmp_path: Path) -> None:
    directory = _copy_sample(tmp_path)
    (directory / "manifest.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "manifest_invalid"


def test_manifest_without_samples_is_rejected(tmp_path: Path) -> None:
    directory = _copy_sample(tmp_path)
    (directory / "manifest.json").write_text('{"samples": []}', encoding="utf-8")

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "no_samples"


def test_missing_fixture_is_rejected(tmp_path: Path) -> None:
    directory = _copy_sample(tmp_path)
    (directory / "real_sample_01.json").unlink()

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "fixture_missing"


def test_swapped_fixture_is_rejected(tmp_path: Path) -> None:
    """同名但内容被整体替换（JSON 仍合法）也必须失败。"""
    directory = _copy_sample(tmp_path)
    replaced = json.dumps({"meta": {"generated": "2027-03-01"}, "players": [], "staff": []})
    (directory / "real_sample_01.json").write_text(replaced, encoding="utf-8")

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "hash_mismatch"


def test_entry_without_hash_is_rejected(tmp_path: Path) -> None:
    directory = _copy_sample(tmp_path)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    _entry(manifest, "real_sample_01.json").pop("sha256")
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FixtureIntegrityError) as error:
        verify_directory(directory)
    assert error.value.reason == "entry_invalid"


def test_sha256_is_computed_over_raw_bytes() -> None:
    """哈希口径必须是磁盘字节：LF 与 CRLF 不能互相顶替。"""
    assert sha256_bytes(b"a\nb") != sha256_bytes(b"a\r\nb")
